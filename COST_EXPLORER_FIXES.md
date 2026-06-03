# Cost Explorer — Fixes Applied

All 48 confirmed findings from `COST_EXPLORER_AUDIT.md` fixed. **110 tests pass.**

## Critical / High

| # | Fix | File |
|---|-----|------|
| 1 | EC2 CE query scoped per-region (`REGION` dimension) — stops counting account-wide cost N times | `resources/ec2.py` |
| 2 | Trend-chart XSS: URL via `urlencode` + `data-url` attr, no request input in `<script>` | `web/routes/cost.py` |
| 36 | Inline service-chart JSON escaped (`</script>` `<` `>` `&` U+2028/9) | `web/routes/cost.py` |
| 12 | Export path-traversal: dropped `output_dir` param, forced fixed tempdir | `web/routes/export_api.py` |
| 14 | Auth: `ACU_AUTH_TOKEN` gate (header/query); unset = open + startup warning | `web/app.py` |
| 15 | CSRF: Origin/Referer allow-list on POSTs | `web/app.py` |
| 13 | Profile query param validated against profile list | `web/deps.py` |
| 37 | `friendly_error` no longer echoes raw AWS exception (logged server-side) | `web/context.py` |
| 5,6 | Prev-period window length-matched (calendar for mtd/last_month, shift-by-duration for rolling) | `web/routes/cost.py` |
| 7 | Trend table uses `pre_credit_gross()` cost basis | `web/routes/cost.py` |
| 4 | Forecast window starts today midnight (was tomorrow — dropped today's spend) | `core/time_windows.py` |
| 8,29 | Closed-window TTL uses UTC date + 3-day finalization margin | `aws/cost_store.py` |

## Concurrency / Scale

| # | Fix | File |
|---|-----|------|
| 17,34 | Nested thread pools flattened to one bounded executor over (service×region); one frozen session per region | `resources/runner.py` |
| 20 | EBS parallelized across regions | `resources/runner.py` |
| 21 | EC2/EBS duplicate `describe_instances` scans deduped (per-region name cache) | `resources/runner.py` |
| 3 | S3 lists buckets once, resolves region once (`attribute_s3_all`) | `resources/s3.py`, `runner.py` |
| 19 | ELB `describe_target_health` once per target group + 200-TG cap | `resources/elb.py` |
| 23 | DynamoDB `describe_table` capped (200); tags gated on cost>0 | `resources/dynamodb.py` |
| 18 | Rescale factor clamped to [0.2, 5.0] — no divide-by-near-zero inflation | `resources/runner.py` |
| 24 | Adaptive botocore retries on all resource clients | `resources/*.py` |
| 28,32 | Dropped leaking `id(session)` CE-client cache; construct per call | `web/deps.py` |
| 33 | SQLite thread-local connection reuse (was new conn per op) | `web/sqlite_cache.py` |
| 43 | Full cache bust uses plain `DELETE` (no `LIKE '%'` scan) | `web/sqlite_cache.py` |
| 30 | Refresh pool in-flight cap + shedding | `web/deps.py` |
| 27,31,46 | CE counter contextvar propagated via `copy_context().run`; side-effect-free fallback | `web/routes/cost.py`, `web/middleware.py`, `web/deps.py`, `export_api.py` |
| 22 | `enumerate_all` optional `top_n` + long-tail aggregate row | `resources/runner.py` |

## Frontend

| # | Fix | File |
|---|-----|------|
| 11,16 | Server row cap (500 default / 2000 max); frontend requests bounded limit + "load more" | `web/routes/resources_api.py`, `frontend/src/App.jsx` |
| 10 | Client-side pagination (100/page) — bounded DOM, no new dep | `frontend/src/App.jsx` |
| 35 | Clipboard async try/catch + textarea fallback + per-row feedback | `frontend/src/App.jsx` |
| 9 | SWR cache 256KB per-entry cap + LRU eviction on quota | `frontend/src/lib/swrCache.js` |

## Minor

| # | Fix | File |
|---|-----|------|
| 25 | Composition keeps negative line items (reconciles with service net) | `web/routes/cost.py` |
| 26 | Error contexts not cached | `web/routes/cost.py` |
| 38 | EIP: associated IPs not idle-charged; unassociated flagged best-effort | `resources/eip.py` |
| 39 | `get_trend` per-bucket provenance (deleted dead `if False` branch) | `aws/cost_explorer.py` |
| 40,47 | Forecast metric guard raises on unsupported usage metrics | `aws/cost_explorer.py` |
| 48 | CE filter Values arrays capped at 200 (CE hard limit) | `core/filters.py` |

## Tests

- `test_deps_ce_client` updated for new no-cache contract (each call → fresh client).
- Full suite: **110 passed**.
