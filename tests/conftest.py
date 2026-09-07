import duckdb
import pytest


@pytest.fixture(scope="session")
def cur_sample_parquet(tmp_path_factory):
    """A CUR-shaped Parquet partition, written with DuckDB.

    DuckDB writes Parquet natively, so this used PyArrow only to build a
    fixture. Dropping that import takes PyArrow out of the dependency tree
    entirely — it was 118 MB of the 254 MB desktop bundle for something no
    shipped code path imported.

    ``product`` and ``resource_tags`` have to stay STRUCT and MAP: the
    line_items view reads ``product['product_name']``, so a flat column here
    would pass the fixture while breaking against real CUR files.
    """
    rows = [
        # date, account, service_code, service_name, resource_id, name, project, usage_type, op, usage, unblended
        ("2026-05-18", "123456789012", "AmazonEC2", "Amazon Elastic Compute Cloud",
         "i-aaa1", "web-1", "influenzer", "BoxUsage:t4g.small", "RunInstances", 24.0, 1.50),
        ("2026-05-19", "123456789012", "AmazonEC2", "Amazon Elastic Compute Cloud",
         "i-aaa1", "web-1", "influenzer", "BoxUsage:t4g.small", "RunInstances", 24.0, 1.55),
        ("2026-05-18", "123456789012", "AmazonS3", "Amazon Simple Storage Service",
         "my-app-assets", "my-app-assets", None, "TimedStorage-ByteHrs", "StandardStorage", 1024.0, 0.20),
        ("2026-05-19", "123456789012", "AmazonS3", "Amazon Simple Storage Service",
         "my-app-assets", "my-app-assets", None, "TimedStorage-ByteHrs", "StandardStorage", 1024.0, 0.22),
    ]

    selects = []
    for d, acct, code, name, rid, tag_name, tag_proj, ut, op, usage, cost in rows:
        tags = f"MAP {{'Name': '{tag_name}'}}" if tag_proj is None else \
               f"MAP {{'Name': '{tag_name}', 'Project': '{tag_proj}'}}"
        selects.append(
            f"SELECT DATE '{d[:7]}-01' AS bill_billing_period_start_date, "
            f"DATE '{d}' AS line_item_usage_start_date, "
            f"'{acct}' AS line_item_usage_account_id, "
            f"'{code}' AS line_item_product_code, "
            f"{{'product_name': '{name}'}} AS product, "
            f"'{rid}' AS line_item_resource_id, "
            f"{tags} AS resource_tags, "
            f"'{ut}' AS line_item_usage_type, "
            f"'{op}' AS line_item_operation, "
            f"{usage} AS line_item_usage_amount, "
            f"{cost} AS line_item_unblended_cost, "
            f"{cost} AS line_item_blended_cost, "
            f"'USD' AS line_item_currency_code"
        )

    root = tmp_path_factory.mktemp("cur")
    out_dir = root / "2026-05" / "abc-asm"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "part-0.snappy.parquet"

    con = duckdb.connect()
    con.execute(f"CREATE TABLE cur AS {' UNION ALL '.join(selects)}")
    con.execute("COPY cur TO ? (FORMAT PARQUET, COMPRESSION SNAPPY)", [str(out_path)])
    con.close()

    return root  # billing-period root, so glob root/"*"/"*"/"*.parquet" matches
