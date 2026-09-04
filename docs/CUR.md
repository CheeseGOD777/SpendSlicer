# CUR warehouse (optional)

Without CUR, per-resource costs are **estimates**: Cost Explorer gives exact
service totals, and CostSight splits them across resources using running hours
and list prices. Good enough to find the expensive things; not exact.

With CUR, per-resource costs are **exact billed line items**, and the estimation
goes away entirely.

The reason this is a separate opt-in rather than the default: Cost Explorer's
`GetCostAndUsageWithResources` would give the same precision with no setup, but
it bills $0.00001 per usage record on top of $0.01 per request, which on a real
account dominates the tool's running cost. A Cost and Usage Report delivered to
your own S3 bucket costs a few cents a month in storage and nothing to query.

## What you get

| | Cost Explorer only | With CUR |
| --- | --- | --- |
| Service totals | Exact | Exact |
| Per-resource cost | Estimated, rescaled | Exact, from billed line items |
| Unattributed drift | Often non-zero | Zero |
| Query cost | $0.01 per request | Free (local DuckDB) |
| Data freshness | Hours | Up to 24h (CUR delivery cadence) |
| Setup | None | Terraform + a day's wait |

## Setup

### 1. Create the report

Terraform for an S3 bucket plus a CUR 2.0 (Data Exports) definition delivering
daily Parquet line items lives in [`iac/cur/`](../iac/cur):

```bash
cd iac/cur
terraform init
terraform apply -var="bucket_name=costsight-cur-<account-id>-<region>"
```

Prefer the console? Billing → Data Exports → Create → **Standard data export**,
with Parquet format, daily granularity, and resource IDs enabled.

### 2. Wait for the first delivery

AWS writes the first export within 24 hours. Nothing to do until it lands.

### 3. Ingest

```bash
costsight cur ingest \
  --bucket "$(terraform output -raw bucket)" \
  --prefix "$(terraform output -raw prefix)"

costsight cur status     # what's loaded
costsight cur reset      # wipe the local database
```

This downloads new Parquet partitions into
`~/.cache/costsight/parquet` and registers them in a DuckDB database at
`~/.cache/costsight/cur.duckdb`. Only new partitions are fetched on re-runs.

### 4. Point the server at it

```bash
export COSTSIGHT_CUR_BUCKET="costsight-cur-123456789012-us-east-1"
export COSTSIGHT_CUR_PREFIX="cur/"
costsight-web
```

With `COSTSIGHT_CUR_BUCKET` set, a background worker re-ingests every 6 hours
(`COSTSIGHT_CUR_INGEST_INTERVAL_SECONDS`). CostSight then uses CUR for any
query the warehouse can answer and falls back to Cost Explorer for the rest —
`cost_source.py` makes that choice per query, so there is no cliff when CUR
lacks a period.

## IAM

The ingester needs read access to the bucket, scoped to it:

```json
{
  "Effect": "Allow",
  "Action": ["s3:ListBucket", "s3:GetObject"],
  "Resource": [
    "arn:aws:s3:::YOUR-CUR-BUCKET",
    "arn:aws:s3:::YOUR-CUR-BUCKET/*"
  ]
}
```

Creating the report itself additionally needs `cur:PutReportDefinition` or
`bcm-data-exports:CreateExport`, but that is a one-time action Terraform
performs — the running app never needs it.

## Costs

S3 storage for a small-to-mid account runs well under $0.01/month. Queries are
local and free. The Data Export itself is free.

## Teardown

```bash
cd iac/cur && terraform destroy
costsight cur reset
```

## Troubleshooting

**`CUR not configured` from `cur status`.** No partitions ingested yet. Confirm
objects exist under the prefix: `aws s3 ls s3://YOUR-BUCKET/cur/ --recursive`.

**Ingest runs but finds nothing.** The prefix must match the export's S3 path
prefix exactly, and the export must be Parquet — CSV is not read.

**`ModuleNotFoundError: duckdb`.** The `cur` extra is not installed:
`pip install "costsight[cur]"`. The desktop builds bundle it already.

**Numbers differ from Cost Explorer.** Expected, and CUR is the more precise of
the two. CUR carries full line-item detail while Cost Explorer aggregates;
amortisation and credit handling can also differ. CostSight labels which source
produced each figure.
