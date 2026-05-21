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
    glob = str(cur_sample_parquet / "*" / "*" / "*.parquet")
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
