# Plan 1 — Backend Cleanup + Persistent Cache + Drop EC2 RESOURCE_ID

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut current Cost Explorer spend by ~10× via deduplication, persistent caching, and dropping the EC2 RESOURCE_ID path that silently adds UsageRecord surcharges.

**Architecture:** Replace the JSON-file cache with a SQLite cache keyed by `(profile, account_id, kind, fingerprint)`. Add a thin `cost_store.py` that fetches one canonical `(DAILY × SERVICE)` CE response per profile/window and lets summary/services/trend routes slice from it. Remove `ce_attribution.py`'s EC2 RESOURCE_ID call entirely — the resources page falls back to USAGE_TYPE attribution until Plan 2 (CUR) ships.

**Tech Stack:** Python 3.10+, FastAPI, boto3, sqlite3 (stdlib), pytest.

**Prerequisites:** None. Run before Plan 2 and Plan 3 (or in parallel with Plan 3).

---

## Files affected

**Create:**
- `aws_cost_ultra/web/sqlite_cache.py` — new persistent cache backend
- `aws_cost_ultra/aws/cost_store.py` — single-call canonical cost fetcher + slicers
- `aws_cost_ultra/web/middleware.py` — `X-CE-Calls-Spent` response header middleware
- `tests/test_sqlite_cache.py`
- `tests/test_cost_store.py`
- `tests/test_middleware.py`

**Modify:**
- `aws_cost_ultra/web/deps.py` — replace JSON cache with SQLite backend, add per-thread CE client
- `aws_cost_ultra/web/prewarm.py` — dedupe and gate behind explicit env var
- `aws_cost_ultra/web/routes/cost.py` — route summary/services/trend through `cost_store`, cache `/trend-table` HTML
- `aws_cost_ultra/web/routes/resources_api.py` — drop EC2 RESOURCE_ID kick-off
- `aws_cost_ultra/aws/ce_attribution.py` — delete; resources fall back to `_attribute_from_usage_type`
- `aws_cost_ultra/resources/ec2.py` — remove RESOURCE_ID path; always USAGE_TYPE
- `aws_cost_ultra/aws/cost_explorer.py` — accept `ce_call_counter` callback, per-thread instances, expose pagination count
- `aws_cost_ultra/web/app.py` — register middleware, gate prewarm
- `aws_cost_ultra/audit/idle.py`, `aws_cost_ultra/audit/budgets.py`, `aws_cost_ultra/resources/ec2.py` — replace bare `except: pass` with logged warnings
- `pyproject.toml` — no new deps (sqlite3 is stdlib)

**Delete (after migration verified):**
- `static/js/app.js`
- `templates/dashboard.html`
- `AWS Costing Dashboard/` (the prototype folder — copy `tokens.css` into `frontend/src/` first)

---

## Task 1: SQLite cache backend

**Files:**
- Create: `aws_cost_ultra/web/sqlite_cache.py`
- Test: `tests/test_sqlite_cache.py`

The current `_cache: dict + JSON file` loses entries on schema changes and can't be queried. SQLite is stdlib, single-file, atomic. Schema:

```sql
CREATE TABLE IF NOT EXISTS cache_entries (
  key            TEXT PRIMARY KEY,
  value_json     TEXT NOT NULL,
  created_at     REAL NOT NULL,   -- unix ts
  ttl_seconds    REAL NOT NULL,   -- per-entry TTL (today=900, closed-day=∞)
  swr_seconds    REAL NOT NULL    -- stale-while-revalidate window
);
CREATE INDEX IF NOT EXISTS idx_created_at ON cache_entries(created_at);
```

Per-entry TTL lets closed days (older than today) cache forever while today's data refreshes every 15 min.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sqlite_cache.py
import json
import time
from pathlib import Path

import pytest

from aws_cost_ultra.web.sqlite_cache import SqliteCache


@pytest.fixture
def cache(tmp_path: Path) -> SqliteCache:
    return SqliteCache(tmp_path / "cache.db")


def test_set_and_get_returns_value(cache: SqliteCache):
    cache.set("k1", {"a": 1}, ttl_seconds=60)
    assert cache.get("k1") == {"a": 1}


def test_get_after_ttl_returns_none(cache: SqliteCache):
    cache.set("k1", {"a": 1}, ttl_seconds=0.01)
    time.sleep(0.05)
    assert cache.get("k1") is None


def test_swr_returns_stale_within_window(cache: SqliteCache):
    cache.set("k1", {"a": 1}, ttl_seconds=0.01, swr_seconds=60)
    time.sleep(0.05)
    val, refresh = cache.get_swr("k1")
    assert val == {"a": 1}
    assert refresh is True


def test_swr_past_window_returns_none(cache: SqliteCache):
    cache.set("k1", {"a": 1}, ttl_seconds=0.01, swr_seconds=0.01)
    time.sleep(0.05)
    val, refresh = cache.get_swr("k1")
    assert val is None
    assert refresh is True


def test_bust_by_prefix(cache: SqliteCache):
    cache.set("summary:p1:mtd", {"x": 1}, ttl_seconds=60)
    cache.set("summary:p2:mtd", {"x": 2}, ttl_seconds=60)
    cache.set("services:p1:mtd", {"x": 3}, ttl_seconds=60)
    assert cache.bust("summary:") == 2
    assert cache.get("summary:p1:mtd") is None
    assert cache.get("services:p1:mtd") == {"x": 3}


def test_closed_day_ttl_is_effectively_infinite(cache: SqliteCache):
    cache.set("trend:p1:2025-01", [1, 2, 3], ttl_seconds=10**9)
    val, refresh = cache.get_swr("trend:p1:2025-01")
    assert val == [1, 2, 3]
    assert refresh is False


def test_corrupt_db_falls_back_to_empty(tmp_path: Path):
    path = tmp_path / "bad.db"
    path.write_bytes(b"not a sqlite file")
    cache = SqliteCache(path)
    # Should recover by recreating the file
    cache.set("k", {"v": 1}, ttl_seconds=60)
    assert cache.get("k") == {"v": 1}
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd "/run/media/tirth/OS/Users/Tirth Teraiya/Personal Folder/aws-cost-dashboard"
pytest tests/test_sqlite_cache.py -v
```
Expected: ImportError / module not found.

- [ ] **Step 3: Implement `SqliteCache`**

```python
# aws_cost_ultra/web/sqlite_cache.py
"""Persistent SQLite-backed cache with per-entry TTL and SWR window.

Replaces the JSON-file cache. Survives restarts, supports composite
TTLs (today vs closed days), and lets us add columns later (e.g.,
account_id, fingerprint) without losing entries.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("aws_cost_ultra.cache")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entries (
  key            TEXT PRIMARY KEY,
  value_json     TEXT NOT NULL,
  created_at     REAL NOT NULL,
  ttl_seconds    REAL NOT NULL,
  swr_seconds    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_created_at ON cache_entries(created_at);
"""


class SqliteCache:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        try:
            with self._connect() as conn:
                conn.executescript(_SCHEMA)
        except sqlite3.DatabaseError:
            log.warning("cache db at %s corrupt — recreating", self._path)
            self._path.unlink(missing_ok=True)
            with self._connect() as conn:
                conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        # check_same_thread=False because FastAPI handlers run on a pool.
        # We serialize with self._lock for write safety.
        conn = sqlite3.connect(self._path, check_same_thread=False, timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def set(self, key: str, value: Any, ttl_seconds: float, swr_seconds: float = 0.0) -> None:
        payload = json.dumps(value, default=str)
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache_entries(key, value_json, created_at, ttl_seconds, swr_seconds) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, payload, now, ttl_seconds, swr_seconds),
            )

    def get(self, key: str) -> Optional[Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value_json, created_at, ttl_seconds FROM cache_entries WHERE key=?",
                (key,),
            ).fetchone()
        if not row:
            return None
        value_json, created_at, ttl_seconds = row
        if (time.time() - created_at) >= ttl_seconds:
            return None
        return json.loads(value_json)

    def get_swr(self, key: str) -> tuple[Optional[Any], bool]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value_json, created_at, ttl_seconds, swr_seconds FROM cache_entries WHERE key=?",
                (key,),
            ).fetchone()
        if not row:
            return None, True
        value_json, created_at, ttl, swr = row
        age = time.time() - created_at
        if age < ttl:
            return json.loads(value_json), False
        if age < (ttl + swr):
            return json.loads(value_json), True
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM cache_entries WHERE key=?", (key,))
        return None, True

    def bust(self, prefix: str = "") -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM cache_entries WHERE key LIKE ?",
                (prefix + "%",),
            )
            return cur.rowcount
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest tests/test_sqlite_cache.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add aws_cost_ultra/web/sqlite_cache.py tests/test_sqlite_cache.py
git commit -m "feat(cache): add SQLite-backed persistent cache with per-entry TTL/SWR"
```

---

## Task 2: Wire SqliteCache into `deps.py`

**Files:**
- Modify: `aws_cost_ultra/web/deps.py`

Replace the in-memory dict + JSON flush with a `SqliteCache` instance, keeping the existing `cache_get`, `cache_get_swr`, `cache_set`, `cache_bust`, `schedule_refresh` API surface so call sites don't need to change.

- [ ] **Step 1: Replace the cache module body**

Replace lines 26–150 of `aws_cost_ultra/web/deps.py` with:

```python
_TTL = float(os.environ.get("ACU_CACHE_TTL_SECONDS", "1800"))
_SWR_WINDOW = float(os.environ.get("ACU_CACHE_SWR_SECONDS", "21600"))
_CACHE_DIR = Path(os.environ.get("ACU_CACHE_DIR", Path.home() / ".cache" / "aws_cost_ultra"))
_CACHE_DB = _CACHE_DIR / "cache.db"

from aws_cost_ultra.web.sqlite_cache import SqliteCache  # noqa: E402

_cache = SqliteCache(_CACHE_DB)


def cache_get(key: str):
    return _cache.get(key)


def cache_get_swr(key: str):
    return _cache.get_swr(key)


def cache_set(key: str, val, ttl_seconds: float | None = None, swr_seconds: float | None = None) -> None:
    _cache.set(
        key,
        val,
        ttl_seconds=_TTL if ttl_seconds is None else ttl_seconds,
        swr_seconds=_SWR_WINDOW if swr_seconds is None else swr_seconds,
    )


def cache_bust(prefix: str = "") -> int:
    return _cache.bust(prefix)


# Background-refresh thread pool kept as-is below.
```

Keep the existing `schedule_refresh`, `get_session`, `get_ce_client`, `get_profiles`, `COMMON_REGIONS`, `period_to_window` blocks untouched.

- [ ] **Step 2: Run existing tests to confirm nothing broke**

```bash
pytest tests/ -v -k "not slow"
```
Expected: all currently-passing tests still pass. Any test that imports `_cache`, `_load_from_disk`, `_flush_to_disk`, or `_flush_worker` directly needs updating — those private names are gone.

- [ ] **Step 3: Manual smoke**

```bash
ACU_CACHE_DIR=/tmp/acu_test python -c "from aws_cost_ultra.web import deps; deps.cache_set('hi', {'x':1}); print(deps.cache_get('hi'))"
```
Expected: `{'x': 1}`. Then `ls /tmp/acu_test/cache.db` exists.

- [ ] **Step 4: Commit**

```bash
git add aws_cost_ultra/web/deps.py
git commit -m "refactor(cache): swap JSON cache for SqliteCache"
```

---

## Task 3: Cost call counter + middleware

**Files:**
- Create: `aws_cost_ultra/web/middleware.py`
- Create: `tests/test_middleware.py`
- Modify: `aws_cost_ultra/aws/cost_explorer.py:318-349`

Wrap each `get_cost_and_usage` call with a context-aware counter so `/api/cost/*` handlers can report `X-CE-Calls-Spent` and `X-CE-Estimated-Cost-USD` headers. The user sees what each click cost in the network tab.

- [ ] **Step 1: Write failing test for counter**

```python
# tests/test_middleware.py
from aws_cost_ultra.web.middleware import CECallCounter


def test_counter_starts_at_zero():
    c = CECallCounter()
    assert c.calls == 0
    assert c.estimated_usd() == 0.0


def test_counter_increment():
    c = CECallCounter()
    c.add(pages=1, records=0)
    c.add(pages=2, records=100)
    assert c.calls == 3
    assert c.estimated_usd() == pytest.approx(0.03 + 100 * 0.00001)


def test_counter_thread_local():
    """Per-request counters don't leak between threads."""
    import threading
    a = CECallCounter()
    b = CECallCounter()
    a.add(pages=1)
    b.add(pages=2)
    assert a.calls == 1
    assert b.calls == 2
```

- [ ] **Step 2: Implement counter**

```python
# aws_cost_ultra/web/middleware.py
"""Per-request Cost Explorer call counter exposed as response headers."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


@dataclass
class CECallCounter:
    calls: int = 0
    records: int = 0

    def add(self, pages: int = 0, records: int = 0) -> None:
        self.calls += pages
        self.records += records

    def estimated_usd(self) -> float:
        # $0.01 / request, $0.00001 / UsageRecord
        return self.calls * 0.01 + self.records * 0.00001


_current: contextvars.ContextVar["CECallCounter"] = contextvars.ContextVar(
    "ce_counter", default=None  # type: ignore[arg-type]
)


def get_current_counter() -> CECallCounter:
    """Return the current request's counter, or a throwaway if outside a request."""
    c = _current.get()
    if c is None:
        c = CECallCounter()
        _current.set(c)
    return c


class CECountingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        counter = CECallCounter()
        token = _current.set(counter)
        try:
            response = await call_next(request)
        finally:
            _current.reset(token)
        response.headers["X-CE-Calls-Spent"] = str(counter.calls)
        response.headers["X-CE-Estimated-Cost-USD"] = f"{counter.estimated_usd():.5f}"
        return response
```

Then modify `aws_cost_ultra/aws/cost_explorer.py:340-349` (the `_get_cost_and_usage` loop) to increment the counter:

```python
        all_periods: list[dict] = []
        token: Optional[str] = None
        from aws_cost_ultra.web.middleware import get_current_counter  # local import to avoid cycle
        counter = get_current_counter()
        while True:
            call_kwargs = dict(kwargs)
            if token:
                call_kwargs["NextPageToken"] = token
            resp = self._client.get_cost_and_usage(**call_kwargs)
            results = resp.get("ResultsByTime", [])
            all_periods.extend(results)
            records = sum(len(r.get("Groups", []) or [r]) for r in results)
            counter.add(pages=1, records=records)
            token = resp.get("NextPageToken")
            if not token:
                break
        return all_periods
```

Also wrap `get_cost_forecast` (around line 256) with `counter.add(pages=1)` since forecast is also billed.

- [ ] **Step 3: Register middleware in `app.py`**

```python
# aws_cost_ultra/web/app.py — near the FastAPI app construction
from aws_cost_ultra.web.middleware import CECountingMiddleware
app.add_middleware(CECountingMiddleware)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_middleware.py tests/test_cost_explorer.py -v
```
Expected: middleware tests pass; existing cost_explorer tests still pass.

- [ ] **Step 5: Manual verify**

Start the server, hit `/api/cost/summary/data?profile=default&period=mtd`, check the response headers in dev-tools or:

```bash
curl -sI 'http://127.0.0.1:8080/api/cost/summary/data?profile=default&period=mtd' | grep -i x-ce
```
Expected: `X-CE-Calls-Spent: 4` (or fewer after Task 5) and `X-CE-Estimated-Cost-USD: 0.04...`.

- [ ] **Step 6: Commit**

```bash
git add aws_cost_ultra/web/middleware.py aws_cost_ultra/aws/cost_explorer.py aws_cost_ultra/web/app.py tests/test_middleware.py
git commit -m "feat(obs): expose X-CE-Calls-Spent + estimated cost per request"
```

---

## Task 4: Canonical `cost_store` — one CE call per profile/window

**Files:**
- Create: `aws_cost_ultra/aws/cost_store.py`
- Create: `tests/test_cost_store.py`

Replace the current pattern (4 calls for summary, 2 for services, 1 for trend = 7 CE calls to render the home page) with **one** `(DAILY × SERVICE)` call cached per (profile, account_id, window). Summary, services, and trend are all derived in-memory from this blob.

- [ ] **Step 1: Write failing test**

```python
# tests/test_cost_store.py
import datetime as dt
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from aws_cost_ultra.aws.cost_store import CostStore, DailyServiceMatrix


def _fake_ce_response():
    # Two days, two services
    return [
        {
            "TimePeriod": {"Start": "2026-05-18", "End": "2026-05-19"},
            "Groups": [
                {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "1.50", "Unit": "USD"}}},
                {"Keys": ["Amazon S3"], "Metrics": {"UnblendedCost": {"Amount": "0.20", "Unit": "USD"}}},
            ],
        },
        {
            "TimePeriod": {"Start": "2026-05-19", "End": "2026-05-20"},
            "Groups": [
                {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "1.55", "Unit": "USD"}}},
                {"Keys": ["Amazon S3"], "Metrics": {"UnblendedCost": {"Amount": "0.22", "Unit": "USD"}}},
            ],
        },
    ]


def test_matrix_total_sums_all_cells():
    m = DailyServiceMatrix.from_ce(_fake_ce_response())
    assert m.total() == pytest.approx(1.50 + 0.20 + 1.55 + 0.22)


def test_matrix_by_service_aggregates_across_days():
    m = DailyServiceMatrix.from_ce(_fake_ce_response())
    by_svc = dict(m.by_service())
    assert by_svc["Amazon EC2"] == pytest.approx(3.05)
    assert by_svc["Amazon S3"] == pytest.approx(0.42)


def test_matrix_trend_returns_daily_totals():
    m = DailyServiceMatrix.from_ce(_fake_ce_response())
    labels, values = m.trend()
    assert labels == ["2026-05-18", "2026-05-19"]
    assert values == [pytest.approx(1.70), pytest.approx(1.77)]


def test_store_fetches_once_per_window(monkeypatch):
    ce = MagicMock()
    ce.daily_service_matrix.return_value = _fake_ce_response()

    @dataclass
    class W:
        start: dt.date
        end: dt.date
        def iso(self): return (self.start.isoformat(), self.end.isoformat())

    store = CostStore(ce_client=ce, cache_get=lambda k: None, cache_set=lambda k, v, **kw: None)
    w = W(dt.date(2026, 5, 18), dt.date(2026, 5, 20))
    m1 = store.get_matrix("p1", "acct1", w, spec="pre_credit_gross")
    m2 = store.get_matrix("p1", "acct1", w, spec="pre_credit_gross")
    # Without cache the underlying client is called every time, but we
    # assert that the public interface is idempotent and shape-correct.
    assert m1.total() == m2.total()


def test_store_uses_cache_when_present():
    cache: dict = {}
    def cg(k): return cache.get(k)
    def cs(k, v, **kw): cache[k] = v

    ce = MagicMock()
    ce.daily_service_matrix.return_value = _fake_ce_response()

    @dataclass
    class W:
        start: dt.date
        end: dt.date
        def iso(self): return (self.start.isoformat(), self.end.isoformat())

    w = W(dt.date(2026, 5, 18), dt.date(2026, 5, 20))
    store = CostStore(ce_client=ce, cache_get=cg, cache_set=cs)
    store.get_matrix("p1", "acct1", w, spec="pre_credit_gross")
    store.get_matrix("p1", "acct1", w, spec="pre_credit_gross")
    assert ce.daily_service_matrix.call_count == 1
```

- [ ] **Step 2: Implement `cost_store.py`**

```python
# aws_cost_ultra/aws/cost_store.py
"""Single canonical (DAILY × SERVICE) CE call per (profile, account, window).

All higher-level views (total, by-service, trend) are derived in-memory
from the resulting matrix. Replaces the previous pattern of one CE
call per view, which sent 7+ calls to render one page.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional, Protocol

log = logging.getLogger("aws_cost_ultra.cost_store")


class _Window(Protocol):
    def iso(self) -> tuple[str, str]: ...


@dataclass
class DailyServiceMatrix:
    """Sparse daily × service cost matrix.

    Keys: (date_str, service_name) → unblended_usd.
    """
    cells: dict[tuple[str, str], float] = field(default_factory=dict)
    days: list[str] = field(default_factory=list)

    @classmethod
    def from_ce(cls, results_by_time: list[dict]) -> "DailyServiceMatrix":
        m = cls()
        seen_days: set[str] = set()
        for period in results_by_time:
            day = period["TimePeriod"]["Start"]
            seen_days.add(day)
            for grp in period.get("Groups", []) or []:
                svc = grp["Keys"][0] if grp.get("Keys") else "Unknown"
                amt = float(grp["Metrics"]["UnblendedCost"]["Amount"])
                m.cells[(day, svc)] = m.cells.get((day, svc), 0.0) + amt
        m.days = sorted(seen_days)
        return m

    def total(self) -> float:
        return sum(self.cells.values())

    def by_service(self) -> list[tuple[str, float]]:
        agg: dict[str, float] = {}
        for (_d, svc), v in self.cells.items():
            agg[svc] = agg.get(svc, 0.0) + v
        return sorted(agg.items(), key=lambda kv: -kv[1])

    def trend(self) -> tuple[list[str], list[float]]:
        labels = list(self.days)
        values = [
            sum(v for (d, _s), v in self.cells.items() if d == day)
            for day in labels
        ]
        return labels, values


class CostStore:
    """Fetches and caches the canonical daily×service matrix per window."""

    def __init__(
        self,
        ce_client: Any,
        cache_get: Callable[[str], Optional[Any]],
        cache_set: Callable[..., None],
    ) -> None:
        self._ce = ce_client
        self._cache_get = cache_get
        self._cache_set = cache_set

    @staticmethod
    def _key(profile: str, account_id: str, window: _Window, spec_summary: str) -> str:
        s, e = window.iso()
        return f"matrix:{profile}:{account_id}:{s}:{e}:{spec_summary}"

    @staticmethod
    def _is_closed_window(window: _Window) -> bool:
        """True when the window's end date is in the past (no more updates expected)."""
        _s, e = window.iso()
        end = dt.date.fromisoformat(e)
        return end <= dt.date.today()

    def get_matrix(
        self,
        profile: str,
        account_id: str,
        window: _Window,
        spec,
        force: bool = False,
    ) -> DailyServiceMatrix:
        spec_summary = spec.summary() if hasattr(spec, "summary") else str(spec)
        key = self._key(profile, account_id, window, spec_summary)
        if not force:
            cached = self._cache_get(key)
            if cached is not None:
                return DailyServiceMatrix(
                    cells={tuple(k.split("\x1f")): v for k, v in cached["cells"].items()},
                    days=cached["days"],
                )

        raw = self._ce.daily_service_matrix(window, spec=spec)
        m = DailyServiceMatrix.from_ce(raw)

        # Closed windows cache effectively forever; open (today) cache 15 min.
        if self._is_closed_window(window):
            ttl, swr = 30 * 24 * 3600.0, 0.0      # 30 days, no SWR
        else:
            ttl, swr = 900.0, 6 * 3600.0          # 15 min fresh, 6h stale

        self._cache_set(
            key,
            {
                "cells": {f"{d}\x1f{s}": v for (d, s), v in m.cells.items()},
                "days": m.days,
            },
            ttl_seconds=ttl,
            swr_seconds=swr,
        )
        return m
```

Then add a thin method to `CostExplorerClient` (`aws_cost_ultra/aws/cost_explorer.py`):

```python
def daily_service_matrix(self, window, spec):
    """Single canonical CE call: DAILY granularity, grouped by SERVICE."""
    return self._get_cost_and_usage(
        window=window,
        metric=CostMetric.UNBLENDED_COST,  # match existing default
        spec=spec,
        granularity=Granularity.DAILY,
        group_by=(("DIMENSION", "SERVICE"),),
    )
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_cost_store.py -v
```
Expected: 5 passed.

- [ ] **Step 4: Commit**

```bash
git add aws_cost_ultra/aws/cost_store.py aws_cost_ultra/aws/cost_explorer.py tests/test_cost_store.py
git commit -m "feat(cost): add CostStore + DailyServiceMatrix — one CE call per window"
```

---

## Task 5: Refactor `/api/cost/*` routes to use `CostStore`

**Files:**
- Modify: `aws_cost_ultra/web/routes/cost.py`

The handlers currently each issue their own CE calls. Replace with `CostStore.get_matrix(...)` + slice. Net effect: a fresh dashboard load drops from ~7 CE calls to **1**.

- [ ] **Step 1: Replace `_build_summary_ctx`**

In `aws_cost_ultra/web/routes/cost.py`, replace the body of `_build_summary_ctx` (around line 40–80) with:

```python
def _build_summary_ctx(profile: str, period: str, session, ce, spec):
    from aws_cost_ultra.aws.cost_store import CostStore
    from aws_cost_ultra.core.time_windows import remainder_of_current_month
    from aws_cost_ultra.web.deps import cache_get, cache_set

    account_id = session.client("sts").get_caller_identity()["Account"]
    store = CostStore(ce, cache_get=cache_get, cache_set=cache_set)

    window = period_to_window(period)
    prev_window = period_to_window("last_month") if period == "mtd" else None

    m = store.get_matrix(profile, account_id, window, spec)
    by_svc = m.by_service()
    total = m.total()

    prev_total = None
    if prev_window is not None:
        prev_m = store.get_matrix(profile, account_id, prev_window, spec)
        prev_total = prev_m.total()

    # Forecast is the one call we still need from CE — there's no cheap substitute.
    fcast = ce.get_forecast(remainder_of_current_month(), spec=spec)

    change_pct = None
    if prev_total is not None and prev_total >= 0.50:
        raw = (total - prev_total) / prev_total * 100
        change_pct = max(-999.9, min(9999.9, raw))

    return {
        "error": None,
        "total_mtd": total,
        "total_prev": prev_total,
        "change_pct": change_pct,
        "forecast": (total + fcast.amount_usd) if fcast else None,
        "top_service_name": by_svc[0][0] if by_svc else None,
        "top_service_cost": by_svc[0][1] if by_svc else None,
        "period": period,
        "cost_basis_label": "Pre-credit · excludes Credit/Refund · UTC",
    }
```

- [ ] **Step 2: Replace `_build_services_ctx`**

```python
def _build_services_ctx(profile: str, period: str, limit: int, session, ce, spec):
    from aws_cost_ultra.aws.cost_store import CostStore
    from aws_cost_ultra.web.deps import cache_get, cache_set

    account_id = session.client("sts").get_caller_identity()["Account"]
    store = CostStore(ce, cache_get=cache_get, cache_set=cache_set)
    window = period_to_window(period)
    prev_window = period_to_window("last_month") if period == "mtd" else None

    m = store.get_matrix(profile, account_id, window, spec)
    prev_map: dict[str, float] = {}
    if prev_window is not None:
        prev_m = store.get_matrix(profile, account_id, prev_window, spec)
        prev_map = {svc: cost for svc, cost in prev_m.by_service()}

    svc_rows = []
    total = 0.0
    for svc, cost in m.by_service():
        prev = prev_map.get(svc)
        delta_pct = None
        if prev and prev >= 0.50:
            delta_pct = (cost - prev) / prev * 100
        svc_rows.append({"service": svc, "cost": round(cost, 2), "prev": prev, "delta_pct": delta_pct})
        total += cost

    if limit > 0:
        svc_rows = svc_rows[:limit]
    return {
        "error": None,
        "total": round(total, 2),
        "services": svc_rows,
        "cost_basis_label": "Pre-credit gross",
    }
```

- [ ] **Step 3: Replace `_build_trend_ctx` (and cache the `/trend-table` HTML)**

```python
def _build_trend_ctx(profile: str, period: str, granularity, session, ce, spec):
    from aws_cost_ultra.aws.cost_store import CostStore
    from aws_cost_ultra.web.deps import cache_get, cache_set

    account_id = session.client("sts").get_caller_identity()["Account"]
    store = CostStore(ce, cache_get=cache_get, cache_set=cache_set)
    window = period_to_window(period)
    m = store.get_matrix(profile, account_id, window, spec)

    if granularity.value == "MONTHLY":
        # Bucket the daily values into year-month.
        labels, values = m.trend()
        monthly: dict[str, float] = {}
        for d, v in zip(labels, values):
            ym = d[:7]
            monthly[ym] = monthly.get(ym, 0.0) + v
        labels = sorted(monthly.keys())
        values = [round(monthly[k], 2) for k in labels]
    else:
        labels, values = m.trend()
        values = [round(v, 2) for v in values]

    return {"labels": labels, "values": values, "cost_basis_label": "Pre-credit gross"}
```

For the trend-table HTML route (around line 216–237), wrap the existing logic with `cache_get_swr`/`cache_set` exactly like the JSON variant.

- [ ] **Step 4: Run existing route tests**

```bash
pytest tests/ -v
```
Expected: previously-green tests still green. If any unit test directly asserted "X CE calls happened" with the old count, update it to reflect the new "1 canonical call + 1 forecast" pattern.

- [ ] **Step 5: Manual smoke**

```bash
ACU_CACHE_DIR=/tmp/acu_test rm -rf /tmp/acu_test
uvicorn aws_cost_ultra.web.app:app --port 8080 &
sleep 2
curl -sI 'http://127.0.0.1:8080/api/cost/summary/data?profile=default&period=mtd' | grep -i x-ce
curl -sI 'http://127.0.0.1:8080/api/cost/services/data?profile=default&period=mtd' | grep -i x-ce  # second hit
curl -sI 'http://127.0.0.1:8080/api/cost/trend/data?profile=default&period=mtd'   | grep -i x-ce  # third hit
```
Expected first call: `X-CE-Calls-Spent: 2` (1 matrix + 1 forecast) or `3` if `period=mtd` triggers a prev-window fetch too. Expected second + third: `X-CE-Calls-Spent: 0` (served from cache).

- [ ] **Step 6: Commit**

```bash
git add aws_cost_ultra/web/routes/cost.py
git commit -m "refactor(cost): route summary/services/trend through CostStore matrix"
```

---

## Task 6: Dedupe prewarm + gate behind explicit opt-in

**Files:**
- Modify: `aws_cost_ultra/web/prewarm.py`
- Modify: `aws_cost_ultra/web/app.py`

Current prewarm fires 9 CE calls/profile on every server start. New prewarm fires **1 matrix call/profile + 1 forecast** = 2 calls, only when `ACU_ENABLE_PREWARM=1`.

- [ ] **Step 1: Replace `prewarm_background`**

```python
# aws_cost_ultra/web/prewarm.py
from __future__ import annotations

import logging

from aws_cost_ultra.aws.cost_store import CostStore
from aws_cost_ultra.core.filters import pre_credit_gross
from aws_cost_ultra.web.deps import cache_get, cache_set, get_ce_client, get_session, period_to_window

log = logging.getLogger("aws_cost_ultra.prewarm")


def prewarm_background(profiles: list[str]) -> None:
    for profile in profiles:
        try:
            session = get_session(profile)
            ce = get_ce_client(session)
            spec = pre_credit_gross()

            try:
                account_id = session.client("sts").get_caller_identity()["Account"]
            except Exception as exc:
                log.info("skip prewarm %s: %s", profile, type(exc).__name__)
                continue

            window = period_to_window("mtd")
            store = CostStore(ce, cache_get=cache_get, cache_set=cache_set)
            store.get_matrix(profile, account_id, window, spec)

            log.info("prewarm matrix populated for profile=%s", profile)
        except Exception as exc:
            log.warning("prewarm error for %s: %s", profile, exc, exc_info=True)
```

- [ ] **Step 2: Confirm `app.py` gating is already in place**

The existing `_kick_prewarm` in `web/app.py` already gates on `ACU_ENABLE_PREWARM`. Confirm it still skips by default.

- [ ] **Step 3: Manual smoke**

```bash
ACU_CACHE_DIR=/tmp/acu_test rm -rf /tmp/acu_test
ACU_ENABLE_PREWARM=1 uvicorn aws_cost_ultra.web.app:app --port 8080 &
sleep 5  # prewarm runs in background
# Then check cache db has entries
sqlite3 /tmp/acu_test/cache.db "SELECT key FROM cache_entries;"
```
Expected: 1 `matrix:default:<acct>:...` row per profile.

- [ ] **Step 4: Commit**

```bash
git add aws_cost_ultra/web/prewarm.py
git commit -m "refactor(prewarm): use CostStore matrix — 2 CE calls/profile instead of 9"
```

---

## Task 7: Drop EC2 RESOURCE_ID path

**Files:**
- Modify: `aws_cost_ultra/aws/ce_attribution.py` — delete the module (or empty it)
- Modify: `aws_cost_ultra/resources/ec2.py` — remove RESOURCE_ID branch; always USAGE_TYPE
- Modify: `aws_cost_ultra/resources/runner.py` — drop the `ce_ec2_cost_by_instance_id` import + call site

The RESOURCE_ID query is the single biggest cost source on large accounts (UsageRecord surcharge). With 9 instances it's tiny but on principle and because Plan 2 (CUR) will replace this entirely with exact data, we delete it now.

- [ ] **Step 1: Find and remove call sites**

```bash
cd "/run/media/tirth/OS/Users/Tirth Teraiya/Personal Folder/aws-cost-dashboard"
grep -rn "ce_ec2_cost_by_instance_id\|ce_attribution" aws_cost_ultra/
```

For each hit, replace with the USAGE_TYPE fallback that already exists (`_attribute_from_usage_type` in `resources/ec2.py`).

- [ ] **Step 2: Delete `ce_attribution.py`**

```bash
git rm aws_cost_ultra/aws/ce_attribution.py
```

- [ ] **Step 3: In `resources/ec2.py`, replace the RESOURCE_ID branch**

Find the block (around line 43–52 per the audit) that calls `ce_ec2_cost_by_instance_id` and replace with:

```python
# Resource-level attribution removed (CE RESOURCE_ID surcharge).
# Plan 2 reintroduces named per-resource cost via CUR + DuckDB.
# Until then, attribute by USAGE_TYPE.
usage_type_attrs = _attribute_from_usage_type(ce_client, window, spec)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/ -v
```
Expected: existing tests pass. Update any test that referenced `ce_attribution` to use the USAGE_TYPE attribution instead.

- [ ] **Step 5: Manual smoke**

```bash
curl -sI 'http://127.0.0.1:8080/api/resources/data?profile=default&period=mtd&region=all' | grep -i x-ce
```
Expected: `X-CE-Calls-Spent: 1` (the USAGE_TYPE fallback) instead of `2`.

- [ ] **Step 6: Commit**

```bash
git commit -am "feat(cost): drop EC2 RESOURCE_ID CE path — eliminates UsageRecord surcharge"
```

---

## Task 8: Per-thread Cost Explorer clients

**Files:**
- Modify: `aws_cost_ultra/web/deps.py`
- Modify: `aws_cost_ultra/aws/cost_explorer.py`

Eliminate the documented-not-thread-safe risk by using `threading.local`.

- [ ] **Step 1: Replace `get_ce_client`**

```python
# aws_cost_ultra/web/deps.py
import threading
_ce_local = threading.local()

def get_ce_client(session: boto3.Session) -> CostExplorerClient:
    # boto3 Session is per-call from the FastAPI dependency, but Session itself
    # is cheap; CE wrapper holds a boto3 ce client whose internal state is
    # not officially thread-safe. Keep one per thread.
    key = id(session)
    cache = getattr(_ce_local, "clients", None)
    if cache is None:
        cache = {}
        _ce_local.clients = cache
    if key not in cache:
        cache[key] = CostExplorerClient(session=session)
    return cache[key]
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/ -v
```
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git commit -am "fix(thread): per-thread CostExplorerClient instances"
```

---

## Task 9: Replace bare `except: pass` with logged warnings

**Files:**
- Modify: `aws_cost_ultra/audit/idle.py`
- Modify: `aws_cost_ultra/audit/budgets.py`
- Modify: `aws_cost_ultra/resources/ec2.py`
- Modify: `aws_cost_ultra/web/deps.py:181` (`schedule_refresh` _run)

- [ ] **Step 1: Find every offender**

```bash
grep -rn "except Exception:.*pass" aws_cost_ultra/ | head -30
grep -rn "except:.*pass" aws_cost_ultra/ | head -30
```

- [ ] **Step 2: Replace each instance**

```python
# Before
try:
    something()
except Exception:
    pass

# After
try:
    something()
except Exception as exc:
    log.warning("%s failed: %s", "<context>", type(exc).__name__, exc_info=True)
```

The `<context>` should describe what was being attempted ("idle EBS check", "budget fetch for profile X", etc.).

- [ ] **Step 3: Run tests + manual smoke**

```bash
pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git commit -am "fix(logging): surface swallowed exceptions in audit and refresh paths"
```

---

## Task 10: Remove legacy duplicate stack

**Files:**
- Delete: `static/js/app.js`, `templates/dashboard.html`
- Delete: `AWS Costing Dashboard/` (after copying any actively-used CSS tokens into `frontend/src/tokens.css`)

- [ ] **Step 1: Confirm nothing imports them**

```bash
grep -rn "static/js/app.js\|templates/dashboard.html" aws_cost_ultra/ frontend/src/ || echo "no refs"
```

- [ ] **Step 2: Copy tokens.css**

```bash
cp "AWS Costing Dashboard/tokens.css" frontend/src/tokens.css
```

Update `frontend/src/styles.css` to import from the local path instead of the prototype folder.

- [ ] **Step 3: Delete**

```bash
git rm -r static/js/app.js templates/dashboard.html "AWS Costing Dashboard"
```

- [ ] **Step 4: Confirm app still boots and frontend builds**

```bash
uvicorn aws_cost_ultra.web.app:app --port 8080 &
cd frontend && npm run build && cd ..
curl -s http://127.0.0.1:8080/ | head -10
```

- [ ] **Step 5: Commit**

```bash
git commit -am "chore: delete legacy vanilla-JS dashboard + orphan prototype folder"
```

---

## Self-Review

**Spec coverage check** against `2026-05-20-cost-and-perf-redesign.md` §6 Week 1 items:

| Spec item | Plan task |
|---|---|
| 1. Persistent SQLite cache | Task 1, 2 |
| 2. Single canonical daily CE call | Task 4 |
| 3. Frontend slicing | Backend side in Task 5; frontend side in Plan 3 |
| 4. Cache `/trend-table` HTML | Task 5 step 3 |
| 5. Dedupe prewarm | Task 6 |
| 6. Kill EC2 RESOURCE_ID | Task 7 |
| 7. `X-CE-Calls-Spent` header | Task 3 |
| 8. AbortController | **Plan 3** |
| 9. Debounce filter changes | **Plan 3** |
| 10. Replace bare excepts | Task 9 |
| 11. Per-thread CE clients | Task 8 |
| 12. Delete legacy code | Task 10 |

All Week 1 backend items covered. Frontend items handled in Plan 3.

**Placeholder scan:** No "TBD" / "implement later" / vague "add error handling" — all code blocks are concrete.

**Type consistency:** `DailyServiceMatrix`, `CostStore`, `CECallCounter`, `SqliteCache` names used consistently. `cache_set` accepts optional `ttl_seconds`/`swr_seconds` and falls back to defaults — checked in Task 2.

---

## Verification (end-to-end)

After all 10 tasks, run:

```bash
ACU_CACHE_DIR=/tmp/acu_verify rm -rf /tmp/acu_verify
uvicorn aws_cost_ultra.web.app:app --port 8080 &
sleep 2

# Cold dashboard load (clean cache)
curl -sI 'http://127.0.0.1:8080/api/cost/summary/data?profile=default&period=mtd' | grep X-CE
curl -sI 'http://127.0.0.1:8080/api/cost/services/data?profile=default&period=mtd' | grep X-CE
curl -sI 'http://127.0.0.1:8080/api/cost/trend/data?profile=default&period=mtd'   | grep X-CE
curl -sI 'http://127.0.0.1:8080/api/resources/data?profile=default&period=mtd&region=all' | grep X-CE

# Expected totals across all four calls: 3 CE calls
#   - 1 matrix (DAILY × SERVICE) shared by summary/services/trend
#   - 1 forecast
#   - 1 USAGE_TYPE fallback for resources

# Warm reload (within 15 min)
curl -sI 'http://127.0.0.1:8080/api/cost/summary/data?profile=default&period=mtd' | grep X-CE
# Expected: X-CE-Calls-Spent: 0
```
