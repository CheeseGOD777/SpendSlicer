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
