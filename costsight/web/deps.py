"""FastAPI dependency helpers — session, cache, profile resolution.

The cache is a SQLite-backed store (SqliteCache) that survives restarts
and uvicorn --reload cycles without losing warm entries. 
"""

from __future__ import annotations

import contextvars
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import boto3
from fastapi import HTTPException, Query

from costsight.aws.cost_explorer import CostExplorerClient
from costsight.aws.session import list_profiles, make_session
from costsight.web.sqlite_cache import SqliteCache

log = logging.getLogger(__name__)

# Defaults favor lower AWS API spend during normal dashboard use.
# Override with env vars for faster/near-real-time setups.
_TTL = float(os.environ.get("COSTSIGHT_CACHE_TTL_SECONDS", "1800"))          # 30 min fresh
_SWR_WINDOW = float(os.environ.get("COSTSIGHT_CACHE_SWR_SECONDS", "21600"))  # +6h stale
_CACHE_DIR = Path(os.environ.get("COSTSIGHT_CACHE_DIR", Path.home() / ".cache" / "costsight"))
_CACHE_DB = _CACHE_DIR / "cache.db"

_cache = SqliteCache(_CACHE_DB)


def cache_get(key: str) -> Any | None:
    return _cache.get(key)


def cache_get_swr(key: str) -> tuple[Any | None, bool]:
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
_refresh_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="costsight-refresh")
# Separate pool for HEAVY producers (full resource enumeration across regions —
# minutes per key). Keeping them off _refresh_pool stops a few heavy refreshes
# from monopolising all workers and starving cheap CE refreshes.
_heavy_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="costsight-refresh-heavy")
_refreshing: set[str] = set()
_refresh_lock = threading.Lock()

# Hard cap on queued+running background refreshes. With an unbounded
# SimpleQueue, heavy producers can starve hot keys and the queue grows
# without bound; once we hit this cap we shed (drop) new refresh requests
# rather than enqueue them. Per-key dedup via _refreshing still applies.
_MAX_INFLIGHT_REFRESHES = int(os.environ.get("COSTSIGHT_MAX_INFLIGHT_REFRESHES", "32"))
_inflight_refreshes = 0


def schedule_refresh(key: str, producer, heavy: bool = False) -> None:
    """Fire-and-forget background cache refresh, deduplicated by key.

    ``producer`` is a 0-arg callable that returns the new cached value.
    Only one refresh per key runs at a time; duplicates are silently
    dropped, so any number of simultaneous stale-hits still triggers
    exactly one upstream fetch. A global in-flight cap sheds new requests
    once too many refreshes are queued/running.

    ``heavy=True`` routes minutes-long resource enumerations to a dedicated
    pool so they can't monopolise the workers used for cheap CE refreshes.
    """
    with _refresh_lock:
        if key in _refreshing:
            return
        global _inflight_refreshes
        if _inflight_refreshes >= _MAX_INFLIGHT_REFRESHES:
            log.warning(
                "shedding background refresh for key=%s: in-flight cap %d reached",
                key, _MAX_INFLIGHT_REFRESHES,
            )
            return
        _refreshing.add(key)
        _inflight_refreshes += 1

    def _run() -> None:
        global _inflight_refreshes
        # Give the background producer its OWN CE counter rather than mutating
        # the triggering request's counter (which the shallow context copy
        # otherwise shares) — see middleware.set_new_counter.
        try:
            from costsight.web.middleware import set_new_counter
            set_new_counter()
        except Exception:
            pass
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
    # propagate into the pool worker instead of the worker fabricating orphan
    # state (the fresh counter above is then set within that copied context).
    ctx = contextvars.copy_context()
    pool = _heavy_pool if heavy else _refresh_pool
    try:
        pool.submit(ctx.run, _run)
    except Exception as exc:
        # submit() can raise (e.g. RuntimeError if the pool is shutting down).
        # Without this guard the _refreshing entry and in-flight slot would leak
        # forever, permanently dropping all future refreshes for this key
        #.
        log.warning("schedule_refresh: submit failed for key=%s: %s", key, type(exc).__name__)
        with _refresh_lock:
            _refreshing.discard(key)
            _inflight_refreshes -= 1


# ---------------------------------------------------------------------------
# Session + CE client factories
# ---------------------------------------------------------------------------

def get_session(profile: str = Query("default")) -> boto3.Session:
    # The profile name selects which local AWS credentials (and,
    # via credential_process, which command) are used. Never pass an arbitrary
    # client-supplied value to boto3 — validate it against the known profiles
    # first. "default" is always permitted.
    if profile and profile != "default" and profile not in set(list_profiles()):
        raise HTTPException(status_code=400, detail="Unknown AWS profile.")
    p = profile if profile and profile != "default" else None
    try:
        return make_session(profile=p)
    except Exception as exc:
        # Do NOT silently fall back to boto3.Session() here.
        # The default session may resolve to a *different* AWS account, and its
        # costs would then be cached under the requested profile's cache keys —
        # serving one account's numbers under another's name. Fail loudly so the
        # caller surfaces an error instead of showing wrong-account data.
        log.warning(
            "get_session: make_session failed for profile=%r: %s",
            p, type(exc).__name__, exc_info=True,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Could not initialize AWS session for profile {profile!r}.",
        ) from exc


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

# Rolling/relative range periods. Specific calendar months are handled
# separately via the YYYY-MM form (see ``_MONTH_PERIOD_RE``).
_RANGE_PERIODS = ("mtd", "last_month", "30d", "60d", "90d", "3m", "6m", "12m")

# A specific calendar month, e.g. "2026-05". Month 01..12 only.
_MONTH_PERIOD_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")

# How many recent calendar months to offer in the month picker.
_MONTH_PICKER_COUNT = 12


def is_valid_period(period: str) -> bool:
    """True if ``period`` is a known range key or a well-formed YYYY-MM month.

    This is the single allow-list used to validate the client-supplied
    ``period`` everywhere it is reflected (templates, cache keys, CE calls),
    closing the reflected-XSS / cache-poisoning vector.
    """
    return period in _RANGE_PERIODS or bool(_MONTH_PERIOD_RE.match(period or ""))


def period_to_window(period: str):
    from costsight.core.time_windows import (
        current_month,
        last_month,
        last_n_days,
        month_window,
        trailing_months,
    )

    m = _MONTH_PERIOD_RE.match(period or "")
    if m:
        return month_window(int(m.group(1)), int(m.group(2)))

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


def available_periods() -> list[dict]:
    """Structured period options for the UI, grouped into Ranges and Months.

    Each entry is ``{"value", "label", "group"}``. Ranges (rolling/relative)
    and specific calendar months coexist so the picker offers both at once.
    """
    from costsight.core.time_windows import recent_months

    _MONTH_NAMES = (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )
    ranges = [
        ("mtd", "Month to date"),
        ("last_month", "Last month"),
        ("30d", "Last 30 days"),
        ("90d", "Last 90 days"),
        ("3m", "Rolling 3 months"),
        ("6m", "Trailing 6 months"),
        ("12m", "Trailing 12 months"),
    ]
    out: list[dict] = [
        {"value": v, "label": label, "group": "Ranges"} for v, label in ranges
    ]
    for y, mo in recent_months(_MONTH_PICKER_COUNT):
        out.append({
            "value": f"{y:04d}-{mo:02d}",
            "label": f"{_MONTH_NAMES[mo - 1]} {y}",
            "group": "Months",
        })
    return out


# ---------------------------------------------------------------------------
# CUR + CostSource  (duckdb is optional — imports are lazy so the server
# starts fine even without the `cur` extras installed)
# ---------------------------------------------------------------------------

_CUR_DB_PATH = Path(os.environ.get("COSTSIGHT_CUR_DB", str(_CACHE_DIR / "cur.duckdb")))

_cur_conn = None  # type: ignore[assignment]
_cur_conn_lock = threading.Lock()


def get_cur_store():
    """Return a CurStore if CUR is configured and duckdb is installed, else None."""
    global _cur_conn
    if not _CUR_DB_PATH.exists():
        return None
    try:
        from costsight.cur.schema import (
            connect as _cur_connect,
        )
        from costsight.cur.schema import (
            ensure_line_items_view as _cur_ensure_view,
        )
        from costsight.cur.schema import (
            get_parquet_glob as _cur_get_glob,
        )
        from costsight.cur.store import CurStore
    except ModuleNotFoundError:
        return None
    with _cur_conn_lock:
        if _cur_conn is None:
            _cur_conn = _cur_connect(_CUR_DB_PATH)
            if _cur_get_glob(_cur_conn):
                _cur_ensure_view(_cur_conn)
    return CurStore(_cur_conn)


def get_cost_source(session: boto3.Session):
    from costsight.aws.cost_source import CostSource
    from costsight.aws.cost_store import CostStore

    ce = get_ce_client(session)
    cost_store = CostStore(ce, cache_get=cache_get, cache_set=cache_set)
    return CostSource(cur_store=get_cur_store(), cost_store=cost_store)
