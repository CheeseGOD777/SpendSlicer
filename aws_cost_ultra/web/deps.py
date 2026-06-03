"""FastAPI dependency helpers — session, cache, profile resolution.

The cache is a SQLite-backed store (SqliteCache) that survives restarts
and uvicorn --reload cycles without losing warm entries.
"""

from __future__ import annotations

import contextvars
import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

import boto3
from fastapi import Query

from aws_cost_ultra.aws.cost_explorer import CostExplorerClient
from aws_cost_ultra.aws.session import list_profiles, make_session

# Defaults favor lower AWS API spend during normal dashboard use.
# Override with env vars for faster/near-real-time setups.
_TTL = float(os.environ.get("ACU_CACHE_TTL_SECONDS", "1800"))          # 30 min fresh
_SWR_WINDOW = float(os.environ.get("ACU_CACHE_SWR_SECONDS", "21600"))  # +6h stale
_CACHE_DIR = Path(os.environ.get("ACU_CACHE_DIR", Path.home() / ".cache" / "aws_cost_ultra"))
_CACHE_DB = _CACHE_DIR / "cache.db"

from aws_cost_ultra.web.sqlite_cache import SqliteCache  # noqa: E402

_cache = SqliteCache(_CACHE_DB)


def cache_get(key: str) -> Optional[Any]:
    return _cache.get(key)


def cache_get_swr(key: str) -> tuple[Optional[Any], bool]:
    """Return ``(value, should_refresh)`` using stale-while-revalidate.

    - Fresh (age < TTL):     (value, False) — no refresh needed.
    - Stale (age < TTL+SWR): (value, True)  — serve stale, caller must kick refresh.
    - Too stale / absent:    (None,  True) — cold, caller must fetch synchronously.

    The caller stays responsible for kicking the background refresh so
    this module doesn't need knowledge of handler logic.
    """
    return _cache.get_swr(key)


def cache_set(key: str, val: Any, ttl_seconds: float | None = None, swr_seconds: float | None = None) -> None:
    _cache.set(
        key,
        val,
        ttl_seconds=_TTL if ttl_seconds is None else ttl_seconds,
        swr_seconds=_SWR_WINDOW if swr_seconds is None else swr_seconds,
    )


def cache_bust(prefix: str = "") -> int:
    return _cache.bust(prefix)


# ---------------------------------------------------------------------------
# Background-refresh thread pool — for stale-while-revalidate handlers
# ---------------------------------------------------------------------------
from concurrent.futures import ThreadPoolExecutor  # noqa: E402

_refresh_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="acu-refresh")
_refreshing: set[str] = set()
_refresh_lock = threading.Lock()

# Hard cap on queued+running background refreshes. With an unbounded
# SimpleQueue, heavy producers can starve hot keys and the queue grows
# without bound; once we hit this cap we shed (drop) new refresh requests
# rather than enqueue them. Per-key dedup via _refreshing still applies.
_MAX_INFLIGHT_REFRESHES = int(os.environ.get("ACU_MAX_INFLIGHT_REFRESHES", "32"))
_inflight_refreshes = 0


def schedule_refresh(key: str, producer) -> None:
    """Fire-and-forget background cache refresh, deduplicated by key.

    ``producer`` is a 0-arg callable that returns the new cached value.
    Only one refresh per key runs at a time; duplicates are silently
    dropped, so any number of simultaneous stale-hits still triggers
    exactly one upstream fetch. A global in-flight cap sheds new requests
    once too many refreshes are queued/running.
    """
    with _refresh_lock:
        if key in _refreshing:
            return
        global _inflight_refreshes
        if _inflight_refreshes >= _MAX_INFLIGHT_REFRESHES:
            log.debug(
                "shedding background refresh for key=%s: in-flight cap %d reached",
                key, _MAX_INFLIGHT_REFRESHES,
            )
            return
        _refreshing.add(key)
        _inflight_refreshes += 1

    def _run() -> None:
        global _inflight_refreshes
        try:
            val = producer()
            if val is not None:
                cache_set(key, val)
        except Exception as exc:
            log.warning("background cache refresh failed for key=%s: %s", key, type(exc).__name__, exc_info=True)
        finally:
            with _refresh_lock:
                _refreshing.discard(key)
                _inflight_refreshes -= 1

    # Run the producer in a copy of the request's context so contextvars
    # (e.g. the CE call counter) propagate into the pool worker instead of
    # the worker fabricating orphan state.
    ctx = contextvars.copy_context()
    _refresh_pool.submit(ctx.run, _run)


# ---------------------------------------------------------------------------
# Session + CE client factories
# ---------------------------------------------------------------------------

def get_session(profile: str = Query("default")) -> boto3.Session:
    p = profile if profile and profile != "default" else None
    try:
        return make_session(profile=p)
    except Exception as exc:
        log.warning("get_session: make_session failed for profile=%r, falling back to default session: %s", p, type(exc).__name__, exc_info=True)
        return boto3.Session()


def get_ce_client(session: boto3.Session) -> CostExplorerClient:
    """Construct a CostExplorerClient bound to ``session``.

    We deliberately do NOT cache here. get_session/make_session builds a
    fresh boto3.Session per request, so caching keyed by id(session) grew
    an unbounded per-thread dict (the ids are always distinct). Client
    construction is cheap relative to the CE round-trip, and the wrapper
    pins its own session, so a per-call client is both correct and safe.
    """
    return CostExplorerClient(session=session)


def get_profiles() -> list[str]:
    profiles = list_profiles()
    return profiles if profiles else ["default"]


# ---------------------------------------------------------------------------
# Region list — used by the audit/resources region selectors
# ---------------------------------------------------------------------------

COMMON_REGIONS: list[tuple[str, str]] = [
    ("ap-south-1",      "Mumbai"),
    ("us-east-1",       "N. Virginia"),
    ("us-east-2",       "Ohio"),
    ("us-west-1",       "N. California"),
    ("us-west-2",       "Oregon"),
    ("eu-west-1",       "Ireland"),
    ("eu-west-2",       "London"),
    ("eu-central-1",    "Frankfurt"),
    ("ap-southeast-1",  "Singapore"),
    ("ap-southeast-2",  "Sydney"),
    ("ap-northeast-1",  "Tokyo"),
    ("ap-northeast-2",  "Seoul"),
    ("ca-central-1",    "Canada"),
    ("sa-east-1",       "São Paulo"),
]


# ---------------------------------------------------------------------------
# Period → TimeWindow helper
# ---------------------------------------------------------------------------

def period_to_window(period: str):
    from aws_cost_ultra.core.time_windows import (
        current_month,
        last_month,
        last_n_days,
        trailing_months,
    )

    mapping = {
        "mtd":    current_month,
        "30d":    lambda: last_n_days(30),
        "60d":    lambda: last_n_days(60),
        "90d":    lambda: last_n_days(90),
        "last_month": last_month,
        # UX expectation: "Last 3 months" means rolling window including current.
        "3m":     lambda: last_n_days(90),
        # Keep legacy keys for backward-compatible URLs.
        "6m":     lambda: trailing_months(6),
        "12m":    lambda: trailing_months(12),
    }
    fn = mapping.get(period, current_month)
    return fn()


# ---------------------------------------------------------------------------
# CUR + CostSource  (duckdb is optional — imports are lazy so the server
# starts fine even without the `cur` extras installed)
# ---------------------------------------------------------------------------

_CUR_DB_PATH = Path(os.environ.get("ACU_CUR_DB", str(_CACHE_DIR / "cur.duckdb")))

_cur_conn = None  # type: ignore[assignment]
_cur_conn_lock = threading.Lock()


def get_cur_store():
    """Return a CurStore if CUR is configured and duckdb is installed, else None."""
    global _cur_conn
    if not _CUR_DB_PATH.exists():
        return None
    try:
        from aws_cost_ultra.cur.schema import (
            connect as _cur_connect,
            ensure_line_items_view as _cur_ensure_view,
            get_parquet_glob as _cur_get_glob,
        )
        from aws_cost_ultra.cur.store import CurStore
    except ModuleNotFoundError:
        return None
    with _cur_conn_lock:
        if _cur_conn is None:
            _cur_conn = _cur_connect(_CUR_DB_PATH)
            if _cur_get_glob(_cur_conn):
                _cur_ensure_view(_cur_conn)
    return CurStore(_cur_conn)


def get_cost_source(session: boto3.Session):
    from aws_cost_ultra.aws.cost_source import CostSource
    from aws_cost_ultra.aws.cost_store import CostStore

    ce = get_ce_client(session)
    cost_store = CostStore(ce, cache_get=cache_get, cache_set=cache_set)
    return CostSource(cur_store=get_cur_store(), cost_store=cost_store)
