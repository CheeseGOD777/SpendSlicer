# Architecture

## Shape of the thing

SpendSlicer is a local FastAPI server that talks to AWS with your own credentials
and serves a prebuilt React dashboard. There is no backend service, no database
you have to run, and no component that ever sees your cost data.

```
   Browser / native webview
            │  HTTP on 127.0.0.1
            ▼
   ┌──────────────────────┐
   │  FastAPI (spendslicer) │
   │  ┌────────────────┐  │        ┌─────────────────────┐
   │  │ SQLite cache   │◄─┼────────┤ AWS Cost Explorer   │  $0.01/request
   │  │ TTL + SWR      │  │        │ EC2/RDS/S3/... APIs │  free
   │  └────────────────┘  │        │ Pricing, CloudWatch │
   │  ┌────────────────┐  │        └─────────────────────┘
   │  │ DuckDB (CUR)   │◄─┼──── optional, from your S3 bucket
   │  └────────────────┘  │
   └──────────────────────┘
```

## Module layout

```
spendslicer/
  core/         Pure logic — no AWS, no framework, fully unit-testable
    filters.py       Cost Explorer filter construction (pre-credit gross, etc.)
    time_windows.py  UTC half-open [start, end) windows
    pricing.py       Pricing API wrapper + fallback rate table
    provenance.py    Where every number came from
    service_groups.py, types.py

  aws/          AWS API wrappers
    session.py       Profile discovery, ProfileBundle, parallel fan-out
    cost_explorer.py CE client; every return value carries provenance
    cost_store.py    Cached CE access with per-key single-flight
    cost_source.py   Chooses CUR or Cost Explorer per query

  resources/    Per-resource attribution, one module per service
    runner.py        Parallel (service x region) fan-out, rescaling
    ec2.py ebs.py rds.py s3.py elb.py eip.py lambda_fn.py dynamodb.py

  audit/        Waste radar
    idle.py untagged.py budgets.py runner.py

  cur/          Optional CUR warehouse (DuckDB + Parquet)
  exporters/    CSV / JSON / PDF / Slack / S3 / SES
  web/          FastAPI app, routes, cache, dependency wiring
  desktop.py    Native-window launcher for the packaged builds
```

The dependency direction is one-way: `core` knows nothing about AWS, `aws`
knows nothing about the web layer, and `web` wires everything together. That is
what makes the attribution math testable without mocking HTTP.

## How a cost number is produced

1. **Service totals come from Cost Explorer.** `GetCostAndUsage` grouped by
   `SERVICE`, filtered to pre-credit gross (excluding Credit, Refund, and
   upfront RI/SP amortisation) so the figure matches the Billing console.

2. **Resources are enumerated per region.** `runner.py` builds a flat list of
   (service, region) work units and submits them to a single bounded pool of 16
   threads. An earlier design nested pools inside pools and reached ~70
   concurrent threads, which throttled hard against the AWS APIs.

3. **Each resource gets an estimated cost.** Running hours from the resource's
   state and launch time, multiplied by a list price from the Pricing API (or
   the built-in fallback table).

4. **Estimates are rescaled to the Cost Explorer total.** The per-service sum of
   estimates rarely matches the ground-truth total, so every row is scaled by
   `ce_total / estimated_sum`.

   This is guarded. If the ratio falls outside 0.2x–5x, rescaling is skipped
   entirely — a near-zero estimate sum would otherwise multiply every row into
   nonsense. The unexplained remainder is surfaced as **unattributed drift**
   rather than hidden.

5. **Provenance rides along.** Every `CostValue` carries a `Provenance` record:
   which metric, which record types, which window, which source, and the
   variance from ground truth. The UI surfaces it; exports print it.

With the CUR warehouse enabled, steps 3–4 are replaced by real billed line
items and the estimation disappears.

## Caching

Cost Explorer costs $0.01 per request, so the cache is a spend control.

- **SQLite-backed** (`web/sqlite_cache.py`), so it survives restarts and
  reload cycles. Concurrent access is handled with WAL mode and a per-key
  single-flight lock, and a corrupt database is detected and recreated.
- **Stale-while-revalidate.** Fresh for 30 minutes, then served stale for
  another 6 hours while a background thread refreshes it. A user never waits on
  a Cost Explorer round-trip for data that already exists.
- **Deduplicated and capped.** One refresh per key at a time, with a global
  in-flight cap; beyond it, refresh requests are shed rather than queued.
- **Two pools.** Minutes-long resource enumerations run on a separate pool from
  cheap CE refreshes, so a heavy job cannot starve a hot key.

Per-request Cost Explorer spend is tracked in a `contextvars` counter and
returned as `X-CE-Calls-Spent` / `X-CE-Estimated-Cost-USD`. Background
producers get their own counter so their spend is not misattributed to whichever
request happened to trigger the refresh.

## Web layer

- `web/app.py` — app construction, auth/CSRF dependency, lifespan hooks
- `web/deps.py` — cache, session factory, background refresh pool, period parsing
- `web/routes/` — `cost.py`, `resources_api.py`, `audit_api.py`, `export_api.py`, `pages.py`
- `web/assets.py` — resolves the React bundle across source checkout, installed
  wheel, and frozen build

The frontend is a Vite + React SPA in `frontend/`, built into
`spendslicer/web/static/` and committed, so neither `pip install` nor `./run.sh`

### Security model

- Loopback bind by default
- Optional shared-secret token (`SPENDSLICER_AUTH_TOKEN`), constant-time compared
- Origin/Referer allow-list on state-changing requests, blocking classic CSRF
  and DNS rebinding
- Client-supplied `profile`, `period`, and `region` values are validated against
  allow-lists before reaching boto3 or a cache key — a profile name selects
  which credentials (and potentially which `credential_process`) run, so it is
  never passed through unchecked

See [SECURITY.md](../SECURITY.md) for the full threat model.

## Testing

190 Python tests plus a frontend suite, run against Python 3.10–3.13 on every
push. AWS is mocked with `moto` and `unittest.mock`; no test touches a real
account. The bulk of the coverage sits on the parts most likely to be quietly
wrong: attribution math, rescaling guards, UTC window boundaries, cache
concurrency, and audit thresholds.

```bash
pytest -q                      # Python
cd frontend && npm test        # Frontend
ruff check .                   # Lint
```
