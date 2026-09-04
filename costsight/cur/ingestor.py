"""Pull new CUR Parquet partitions from S3 into the local DuckDB warehouse."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import duckdb

from costsight.cur.schema import ensure_line_items_view, set_parquet_glob

log = logging.getLogger("costsight.cur.ingestor")

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
                "INSERT INTO cur_manifests(billing_period, assembly_id, s3_key) "
                "SELECT ?, ?, ? WHERE NOT EXISTS ("
                "  SELECT 1 FROM cur_manifests WHERE billing_period=? AND assembly_id=? AND s3_key=?"
                ")",
                [bp, asm, key, bp, asm, key],
            )
            n_new += 1

        # Re-register the parquet glob so DuckDB sees the new files.
        glob = str(self._local / "*" / "*" / "*.parquet")
        set_parquet_glob(self._db, glob)
        ensure_line_items_view(self._db)

        log.info("CUR ingest complete: %d new partitions", n_new)
        return n_new
