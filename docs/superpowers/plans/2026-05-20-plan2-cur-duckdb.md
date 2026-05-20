# Plan 2 — CUR + DuckDB Warehouse for Named Per-Resource Cost

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace billed Cost Explorer queries with a local DuckDB warehouse fed by AWS Cost and Usage Reports (CUR 2.0). The Resources page finally shows named per-resource cost — "this specific bucket cost $4.20" — at $0 marginal CE spend.

**Architecture:** Terraform module creates an S3 bucket + CUR 2.0 report definition (daily Parquet, hourly granularity, resource-IDs + tags enabled). A Python ingestor lists new S3 partitions and loads them into `~/.cache/aws_cost_ultra/cur.duckdb`. A `CurStore` exposes the same shape as `CostStore` (`get_matrix`, `total`, `by_service`, `attribute_resources`). A `CostSource` strategy prefers `CurStore` and falls back to `CostStore` (CE) only when CUR has no data for the requested window.

**Tech Stack:** Python 3.10+, DuckDB 1.x (via `duckdb` pip package), boto3 S3, Terraform 1.5+.

**Prerequisites:** Plan 1 complete (depends on `CostStore`, `SqliteCache`, `X-CE-Calls-Spent` middleware).

---

## Files affected

**Create:**
- `iac/cur/main.tf` — Terraform: S3 bucket, IAM, CUR report definition
- `iac/cur/variables.tf`, `iac/cur/outputs.tf`
- `iac/cur/README.md` — how to apply it
- `aws_cost_ultra/cur/__init__.py`
- `aws_cost_ultra/cur/ingestor.py` — downloads new CUR Parquet partitions into DuckDB
- `aws_cost_ultra/cur/store.py` — `CurStore` query layer
- `aws_cost_ultra/cur/schema.py` — DuckDB DDL for the line-items table
- `aws_cost_ultra/cur/setup.py` — `aws-cost-ultra cur setup` CLI helper
- `aws_cost_ultra/aws/cost_source.py` — `CostSource` strategy (CUR first, CE fallback)
- `tests/test_cur_ingestor.py`
- `tests/test_cur_store.py`
- `tests/test_cost_source.py`
- `tests/fixtures/cur_sample.parquet` — tiny generated fixture for tests

**Modify:**
- `pyproject.toml` — add `duckdb>=1.0`, `pyarrow>=15.0`
- `requirements.txt` — same
- `aws_cost_ultra/cli/__init__.py` (or wherever CLI sits) — add `cur` subcommand
- `aws_cost_ultra/web/routes/cost.py` — use `CostSource` instead of `CostStore` directly
- `aws_cost_ultra/web/routes/resources_api.py` — use `CostSource.attribute_resources()` to populate the Resources page with named CUR rows when available
- `aws_cost_ultra/resources/runner.py` — gated: if CUR is configured and current, skip the describe-and-attribute path; otherwise keep it as the 24h cold-start fallback

---

## Task 1: Add DuckDB + pyarrow dependencies

**Files:** `pyproject.toml`, `requirements.txt`

- [ ] **Step 1: Add deps**

In `pyproject.toml`:
```toml
dependencies = [
    "boto3>=1.34",
    "botocore>=1.34",
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
    "duckdb>=1.0",
    "pyarrow>=15.0",
]
```

In `requirements.txt`:
```
boto3>=1.34
botocore>=1.34
fastapi>=0.110
uvicorn[standard]>=0.29
jinja2>=3.1
python-multipart>=0.0.9
duckdb>=1.0
pyarrow>=15.0
pytest>=8.0
```

- [ ] **Step 2: Install + sanity test**

```bash
pip install -e .
python -c "import duckdb; con = duckdb.connect(':memory:'); print(con.execute('SELECT 42').fetchone())"
```
Expected: `(42,)`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml requirements.txt
git commit -m "deps: add duckdb + pyarrow for CUR warehouse"
```

---

## Task 2: DuckDB schema + connection helper

**Files:**
- Create: `aws_cost_ultra/cur/schema.py`
- Create: `aws_cost_ultra/cur/__init__.py`

CUR 2.0 has ~250 columns; we materialize only the ones we query. Schema below covers per-resource cost, tags, time, service, usage.

- [ ] **Step 1: Write `schema.py`**

```python
# aws_cost_ultra/cur/schema.py
"""DuckDB schema for the local CUR warehouse.

We keep the wide CUR Parquet as an external table and project a
narrow `line_items` view that the rest of the app queries. New CUR
columns can be added without breaking existing queries.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

CUR_GLOB_PATH_KEY = "cur_parquet_glob"
MANIFEST_TABLE = "cur_manifests"
LINE_ITEMS_VIEW = "line_items"


SCHEMA_SQL = """
-- Manifest of CUR partitions we've ingested. Idempotent ingestion key.
CREATE TABLE IF NOT EXISTS cur_manifests (
  billing_period   TEXT NOT NULL,   -- e.g. "2026-05"
  assembly_id      TEXT NOT NULL,   -- AWS CUR assembly id
  s3_key           TEXT NOT NULL,
  ingested_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (billing_period, assembly_id, s3_key)
);

-- Where the Parquet partitions live on local disk after sync.
CREATE TABLE IF NOT EXISTS cur_config (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);
"""


def connect(db_path: Path) -> duckdb.DuckDBPyConnection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute(SCHEMA_SQL)
    return con


def set_parquet_glob(con: duckdb.DuckDBPyConnection, glob_path: str) -> None:
    con.execute(
        "INSERT INTO cur_config(k, v) VALUES (?, ?) "
        "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
        [CUR_GLOB_PATH_KEY, glob_path],
    )


def get_parquet_glob(con: duckdb.DuckDBPyConnection) -> str | None:
    row = con.execute("SELECT v FROM cur_config WHERE k=?", [CUR_GLOB_PATH_KEY]).fetchone()
    return row[0] if row else None


def ensure_line_items_view(con: duckdb.DuckDBPyConnection) -> None:
    """Project a stable narrow view over the wide CUR Parquet."""
    glob = get_parquet_glob(con)
    if not glob:
        return
    con.execute(f"""
        CREATE OR REPLACE VIEW {LINE_ITEMS_VIEW} AS
        SELECT
          CAST(bill_billing_period_start_date AS DATE) AS billing_period_start,
          CAST(line_item_usage_start_date     AS DATE) AS usage_date,
          line_item_usage_account_id          AS account_id,
          line_item_product_code              AS service_code,
          product['product_name']             AS service_name,
          line_item_usage_type                AS usage_type,
          line_item_operation                 AS operation,
          line_item_resource_id               AS resource_id,
          resource_tags                       AS tags,
          line_item_usage_amount              AS usage_amount,
          line_item_unblended_cost            AS unblended_cost,
          line_item_blended_cost              AS blended_cost,
          line_item_currency_code             AS currency
        FROM read_parquet('{glob}', union_by_name=true)
    """)
```

> Note: CUR 2.0 column names assume the **CUR 2.0 / Data Exports FOCUS** flavor (with `bill_billing_period_start_date`, `line_item_*`, nested `product` and `resource_tags`). Legacy CUR uses slightly different names — the `union_by_name=true` lets DuckDB tolerate column drift across months. If we end up on legacy CUR, adjust `line_item_unblended_cost` → `lineItem/UnblendedCost`, etc.

- [ ] **Step 2: Commit**

```bash
git add aws_cost_ultra/cur/__init__.py aws_cost_ultra/cur/schema.py
git commit -m "feat(cur): DuckDB schema + parquet glob view"
```

---

## Task 3: CUR ingestor — list S3, download new partitions

**Files:**
- Create: `aws_cost_ultra/cur/ingestor.py`
- Create: `tests/test_cur_ingestor.py`

The ingestor's job: list the CUR S3 prefix, identify partitions newer than what's in `cur_manifests`, download them to a local `parquet/` directory, register them with DuckDB via `ensure_line_items_view`.

CUR 2.0 layout (Parquet flavor):
```
s3://<bucket>/<prefix>/data/BILLING_PERIOD=2026-05/<assembly_id>/<file>.snappy.parquet
```

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cur_ingestor.py
from pathlib import Path
from unittest.mock import MagicMock

import duckdb
import pytest

from aws_cost_ultra.cur.ingestor import CurIngestor


@pytest.fixture
def db(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    from aws_cost_ultra.cur.schema import connect
    return connect(tmp_path / "cur.duckdb")


def test_ingestor_skips_known_partitions(tmp_path: Path, db):
    s3 = MagicMock()
    s3.list_objects_v2.return_value = {"Contents": [
        {"Key": "prefix/data/BILLING_PERIOD=2026-05/AABBCC/part-0.snappy.parquet", "Size": 1234},
    ]}
    s3.download_file = MagicMock()

    ing = CurIngestor(s3_client=s3, bucket="b", prefix="prefix/data/", local_dir=tmp_path / "parquet", db=db)
    n = ing.ingest()
    assert n == 1
    s3.download_file.assert_called_once()

    # Second call: already-known partition is skipped
    s3.download_file.reset_mock()
    n2 = ing.ingest()
    assert n2 == 0
    s3.download_file.assert_not_called()


def test_ingestor_handles_empty_bucket(tmp_path: Path, db):
    s3 = MagicMock()
    s3.list_objects_v2.return_value = {}
    ing = CurIngestor(s3_client=s3, bucket="b", prefix="p/", local_dir=tmp_path, db=db)
    assert ing.ingest() == 0


def test_ingestor_extracts_billing_period_and_assembly_from_key():
    from aws_cost_ultra.cur.ingestor import parse_partition_key
    bp, asm = parse_partition_key("acu-cur/data/BILLING_PERIOD=2026-05/abc-def/part-0.snappy.parquet")
    assert bp == "2026-05"
    assert asm == "abc-def"
```

- [ ] **Step 2: Implement `ingestor.py`**

```python
# aws_cost_ultra/cur/ingestor.py
"""Pull new CUR Parquet partitions from S3 into the local DuckDB warehouse."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Iterable

import duckdb

from aws_cost_ultra.cur.schema import ensure_line_items_view, set_parquet_glob

log = logging.getLogger("aws_cost_ultra.cur.ingestor")

# CUR 2.0 path: <prefix>/data/BILLING_PERIOD=<YYYY-MM>/<assembly_id>/<file>.parquet
_PARTITION_RE = re.compile(r"BILLING_PERIOD=(?P<bp>\d{4}-\d{2})/(?P<asm>[^/]+)/[^/]+\.parquet$")


def parse_partition_key(s3_key: str) -> tuple[str, str] | None:
    m = _PARTITION_RE.search(s3_key)
    if not m:
        return None
    return m.group("bp"), m.group("asm")


class CurIngestor:
    def __init__(
        self,
        s3_client: Any,
        bucket: str,
        prefix: str,
        local_dir: Path,
        db: duckdb.DuckDBPyConnection,
    ) -> None:
        self._s3 = s3_client
        self._bucket = bucket
        self._prefix = prefix.rstrip("/") + "/"
        self._local = Path(local_dir)
        self._db = db
        self._local.mkdir(parents=True, exist_ok=True)

    def _known_keys(self) -> set[str]:
        return {r[0] for r in self._db.execute("SELECT s3_key FROM cur_manifests").fetchall()}

    def _list_partitions(self) -> Iterable[dict]:
        token = None
        while True:
            kwargs = {"Bucket": self._bucket, "Prefix": self._prefix}
            if token:
                kwargs["ContinuationToken"] = token
            resp = self._s3.list_objects_v2(**kwargs)
            for obj in resp.get("Contents", []) or []:
                if obj["Key"].endswith(".parquet"):
                    yield obj
            token = resp.get("NextContinuationToken")
            if not token:
                break

    def ingest(self) -> int:
        known = self._known_keys()
        n_new = 0
        for obj in self._list_partitions():
            key = obj["Key"]
            if key in known:
                continue
            parsed = parse_partition_key(key)
            if parsed is None:
                log.warning("skipping unrecognized CUR key: %s", key)
                continue
            bp, asm = parsed
            local_path = self._local / bp / asm / Path(key).name
            local_path.parent.mkdir(parents=True, exist_ok=True)
            log.info("downloading %s → %s", key, local_path)
            self._s3.download_file(self._bucket, key, str(local_path))
            self._db.execute(
                "INSERT OR IGNORE INTO cur_manifests(billing_period, assembly_id, s3_key) VALUES (?, ?, ?)",
                [bp, asm, key],
            )
            n_new += 1

        # Re-register the parquet glob so DuckDB sees the new files.
        glob = str(self._local / "*" / "*" / "*.parquet")
        set_parquet_glob(self._db, glob)
        ensure_line_items_view(self._db)

        log.info("CUR ingest complete: %d new partitions", n_new)
        return n_new
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_cur_ingestor.py -v
```
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add aws_cost_ultra/cur/ingestor.py tests/test_cur_ingestor.py
git commit -m "feat(cur): S3 → DuckDB ingestor with idempotent manifest tracking"
```

---

## Task 4: `CurStore` — query layer mirroring `CostStore`

**Files:**
- Create: `aws_cost_ultra/cur/store.py`
- Create: `tests/test_cur_store.py`
- Create: `tests/fixtures/cur_sample.parquet` (generated, see step below)

`CurStore` exposes the same shape as `CostStore` (`get_matrix`, `attribute_resources`) so the routes don't care which one they call.

- [ ] **Step 1: Generate the fixture**

```python
# tests/conftest.py — add to existing file or create
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
import pytest


@pytest.fixture(scope="session")
def cur_sample_parquet(tmp_path_factory):
    rows = [
        # date, account, service_code, service_name, resource_id, tags, usage_type, op, usage, unblended
        ("2026-05-18", "012178638401", "AmazonEC2", "Amazon Elastic Compute Cloud",
         "i-aaa1", {"Name": "web-1", "Project": "influenzer"}, "BoxUsage:t4g.small", "RunInstances", 24.0, 1.50),
        ("2026-05-19", "012178638401", "AmazonEC2", "Amazon Elastic Compute Cloud",
         "i-aaa1", {"Name": "web-1", "Project": "influenzer"}, "BoxUsage:t4g.small", "RunInstances", 24.0, 1.55),
        ("2026-05-18", "012178638401", "AmazonS3", "Amazon Simple Storage Service",
         "my-app-assets", {"Name": "my-app-assets"}, "TimedStorage-ByteHrs", "StandardStorage", 1024.0, 0.20),
        ("2026-05-19", "012178638401", "AmazonS3", "Amazon Simple Storage Service",
         "my-app-assets", {"Name": "my-app-assets"}, "TimedStorage-ByteHrs", "StandardStorage", 1024.0, 0.22),
    ]
    columns = {
        "bill_billing_period_start_date": [r[0][:7] + "-01" for r in rows],
        "line_item_usage_start_date":     [r[0] for r in rows],
        "line_item_usage_account_id":     [r[1] for r in rows],
        "line_item_product_code":         [r[2] for r in rows],
        "product":                        [{"product_name": r[3]} for r in rows],
        "line_item_resource_id":          [r[4] for r in rows],
        "resource_tags":                  [r[5] for r in rows],
        "line_item_usage_type":           [r[6] for r in rows],
        "line_item_operation":            [r[7] for r in rows],
        "line_item_usage_amount":         [r[8] for r in rows],
        "line_item_unblended_cost":       [r[9] for r in rows],
        "line_item_blended_cost":         [r[9] for r in rows],
        "line_item_currency_code":        ["USD"] * len(rows),
    }
    table = pa.table(columns)
    out_dir = tmp_path_factory.mktemp("cur") / "2026-05" / "abc-asm"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "part-0.snappy.parquet"
    pq.write_table(table, out_path, compression="snappy")
    return out_path.parent.parent  # billing period root
```

- [ ] **Step 2: Write tests**

```python
# tests/test_cur_store.py
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pytest

from aws_cost_ultra.cur.schema import connect, set_parquet_glob, ensure_line_items_view
from aws_cost_ultra.cur.store import CurStore


@dataclass
class W:
    start: dt.date
    end: dt.date
    def iso(self): return (self.start.isoformat(), self.end.isoformat())


@pytest.fixture
def db_with_data(tmp_path: Path, cur_sample_parquet: Path) -> duckdb.DuckDBPyConnection:
    db = connect(tmp_path / "cur.duckdb")
    glob = str(cur_sample_parquet / "*" / "*.parquet")
    set_parquet_glob(db, glob)
    ensure_line_items_view(db)
    return db


def test_total_for_window(db_with_data):
    s = CurStore(db_with_data)
    w = W(dt.date(2026, 5, 18), dt.date(2026, 5, 20))
    assert s.total("012178638401", w) == pytest.approx(1.50 + 1.55 + 0.20 + 0.22)


def test_by_service(db_with_data):
    s = CurStore(db_with_data)
    w = W(dt.date(2026, 5, 18), dt.date(2026, 5, 20))
    out = dict(s.by_service("012178638401", w))
    assert out["Amazon Elastic Compute Cloud"] == pytest.approx(3.05)
    assert out["Amazon Simple Storage Service"] == pytest.approx(0.42)


def test_attribute_resources_returns_named_rows(db_with_data):
    s = CurStore(db_with_data)
    w = W(dt.date(2026, 5, 18), dt.date(2026, 5, 20))
    rows = s.attribute_resources("012178638401", w)
    by_id = {r["resource_id"]: r for r in rows}
    assert by_id["i-aaa1"]["name"] == "web-1"
    assert by_id["i-aaa1"]["cost"] == pytest.approx(3.05)
    assert by_id["my-app-assets"]["name"] == "my-app-assets"
    assert by_id["my-app-assets"]["cost"] == pytest.approx(0.42)


def test_has_data_for_window(db_with_data):
    s = CurStore(db_with_data)
    have = W(dt.date(2026, 5, 18), dt.date(2026, 5, 20))
    nope = W(dt.date(2024, 1, 1), dt.date(2024, 1, 10))
    assert s.has_data("012178638401", have) is True
    assert s.has_data("012178638401", nope) is False
```

- [ ] **Step 3: Implement `CurStore`**

```python
# aws_cost_ultra/cur/store.py
"""SQL query layer over the local DuckDB CUR warehouse."""

from __future__ import annotations

import datetime as dt
from typing import Any, Protocol

import duckdb

from aws_cost_ultra.cur.schema import LINE_ITEMS_VIEW


class _Window(Protocol):
    def iso(self) -> tuple[str, str]: ...


class CurStore:
    def __init__(self, db: duckdb.DuckDBPyConnection) -> None:
        self._db = db

    def _has_view(self) -> bool:
        row = self._db.execute(
            "SELECT count(*) FROM duckdb_views WHERE view_name = ?",
            [LINE_ITEMS_VIEW],
        ).fetchone()
        return bool(row and row[0])

    def has_data(self, account_id: str, window: _Window) -> bool:
        if not self._has_view():
            return False
        s, e = window.iso()
        row = self._db.execute(
            f"SELECT count(*) FROM {LINE_ITEMS_VIEW} "
            "WHERE account_id = ? AND usage_date >= ? AND usage_date < ?",
            [account_id, s, e],
        ).fetchone()
        return bool(row and row[0] > 0)

    def total(self, account_id: str, window: _Window) -> float:
        s, e = window.iso()
        row = self._db.execute(
            f"SELECT COALESCE(SUM(unblended_cost), 0) FROM {LINE_ITEMS_VIEW} "
            "WHERE account_id = ? AND usage_date >= ? AND usage_date < ?",
            [account_id, s, e],
        ).fetchone()
        return float(row[0]) if row else 0.0

    def by_service(self, account_id: str, window: _Window) -> list[tuple[str, float]]:
        s, e = window.iso()
        rows = self._db.execute(
            f"""
            SELECT COALESCE(service_name, service_code) AS svc,
                   SUM(unblended_cost) AS cost
            FROM {LINE_ITEMS_VIEW}
            WHERE account_id = ? AND usage_date >= ? AND usage_date < ?
            GROUP BY svc
            ORDER BY cost DESC
            """,
            [account_id, s, e],
        ).fetchall()
        return [(r[0], float(r[1])) for r in rows]

    def daily_service_matrix(self, account_id: str, window: _Window):
        """Same shape as CostExplorerClient.daily_service_matrix output."""
        s, e = window.iso()
        rows = self._db.execute(
            f"""
            SELECT usage_date, COALESCE(service_name, service_code) AS svc,
                   SUM(unblended_cost) AS cost
            FROM {LINE_ITEMS_VIEW}
            WHERE account_id = ? AND usage_date >= ? AND usage_date < ?
            GROUP BY usage_date, svc
            ORDER BY usage_date
            """,
            [account_id, s, e],
        ).fetchall()
        # Reshape into the same ResultsByTime list CE returns, so downstream
        # code (DailyServiceMatrix.from_ce) just works.
        by_day: dict[str, list] = {}
        for d, svc, cost in rows:
            day = d.isoformat() if hasattr(d, "isoformat") else str(d)
            by_day.setdefault(day, []).append({
                "Keys": [svc],
                "Metrics": {"UnblendedCost": {"Amount": f"{float(cost)}", "Unit": "USD"}},
            })
        out = []
        sorted_days = sorted(by_day.keys())
        for i, day in enumerate(sorted_days):
            next_day = (dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat()
            out.append({
                "TimePeriod": {"Start": day, "End": next_day},
                "Groups": by_day[day],
            })
        return out

    def attribute_resources(self, account_id: str, window: _Window) -> list[dict]:
        """Per-resource cost with name + tags. The thing CE can't give us."""
        s, e = window.iso()
        rows = self._db.execute(
            f"""
            SELECT
              resource_id,
              COALESCE(service_name, service_code) AS svc,
              ANY_VALUE(tags) AS tags,
              SUM(unblended_cost) AS cost,
              SUM(usage_amount) AS usage_amount
            FROM {LINE_ITEMS_VIEW}
            WHERE account_id = ?
              AND usage_date >= ? AND usage_date < ?
              AND resource_id IS NOT NULL AND resource_id <> ''
            GROUP BY resource_id, svc
            ORDER BY cost DESC
            """,
            [account_id, s, e],
        ).fetchall()
        out: list[dict] = []
        for resource_id, svc, tags, cost, usage in rows:
            tag_map = dict(tags) if tags else {}
            name = tag_map.get("Name") or tag_map.get("name") or resource_id
            out.append({
                "resource_id": resource_id,
                "name": name,
                "service": svc,
                "tags": tag_map,
                "cost": round(float(cost), 4),
                "usage_amount": float(usage) if usage is not None else None,
            })
        return out
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_cur_store.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add aws_cost_ultra/cur/store.py tests/test_cur_store.py tests/conftest.py
git commit -m "feat(cur): CurStore query layer with named per-resource attribution"
```

---

## Task 5: `CostSource` strategy — CUR first, CE fallback

**Files:**
- Create: `aws_cost_ultra/aws/cost_source.py`
- Create: `tests/test_cost_source.py`

The strategy: if CUR exists and `has_data(account_id, window)` is true → use it. Otherwise → fall back to `CostStore` (Plan 1's CE path). Route handlers depend only on `CostSource`, not on the underlying technology.

- [ ] **Step 1: Write failing test**

```python
# tests/test_cost_source.py
import datetime as dt
from dataclasses import dataclass
from unittest.mock import MagicMock

from aws_cost_ultra.aws.cost_source import CostSource


@dataclass
class W:
    start: dt.date
    end: dt.date
    def iso(self): return (self.start.isoformat(), self.end.isoformat())


def test_uses_cur_when_data_present():
    cur = MagicMock(); cur.has_data.return_value = True
    cur.daily_service_matrix.return_value = []
    ce = MagicMock()
    cs = MagicMock()  # CostStore
    src = CostSource(cur_store=cur, cost_store=cs)
    src.get_matrix("p1", "acct1", W(dt.date(2026,5,1), dt.date(2026,5,2)), spec="x")
    cur.daily_service_matrix.assert_called_once()
    cs.get_matrix.assert_not_called()


def test_falls_back_to_ce_when_cur_empty():
    cur = MagicMock(); cur.has_data.return_value = False
    cs = MagicMock()
    src = CostSource(cur_store=cur, cost_store=cs)
    src.get_matrix("p1", "acct1", W(dt.date(2026,5,1), dt.date(2026,5,2)), spec="x")
    cs.get_matrix.assert_called_once()


def test_no_cur_configured_falls_back_to_ce():
    cs = MagicMock()
    src = CostSource(cur_store=None, cost_store=cs)
    src.get_matrix("p1", "acct1", W(dt.date(2026,5,1), dt.date(2026,5,2)), spec="x")
    cs.get_matrix.assert_called_once()


def test_attribute_resources_prefers_cur():
    cur = MagicMock(); cur.has_data.return_value = True
    cur.attribute_resources.return_value = [{"name": "web-1"}]
    cs = MagicMock()
    src = CostSource(cur_store=cur, cost_store=cs)
    out = src.attribute_resources("acct1", W(dt.date(2026,5,1), dt.date(2026,5,2)), session=None, spec="x")
    assert out == [{"name": "web-1"}]


def test_attribute_resources_falls_back_to_describe_path_when_no_cur():
    cs = MagicMock()
    cs.attribute_resources_via_describe.return_value = [{"name": "fallback"}]
    src = CostSource(cur_store=None, cost_store=cs)
    out = src.attribute_resources("acct1", W(dt.date(2026,5,1), dt.date(2026,5,2)), session="sess", spec="x")
    assert out == [{"name": "fallback"}]
```

- [ ] **Step 2: Implement `CostSource`**

```python
# aws_cost_ultra/aws/cost_source.py
"""Strategy: prefer the local CUR warehouse over Cost Explorer.

Route handlers depend on this abstraction. When CUR is configured and
has data for the window, queries are local DuckDB (free). When CUR
doesn't cover the window (e.g., today's intraday, or before CUR was
enabled), fall back to the cached CE matrix.
"""

from __future__ import annotations

from typing import Optional, Protocol

from aws_cost_ultra.aws.cost_store import CostStore, DailyServiceMatrix


class _Window(Protocol):
    def iso(self) -> tuple[str, str]: ...


class CostSource:
    def __init__(self, *, cur_store, cost_store: CostStore) -> None:
        self._cur = cur_store      # CurStore or None
        self._ce = cost_store

    def _use_cur(self, account_id: str, window: _Window) -> bool:
        return self._cur is not None and self._cur.has_data(account_id, window)

    def get_matrix(self, profile: str, account_id: str, window: _Window, spec) -> DailyServiceMatrix:
        if self._use_cur(account_id, window):
            raw = self._cur.daily_service_matrix(account_id, window)
            return DailyServiceMatrix.from_ce(raw)
        return self._ce.get_matrix(profile, account_id, window, spec)

    def attribute_resources(self, account_id: str, window: _Window, *, session, spec) -> list[dict]:
        if self._use_cur(account_id, window):
            return self._cur.attribute_resources(account_id, window)
        # Fallback path: existing describe + USAGE_TYPE attribution from Plan 1.
        return self._ce.attribute_resources_via_describe(account_id, window, session=session, spec=spec)
```

Also add a thin pass-through method on `CostStore` so the fallback has a stable API:

```python
# aws_cost_ultra/aws/cost_store.py — add to CostStore class
def attribute_resources_via_describe(self, account_id, window, *, session, spec) -> list[dict]:
    """Fallback when CUR isn't available: describe + USAGE_TYPE attribution."""
    from aws_cost_ultra.resources import enumerate_all
    resources = enumerate_all(session=session, window=window, spec=spec)
    return [
        {
            "resource_id": r.resource_id,
            "name": r.name or r.resource_id,
            "service": r.service,
            "tags": r.tags or {},
            "cost": round(r.attributed_cost, 4),
            "usage_amount": None,
        }
        for r in resources
    ]
```

(Adjust attribute names to whatever `AttributedResource` actually has.)

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_cost_source.py -v
```
Expected: 5 passed.

- [ ] **Step 4: Commit**

```bash
git add aws_cost_ultra/aws/cost_source.py aws_cost_ultra/aws/cost_store.py tests/test_cost_source.py
git commit -m "feat(cost): CostSource strategy — CUR first, CE fallback"
```

---

## Task 6: Wire `CostSource` into `deps.py` + route handlers

**Files:**
- Modify: `aws_cost_ultra/web/deps.py` — provide `get_cost_source()` dependency
- Modify: `aws_cost_ultra/web/routes/cost.py` — use `CostSource` instead of `CostStore` directly
- Modify: `aws_cost_ultra/web/routes/resources_api.py` — use `CostSource.attribute_resources()`

- [ ] **Step 1: Add the dependency factory**

```python
# aws_cost_ultra/web/deps.py — append
from pathlib import Path
import os
import duckdb

from aws_cost_ultra.cur.schema import connect as cur_connect, ensure_line_items_view, get_parquet_glob
from aws_cost_ultra.cur.store import CurStore
from aws_cost_ultra.aws.cost_source import CostSource
from aws_cost_ultra.aws.cost_store import CostStore

_CUR_DB_PATH = Path(os.environ.get(
    "ACU_CUR_DB",
    str(_CACHE_DIR / "cur.duckdb"),
))


_cur_conn: duckdb.DuckDBPyConnection | None = None


def get_cur_store() -> CurStore | None:
    global _cur_conn
    if _cur_conn is None:
        if not _CUR_DB_PATH.exists():
            return None
        _cur_conn = cur_connect(_CUR_DB_PATH)
        if get_parquet_glob(_cur_conn):
            ensure_line_items_view(_cur_conn)
    return CurStore(_cur_conn)


def get_cost_source(session: boto3.Session) -> CostSource:
    ce = get_ce_client(session)
    cost_store = CostStore(ce, cache_get=cache_get, cache_set=cache_set)
    return CostSource(cur_store=get_cur_store(), cost_store=cost_store)
```

- [ ] **Step 2: Update `cost.py` route handlers**

Replace `CostStore(...)` instantiations with `get_cost_source(session)` calls. The matrix-using code is identical because `CostSource.get_matrix` returns the same `DailyServiceMatrix`.

```python
# in _build_summary_ctx, _build_services_ctx, _build_trend_ctx — replace
store = CostStore(ce, cache_get=cache_get, cache_set=cache_set)
m = store.get_matrix(profile, account_id, window, spec)
# with
from aws_cost_ultra.web.deps import get_cost_source
src = get_cost_source(session)
m = src.get_matrix(profile, account_id, window, spec)
```

- [ ] **Step 3: Update `resources_api.py`**

The Resources page now calls `src.attribute_resources(...)` and renders the named rows. The existing `enumerate_all` describe-path runs only when CUR has no data for the window (or no CUR).

```python
# aws_cost_ultra/web/routes/resources_api.py — inside the data endpoint
src = get_cost_source(session)
rows = src.attribute_resources(account_id, window, session=session, spec=spec)
# group by service for the existing UI shape
by_service: dict[str, list[dict]] = {}
for r in rows:
    by_service.setdefault(r["service"], []).append(r)
ctx = {"rows": rows, "by_service": by_service, ...}
```

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/ -v
```
Expected: all green.

- [ ] **Step 5: Manual smoke (without CUR yet)**

```bash
ACU_CACHE_DIR=/tmp/acu_test rm -rf /tmp/acu_test
uvicorn aws_cost_ultra.web.app:app --port 8080 &
sleep 2
curl -sI 'http://127.0.0.1:8080/api/cost/summary/data?profile=default&period=mtd' | grep X-CE
# Expected: same as Plan 1 — CE still used because no CUR db exists yet.
```

- [ ] **Step 6: Commit**

```bash
git add aws_cost_ultra/web/deps.py aws_cost_ultra/web/routes/cost.py aws_cost_ultra/web/routes/resources_api.py
git commit -m "feat(cost): route handlers depend on CostSource — CUR first, CE fallback"
```

---

## Task 7: Terraform module for CUR 2.0 + S3 bucket

**Files:**
- Create: `iac/cur/main.tf`
- Create: `iac/cur/variables.tf`
- Create: `iac/cur/outputs.tf`
- Create: `iac/cur/README.md`

CUR 2.0 (Data Exports) lives in **us-east-1** regardless of where the user's workloads run. The bucket can be in any region (we'll use the user's `ap-south-1` since they're already there per their profile).

- [ ] **Step 1: Write `main.tf`**

```hcl
# iac/cur/main.tf
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.40" }
  }
}

# CUR / Data Exports API lives in us-east-1
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

resource "aws_s3_bucket" "cur" {
  bucket = var.bucket_name
  force_destroy = true   # this bucket holds your CUR copy — fine to wipe
}

resource "aws_s3_bucket_versioning" "cur" {
  bucket = aws_s3_bucket.cur.id
  versioning_configuration { status = "Disabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "cur" {
  bucket = aws_s3_bucket.cur.id
  rule {
    id     = "expire-old-cur"
    status = "Enabled"
    expiration { days = var.retention_days }
  }
}

# Allow the AWS Billing service to write CUR objects into the bucket.
data "aws_iam_policy_document" "cur_bucket" {
  statement {
    sid     = "AllowBillingPut"
    effect  = "Allow"
    actions = ["s3:PutObject"]
    principals { type = "Service"; identifiers = ["billingreports.amazonaws.com"] }
    resources = ["${aws_s3_bucket.cur.arn}/*"]
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
  statement {
    sid     = "AllowBillingList"
    effect  = "Allow"
    actions = ["s3:GetBucketAcl", "s3:GetBucketPolicy"]
    principals { type = "Service"; identifiers = ["billingreports.amazonaws.com"] }
    resources = [aws_s3_bucket.cur.arn]
  }
}

resource "aws_s3_bucket_policy" "cur" {
  bucket = aws_s3_bucket.cur.id
  policy = data.aws_iam_policy_document.cur_bucket.json
}

data "aws_caller_identity" "current" {}

# CUR 2.0 / Data Exports — Parquet, daily, hourly granularity, with resource IDs + tags.
resource "aws_bcmdataexports_export" "cur" {
  provider = aws.us_east_1
  export {
    name = var.export_name
    data_query {
      query_statement = "SELECT * FROM COST_AND_USAGE_REPORT"
      table_configurations = {
        COST_AND_USAGE_REPORT = {
          TIME_GRANULARITY                      = "DAILY"
          INCLUDE_RESOURCES                     = "TRUE"
          INCLUDE_SPLIT_COST_ALLOCATION_DATA    = "FALSE"
          INCLUDE_MANUAL_DISCOUNT_COMPATIBILITY = "FALSE"
        }
      }
    }
    destination_configurations {
      s3_destination {
        s3_bucket = aws_s3_bucket.cur.id
        s3_prefix = var.s3_prefix
        s3_region = aws_s3_bucket.cur.region
        s3_output_configurations {
          overwrite   = "OVERWRITE_REPORT"
          format      = "PARQUET"
          compression = "PARQUET"
          output_type = "CUSTOM"
        }
      }
    }
    refresh_cadence { frequency = "SYNCHRONOUS" }
  }
}
```

- [ ] **Step 2: Write `variables.tf` and `outputs.tf`**

```hcl
# iac/cur/variables.tf
variable "bucket_name" {
  type        = string
  description = "S3 bucket that will receive the CUR Parquet exports. Must be globally unique."
}

variable "export_name" {
  type        = string
  default     = "acu-cur"
}

variable "s3_prefix" {
  type        = string
  default     = "cur/"
}

variable "retention_days" {
  type        = number
  default     = 400  # ~13 months
}
```

```hcl
# iac/cur/outputs.tf
output "bucket"   { value = aws_s3_bucket.cur.id }
output "prefix"   { value = var.s3_prefix }
output "region"   { value = aws_s3_bucket.cur.region }
```

- [ ] **Step 3: Write `iac/cur/README.md`**

```markdown
# CUR Terraform

Creates an S3 bucket and a Cost and Usage Report 2.0 (Data Exports) definition that
delivers daily Parquet line-items into the bucket.

## Apply

```bash
cd iac/cur
terraform init
terraform apply \
  -var="bucket_name=acu-cur-<your-account-id>-<region>"
```

First export arrives within 24h. Once it does, run:

```bash
aws-cost-ultra cur ingest \
  --bucket "$(terraform output -raw bucket)" \
  --prefix "$(terraform output -raw prefix)"
```

## Destroy

```bash
terraform destroy
```

S3 storage cost for a small account is well under $0.01/month.
```

- [ ] **Step 4: Commit (no apply yet — that's a manual step the user takes)**

```bash
git add iac/
git commit -m "feat(iac): Terraform for CUR 2.0 S3 export"
```

---

## Task 8: CLI subcommand: `aws-cost-ultra cur ...`

**Files:**
- Create: `aws_cost_ultra/cur/setup.py`
- Modify: `aws_cost_ultra/cli/__init__.py` (whichever file currently dispatches CLI subcommands)

Three subcommands:
- `cur status` — show whether CUR is configured and current
- `cur ingest --bucket B --prefix P` — pull new partitions
- `cur reset` — drop the local DuckDB and start over

- [ ] **Step 1: Write `setup.py`**

```python
# aws_cost_ultra/cur/setup.py
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import boto3

from aws_cost_ultra.cur.ingestor import CurIngestor
from aws_cost_ultra.cur.schema import connect, get_parquet_glob


def _db_path() -> Path:
    return Path(os.environ.get(
        "ACU_CUR_DB",
        str(Path.home() / ".cache" / "aws_cost_ultra" / "cur.duckdb"),
    ))


def _local_dir() -> Path:
    return Path(os.environ.get(
        "ACU_CUR_PARQUET_DIR",
        str(Path.home() / ".cache" / "aws_cost_ultra" / "parquet"),
    ))


def cmd_status(_args) -> int:
    db = connect(_db_path())
    glob = get_parquet_glob(db)
    if not glob:
        print("CUR not configured. Run `aws-cost-ultra cur ingest --bucket … --prefix …` first.")
        return 1
    n = db.execute("SELECT count(*) FROM cur_manifests").fetchone()[0]
    print(f"CUR DB:        {_db_path()}")
    print(f"Parquet glob:  {glob}")
    print(f"Partitions:    {n}")
    if n > 0:
        latest = db.execute("SELECT max(ingested_at) FROM cur_manifests").fetchone()[0]
        print(f"Last ingest:   {latest}")
    return 0


def cmd_ingest(args) -> int:
    session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
    s3 = session.client("s3")
    db = connect(_db_path())
    ing = CurIngestor(
        s3_client=s3,
        bucket=args.bucket,
        prefix=args.prefix,
        local_dir=_local_dir(),
        db=db,
    )
    n = ing.ingest()
    print(f"Ingested {n} new partition(s).")
    return 0


def cmd_reset(_args) -> int:
    p = _db_path()
    if p.exists():
        p.unlink()
        print(f"removed {p}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aws-cost-ultra cur")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(fn=cmd_status)

    ing = sub.add_parser("ingest")
    ing.add_argument("--bucket", required=True)
    ing.add_argument("--prefix", required=True)
    ing.add_argument("--profile", default=None)
    ing.set_defaults(fn=cmd_ingest)

    sub.add_parser("reset").set_defaults(fn=cmd_reset)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Wire into the top-level CLI**

Find the existing `aws-cost-ultra` CLI dispatcher (`aws_cost_ultra/cli/__init__.py` or similar) and add:

```python
# in the main() dispatcher
if argv and argv[0] == "cur":
    from aws_cost_ultra.cur.setup import main as cur_main
    return cur_main(argv[1:])
```

- [ ] **Step 3: Smoke test**

```bash
aws-cost-ultra cur status        # should report "not configured"
aws-cost-ultra cur reset          # should be a no-op when no file exists
```

- [ ] **Step 4: Commit**

```bash
git add aws_cost_ultra/cur/setup.py aws_cost_ultra/cli/
git commit -m "feat(cli): aws-cost-ultra cur {status,ingest,reset} subcommands"
```

---

## Task 9: Scheduled ingest — APScheduler background job

**Files:**
- Modify: `aws_cost_ultra/web/app.py`
- Add new dependency: `apscheduler>=3.10` (or use a simple threading-based scheduler — keep it stdlib if possible)

Once CUR is configured, the server should poll S3 for new partitions every ~6h. We keep it simple with a daemon thread + sleep, no APScheduler dependency.

- [ ] **Step 1: Add the background ingestor**

```python
# aws_cost_ultra/web/app.py — append to existing startup logic
import threading
import time

def _cur_ingest_worker():
    interval = float(os.environ.get("ACU_CUR_INGEST_INTERVAL_SECONDS", str(6 * 3600)))
    bucket = os.environ.get("ACU_CUR_BUCKET")
    prefix = os.environ.get("ACU_CUR_PREFIX", "cur/")
    profile = os.environ.get("ACU_CUR_PROFILE")
    if not bucket:
        return
    while True:
        try:
            session = boto3.Session(profile_name=profile) if profile else boto3.Session()
            from aws_cost_ultra.cur.ingestor import CurIngestor
            from aws_cost_ultra.cur.schema import connect
            db = connect(_CUR_DB_PATH)
            CurIngestor(
                s3_client=session.client("s3"),
                bucket=bucket,
                prefix=prefix,
                local_dir=Path(os.environ.get("ACU_CUR_PARQUET_DIR", str(_CACHE_DIR / "parquet"))),
                db=db,
            ).ingest()
        except Exception as exc:
            log.warning("CUR ingest failed: %s", exc, exc_info=True)
        time.sleep(interval)


@app.on_event("startup")
def _start_cur_worker():
    if os.environ.get("ACU_CUR_BUCKET"):
        threading.Thread(target=_cur_ingest_worker, daemon=True, name="acu-cur-ingest").start()
```

- [ ] **Step 2: Commit**

```bash
git commit -am "feat(cur): background S3 → DuckDB ingest every 6h"
```

---

## Task 10: End-to-end manual verification with real CUR

This task is **manual** (depends on user applying Terraform and waiting 24h for first delivery).

- [ ] **Step 1: Apply Terraform**

```bash
cd iac/cur
terraform init
terraform apply -var "bucket_name=acu-cur-012178638401-ap-south-1"
```

- [ ] **Step 2: Wait 24h for first CUR delivery** — AWS Billing publishes the first report ~24h after the export is created.

- [ ] **Step 3: Initial ingest**

```bash
aws-cost-ultra cur ingest --profile terraform-learning \
  --bucket acu-cur-012178638401-ap-south-1 \
  --prefix cur/
aws-cost-ultra cur status
```
Expected: 1+ partitions ingested, last ingest timestamp recent.

- [ ] **Step 4: Verify Resources page now shows names**

```bash
ACU_CUR_BUCKET=acu-cur-012178638401-ap-south-1 \
ACU_CUR_PROFILE=terraform-learning \
uvicorn aws_cost_ultra.web.app:app --port 8080
```

Open the app, go to Resources page. You should see:
- Each EC2 instance by its `Name` tag (e.g., "web-1") rather than instance id alone
- Each S3 bucket by its actual name with exact unblended cost
- Each EBS volume by `Name` tag (or volume id if untagged)
- `X-CE-Calls-Spent: 0` on the resources endpoint

- [ ] **Step 5: Verify CE fallback still works for today's intraday**

Pick a window that's today only:
```bash
curl -sI 'http://127.0.0.1:8080/api/cost/summary/data?profile=default&period=mtd' | grep X-CE
```
Expected: CUR provides up through yesterday; today still goes to CE (1–2 CE calls). For most use cases (you monitor 2–3x/week), this is fine.

---

## Self-Review

**Spec coverage check** against §6 Weeks 2–3:

| Spec item | Plan task |
|---|---|
| 13. Terraform for CUR 2.0 + S3 | Task 7 |
| 14. `cur/ingestor.py` incremental S3 → DuckDB | Task 3 |
| 15. `cur/store.py` query layer | Task 4 |
| 16. `CostSource` strategy | Task 5, 6 |
| 17. `/api/setup/cur` flow + UI | **Deferred to Plan 3 polish** — for now, CLI is enough |
| 18. Resource-level via single DuckDB query | Task 4 (`attribute_resources`) + Task 6 (wired into resources_api) |
| 19. Optional Athena fallback | **Skipped — YAGNI**, DuckDB is sufficient |

**Placeholder scan:** No vague items. The CUR 2.0 column names may need real-world adjustment in Task 2 (`schema.py`) once the user generates their first export; the test fixture in Task 4 uses the documented CUR 2.0 names but real exports can have minor schema drift. That's a known unknown, documented in `schema.py` comments.

**Type consistency:** `DailyServiceMatrix`, `CostSource`, `CurStore`, `CostStore` all use the same `_Window` protocol. `attribute_resources` returns the same dict shape across CUR and describe-fallback paths.

---

## Verification (end-to-end)

After Tasks 1–9 + a real CUR delivery (Task 10):

```bash
# Cold dashboard load when CUR has yesterday's data
curl -sI 'http://127.0.0.1:8080/api/cost/summary/data?profile=default&period=last_month' | grep X-CE
# Expected: X-CE-Calls-Spent: 0  (last_month is fully covered by CUR)

curl -sI 'http://127.0.0.1:8080/api/cost/summary/data?profile=default&period=mtd' | grep X-CE
# Expected: X-CE-Calls-Spent: 1 or 2  (today's intraday isn't in CUR yet)

curl -s 'http://127.0.0.1:8080/api/resources/data?profile=default&period=last_month&region=all' | jq '.rows[:5]'
# Expected: each row has resource_id + name + cost. Named, not anonymous.
```

Steady-state CE bill:
- 1 CE forecast call/profile/dashboard load = $0.01 × however many times you load the dashboard (a few cents/month)
- 0 CE calls for resources, services, trend, summary (all CUR)
- 0 CE calls for last_month and earlier (all CUR)
- ~$0.001/month in S3 storage for CUR Parquet
