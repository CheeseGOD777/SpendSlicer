"""FastAPI dependency helpers — session, cache, profile resolution.

The cache is an in-memory dict (fast) backed by a JSON file so it
survives uvicorn --reload cycles. Reloads were previously evicting
every entry and forcing a cold re-fetch of every AWS call.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

import boto3
from fastapi import Query

from aws_cost_ultra.aws.cost_explorer import CostExplorerClient
from aws_cost_ultra.aws.session import list_profiles, make_session

# Defaults favor lower AWS API spend during normal dashboard use.
# Override with env vars for faster/near-real-time setups.
_TTL = float(os.environ.get("ACU_CACHE_TTL_SECONDS", "1800"))          # 30 min fresh
_SWR_WINDOW = float(os.environ.get("ACU_CACHE_SWR_SECONDS", "21600"))  # +6h stale
_CACHE_DIR = Path(os.environ.get("ACU_CACHE_DIR", Path.home() / ".cache" / "aws_cost_ultra"))
_CACHE_FILE = _CACHE_DIR / "api_cache.json"

_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


def _load_from_disk() -> None:
    """Hydrate the in-memory cache from disk on startup.

    Entries within TTL + SWR_WINDOW are kept so stale-but-usable data
    survives a restart. Anything beyond that window is discarded.
    """
    if not _CACHE_FILE.exists():
        return
    try:
        with _CACHE_FILE.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        now = time.time()
        with _lock:
            for k, (ts, val) in raw.items():
                if (now - ts) < (_TTL + _SWR_WINDOW):
                    _cache[k] = (ts, val)
    except (json.JSONDecodeError, OSError, ValueError):
        # Corrupt cache → start fresh. Not worth crashing the app over.
        pass


def _flush_to_disk() -> None:
    """Atomic write of the current in-memory cache to disk.

    Writes to a temp file in the same directory, then renames — POSIX
    rename is atomic, so concurrent readers never see a partial file.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        snapshot = dict(_cache)
    try:
        fd, tmp_path = tempfile.mkstemp(
            prefix=".api_cache.",
            suffix=".json",
            dir=str(_CACHE_DIR),
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(snapshot, f)
        os.replace(tmp_path, _CACHE_FILE)
    except (OSError, TypeError):
        # JSON can't serialise some value → swallow; the in-memory
        # cache still holds the entry for this process.
        try:
            os.unlink(tmp_path)
        except (OSError, UnboundLocalError, NameError):
            pass


# Flushes are debounced so rapid sets (during pre-warm or a page load
# that hits many endpoints) don't spam the filesystem.
_pending_flush = threading.Event()


def _flush_worker() -> None:
    while True:
        _pending_flush.wait()
        _pending_flush.clear()
        time.sleep(1.0)  # debounce window
        _flush_to_disk()


_flush_thread = threading.Thread(target=_flush_worker, daemon=True, name="acu-cache-flush")
_flush_thread.start()

# Hydrate on module load — uvicorn --reload re-imports the module, so
# this runs on every reload and restores the warm cache immediately.
_load_from_disk()


def cache_get(key: str) -> Optional[Any]:
    with _lock:
        entry = _cache.get(key)
        if entry and (time.time() - entry[0]) < _TTL:
            return entry[1]
        if entry:
            del _cache[key]
    return None


def cache_get_swr(key: str) -> tuple[Optional[Any], bool]:
    """Return ``(value, should_refresh)`` using stale-while-revalidate.

    - Fresh (age < TTL):     (value, False) — no refresh needed.
    - Stale (age < TTL+SWR): (value, True)  — serve stale, caller must kick refresh.
    - Too stale / absent:    (None,  True) — cold, caller must fetch synchronously.

    The caller stays responsible for kicking the background refresh so
    this module doesn't need knowledge of handler logic.
    """
    with _lock:
        entry = _cache.get(key)
        if not entry:
            return None, True
        age = time.time() - entry[0]
        if age < _TTL:
            return entry[1], False
        if age < _TTL + _SWR_WINDOW:
            return entry[1], True
        # Drop entries past the SWR window so the file doesn't grow forever.
        del _cache[key]
        return None, True


def cache_set(key: str, val: Any) -> None:
    with _lock:
        _cache[key] = (time.time(), val)
    _pending_flush.set()


def cache_bust(prefix: str = "") -> int:
    with _lock:
        keys = [k for k in _cache if k.startswith(prefix)]
        for k in keys:
            del _cache[k]
    _pending_flush.set()
    return len(keys)


# ---------------------------------------------------------------------------
# Background-refresh thread pool — for stale-while-revalidate handlers
# ---------------------------------------------------------------------------
from concurrent.futures import ThreadPoolExecutor  # noqa: E402

_refresh_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="acu-refresh")
_refreshing: set[str] = set()
_refresh_lock = threading.Lock()


def schedule_refresh(key: str, producer) -> None:
    """Fire-and-forget background cache refresh, deduplicated by key.

    ``producer`` is a 0-arg callable that returns the new cached value.
    Only one refresh per key runs at a time; duplicates are silently
    dropped, so any number of simultaneous stale-hits still triggers
    exactly one upstream fetch.
    """
    with _refresh_lock:
        if key in _refreshing:
            return
        _refreshing.add(key)

    def _run() -> None:
        try:
            val = producer()
            if val is not None:
                cache_set(key, val)
        except Exception:
            pass  # swallow — a failed refresh leaves the stale value in place
        finally:
            with _refresh_lock:
                _refreshing.discard(key)

    _refresh_pool.submit(_run)


# ---------------------------------------------------------------------------
# Session + CE client factories
# ---------------------------------------------------------------------------

def get_session(profile: str = Query("default")) -> boto3.Session:
    p = profile if profile and profile != "default" else None
    try:
        return make_session(profile=p)
    except Exception:
        return boto3.Session()


def get_ce_client(session: boto3.Session) -> CostExplorerClient:
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
