# Configuration

Everything is configured through environment variables. There is no config
file, and none of these are required — CostSight runs with sensible defaults
out of the box.

## Server

| Variable | Default | What it does |
| --- | --- | --- |
| `COSTSIGHT_HOST` | `127.0.0.1` | Bind address. **Do not change this without also setting `COSTSIGHT_AUTH_TOKEN`.** |
| `COSTSIGHT_PORT` | `8080` | Bind port. The desktop app ignores this and asks the OS for a free port unless you set it explicitly. |
| `COSTSIGHT_RELOAD` | `0` | `1` enables uvicorn autoreload. Development only — it re-execs the process and breaks frozen builds. |
| `COSTSIGHT_LOG_LEVEL` | `warning` | Standard log levels. `debug` is useful when diagnosing AWS call failures. |

## Security

| Variable | Default | What it does |
| --- | --- | --- |
| `COSTSIGHT_AUTH_TOKEN` | *(unset)* | Shared secret required on every money-spending route, via the `X-CostSight-Token` header or a `?token=` query parameter. Unset means auth is off. |
| `COSTSIGHT_ALLOWED_HOSTS` | `localhost,127.0.0.1,::1` | Comma-separated hosts the server will answer state-changing requests for. Anti-DNS-rebinding and CSRF allow-list. |

Auth is off by default so that a laptop-local install needs zero setup. The
moment you bind anything other than loopback, set a token — the server logs a
warning at startup if you haven't, because an open port here spends real money,
not just leaks data.

```bash
export COSTSIGHT_AUTH_TOKEN="$(openssl rand -base64 32)"
export COSTSIGHT_HOST=0.0.0.0
export COSTSIGHT_ALLOWED_HOSTS=costsight.internal.example.com
costsight-web
```

The desktop builds set a fresh random token on every launch automatically.

## Caching and Cost Explorer spend

Cost Explorer bills **$0.01 per request**, so caching is a cost control, not
just a latency one.

| Variable | Default | What it does |
| --- | --- | --- |
| `COSTSIGHT_CACHE_DIR` | `~/.cache/costsight` | Where the SQLite cache, CUR database, and webview storage live. |
| `COSTSIGHT_CACHE_TTL_SECONDS` | `1800` (30 min) | How long a cached response is considered fresh. |
| `COSTSIGHT_CACHE_SWR_SECONDS` | `21600` (6 h) | Additional window during which stale data is served immediately while refreshing in the background. |
| `COSTSIGHT_MAX_INFLIGHT_REFRESHES` | `32` | Global cap on queued/running background refreshes. Beyond this, new refresh requests are shed rather than queued. |
| `COSTSIGHT_ENABLE_PREWARM` | `0` | `1` warms caches for every profile at startup. Off by default because it fans out a lot of paid API calls; useful for a kiosk dashboard. |

Cost Explorer data only updates a few times a day, so the 30-minute default is
already aggressive. Raising it saves money with essentially no loss of freshness:

```bash
export COSTSIGHT_CACHE_TTL_SECONDS=21600   # 6 hours
export COSTSIGHT_CACHE_SWR_SECONDS=86400   # serve stale for a day
```

Clear the cache with `POST /api/cache/clear` or by deleting
`$COSTSIGHT_CACHE_DIR/cache.db`.

## CUR warehouse (optional)

Setting `COSTSIGHT_CUR_BUCKET` starts a background worker that pulls new CUR
partitions from S3 into a local DuckDB database. See [CUR.md](CUR.md).

| Variable | Default | What it does |
| --- | --- | --- |
| `COSTSIGHT_CUR_BUCKET` | *(unset)* | S3 bucket holding CUR 2.0 / Data Exports Parquet files. Unset disables CUR entirely. |
| `COSTSIGHT_CUR_PREFIX` | `cur/` | Key prefix within the bucket. |
| `COSTSIGHT_CUR_PROFILE` | *(unset)* | AWS profile used to read the bucket. Defaults to the ambient boto3 session. |
| `COSTSIGHT_CUR_DB` | `~/.cache/costsight/cur.duckdb` | Path to the local DuckDB file. |
| `COSTSIGHT_CUR_PARQUET_DIR` | `~/.cache/costsight/parquet` | Where downloaded CUR Parquet partitions are staged. Used by the `costsight cur` CLI. |
| `COSTSIGHT_CUR_INGEST_INTERVAL_SECONDS` | `21600` (6 h) | How often the background worker checks S3 for new partitions. |

## Export

| Variable | Default | What it does |
| --- | --- | --- |
| `COSTSIGHT_EXPORT_DIR` | `./exports` | Destination for `POST /api/export/run`. Created with mode `0700`. |

## AWS credentials

CostSight uses the standard boto3 resolution chain and does not add anything of
its own. The usual variables all work:

`AWS_PROFILE`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`,
`AWS_REGION`, `AWS_CONFIG_FILE`, `AWS_SHARED_CREDENTIALS_FILE`.

The profile dropdown lists everything in `~/.aws/credentials` and
`~/.aws/config`. A client-supplied profile name is validated against that list
before it reaches boto3, so a request cannot make the server load an arbitrary
profile or trigger an unexpected `credential_process`.
