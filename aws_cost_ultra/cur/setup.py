"""CLI helpers for the local CUR warehouse."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import boto3

from aws_cost_ultra.cur.ingestor import CurIngestor
from aws_cost_ultra.cur.schema import connect, get_parquet_glob

log = logging.getLogger("aws_cost_ultra.cur.setup")


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
    else:
        print("Nothing to reset.")
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
