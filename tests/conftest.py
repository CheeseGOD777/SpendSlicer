
import pyarrow as pa
import pyarrow.parquet as pq
import pytest


@pytest.fixture(scope="session")
def cur_sample_parquet(tmp_path_factory):
    rows = [
        # date, account, service_code, service_name, resource_id, tags, usage_type, op, usage, unblended
        ("2026-05-18", "123456789012", "AmazonEC2", "Amazon Elastic Compute Cloud",
         "i-aaa1", {"Name": "web-1", "Project": "influenzer"}, "BoxUsage:t4g.small", "RunInstances", 24.0, 1.50),
        ("2026-05-19", "123456789012", "AmazonEC2", "Amazon Elastic Compute Cloud",
         "i-aaa1", {"Name": "web-1", "Project": "influenzer"}, "BoxUsage:t4g.small", "RunInstances", 24.0, 1.55),
        ("2026-05-18", "123456789012", "AmazonS3", "Amazon Simple Storage Service",
         "my-app-assets", {"Name": "my-app-assets"}, "TimedStorage-ByteHrs", "StandardStorage", 1024.0, 0.20),
        ("2026-05-19", "123456789012", "AmazonS3", "Amazon Simple Storage Service",
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
    root = tmp_path_factory.mktemp("cur")
    out_dir = root / "2026-05" / "abc-asm"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "part-0.snappy.parquet"
    pq.write_table(table, out_path, compression="snappy")
    return root  # billing period root so glob root/"*"/"*"/"*.parquet" matches
