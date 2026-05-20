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
