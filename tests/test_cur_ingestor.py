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
