# aws_cost_ultra — Bug Audit + Cost/Perf Redesign

**Date:** 2026-05-20
**Author:** brainstorming session
**Status:** Draft — awaiting user approval

---

## 1. The actual problem (with numbers)

> Running this tool costs ~$1 in Cost Explorer fees. For a $10–20/month workload that's a 5–10% tax just to look at the dashboard.

CE pricing recap:
- `GetCostAndUsage`, `GetCostForecast`, `GetDimensionValues`, etc. = **$0.01/request**
- Each `NextPageToken` page is a separate billed request
- `GetCostAndUsageWithResources` adds **$0.00001 per UsageRecord** on top of the $0.01

### Where the $1 actually comes from

Per the audit, a single fresh visit to every page of the tool costs:

| Surface | Fresh CE calls | $ at $0.01/call |
|---|---|---|
| Prewarm (per profile, per server start) | 9 | $0.09 |
| `/api/cost/summary` | 4 (total, total_prev, by_service, forecast) | $0.04 |
| `/api/cost/services` | 2 | $0.02 |
| `/api/cost/trend` | 1 | $0.01 |
| `/api/cost/trend-table` (HTML — not cached, bug) | 1 every reload | $0.01 |
| `/api/resources/data` (enumerate_all) | 2–4 + EC2 RESOURCE_ID surcharge | $0.02 – $0.60+ |
| `/api/export/run` | 5–7 | $0.05 – $0.07 |
| `/api/audit/summary` | 0 (uses Budgets/describe) | $0.00 |

**Reality of a $1 session** = ~3 profiles × 9 prewarm + 4 page tabs × multiple period switches + a couple of exports + cache flushes during dev. The EC2 `RESOURCE_ID` query alone, on an account with thousands of instance-hours of UsageRecords, can hit **$0.50+ in a single click** because of the `$0.00001 × records` surcharge.

The architecture treats CE as a free database. **It's not** — it's a metered, expensive, slow API. Almost every "$0.01" is also avoidable.

---

## 2. Backend bugs and smells (confirmed)

### High-impact

1. **Prewarm fires 9 CE calls per profile every server restart** (`web/prewarm.py:41-91`). With 3 profiles = 27 CE calls = $0.27 just to boot. And it re-runs `get_cost_by_service(prev_window)` twice (lines 43 + 69). It also calls `enumerate_all` inside `build_resources_ctx` (line 108) which fires another CE call + EC2 RESOURCE_ID query per profile. Default-off (`ACU_ENABLE_PREWARM=0`), but the moment it's on, this is the dominant cost source.
2. **`/api/cost/trend-table` (HTML) is not cached**, but `/trend-table/data` (JSON) is (`web/routes/cost.py:216-237` vs `238+`). Reloading the HTML page burns $0.01 every time.
3. **`get_cost_by_service` is fetched twice per dashboard load** — once for summary (`cost.py:53`) and again for the services tab (`cost.py:90-91`). Same window, same filter — the second call could be a frontend slice of the first.
4. **EC2 RESOURCE_ID attribution surcharge is silent** (`aws/ce_attribution.py:56`). The Provenance object captures the source but never warns the user that they just paid for N UsageRecords. On a fat account this single call dominates the bill.
5. **No pagination cost awareness**: `cost_explorer.py:340-348` paginates with `NextPageToken` in a loop, each page billed at $0.01. Long windows + fine grouping silently 5×–10× the cost.
6. **`CostExplorerClient` documented as not thread-safe** (`cost_explorer.py:65`) but shared across ThreadPoolExecutor workers in `cost.py:49`, `resources/runner.py:134`, and the prewarm pool. Today's boto3 is mostly safe in practice but the comment exists for a reason; per-thread clients eliminate the doubt.
7. **`/api/resources/top/data` returns empty + `warming=true` on cold start** (`resources_api.py:119-130`). UX dead zone for 30s+ on large accounts.
8. **Double `get_total_cost` in `_build_summary_ctx`** (`cost.py:51,55`) when `period != "mtd"` — calls for `window` and again for `mtd_window`. Could memoize or pass both.

### Medium

9. **Bare `except Exception: pass` swallowing real errors** in `audit/idle.py`, `audit/budgets.py`, `aws/ce_attribution.py`, `resources/ec2.py`. At minimum log `type(exc).__name__`.
10. **Hardcoded fallback pricing rates in `pricing.py:32-74`** (described as "as of 2024-2026"). Pricing API failures silently use stale numbers. Should at least log the fallback path with the SKU.
11. **Unused CE wrappers** still take up surface and audit time: `get_cost_by_usage_type`, `get_cost_by_linked_account`, `get_cost_by_tag`. Delete or wire up.
12. **`AttributedResource.variance_from_ground_truth_pct`** computed but never surfaced in UI — drift warnings would actually be valuable.
13. **No request-scoped timing/observability**. No idea which CE call is slow or how many fired during a request. Add structured log + duration headers.

### Low

14. `friendly_error()` in `context.py:57-62` does a `type(exc).__name__` lookup with no fallback.
15. CE response → CostValue → cache_set → render is fine, but the cache key format `f"summary:{profile}:{period}"` is non-uniform — `services:{profile}:{period}:{limit}` includes `limit` but the partial that consumes it ignores it. Easy to corrupt cache by adding a query param.

### Tests gap

- Zero integration tests for routes.
- Zero tests for cache TTL/SWR.
- Zero tests for concurrent requests.
- Zero frontend tests.

---

## 3. Frontend bugs and smells (confirmed)

### Race conditions / correctness

1. **No `AbortController` on `useAsyncData`** (`App.jsx:29-39`). Rapid period/profile changes leave older requests in flight; last-write-wins on response order, not request order. Easy to display stale data.
2. **No debounce on filter changes** (`ResourcesPage`, `App.jsx:217`). Every keystroke / pill click = a new backend fetch.
3. **Two calls for what is one dataset** in `ResourcesPage` (`App.jsx:217-218`) — reconciliation stats and the row data are both `api.resources()` against the same endpoint.
4. **`api.context()` called with hardcoded `("default", "mtd")`** at mount (`App.jsx:352-358`) regardless of the actual selected profile.
5. **No retry on transient failure**. Budgets 404 = empty card, no recovery affordance.

### Bundle / perf

6. **610 KB single bundle, no code-splitting**. Recharts (~180 KB) loads on every page even when no chart is rendered. Lazy-load per route.
7. **Unvirtualized resource tables** — 100s of rows render synchronously.
8. **Charts unmount/remount on every parent re-render** instead of memoized.
9. **No persistence across reloads** — no `localStorage` cache, no SWR.

### UX

10. **"Pre-credit" badge looks like a control, isn't** (`App.jsx:74`).
11. **Mobile layout broken** for split tables (`styles.css:33-42`).
12. **No skeleton loaders** — 4 separate spinners pop in/out at different times → layout jitter.
13. **A11y**: sidebar items are `<div onClick>`, no role/tabindex; chart legend has no keyboard focus.
14. **No drill-down breadcrumbs**; click KPI → services page with no "back from dashboard" trail.
15. **Hardcoded API base** vs `vite.config.js base: "/app/"` — only the proxy makes dev work; prod is fragile.

### Cleanup

16. `static/js/app.js` and `templates/dashboard.html` are the legacy vanilla stack, duplicating logic.
17. `AWS Costing Dashboard/` (prototype with dark mode, theme tokens) is orphaned but its tokens are imported by the live CSS.
18. `puppeteer` in `package.json` but unused at runtime.

---

## 4. Architecture redesign — three options

The frame: **Cost Explorer should be the source of last resort, not the first.** Once you accept that, the design picks itself.

### Option A — Cache-first, minimal change (1–2 weeks)

Keep Python/FastAPI. Do not add new infrastructure. Just stop paying $0.01 to re-ask for data you already have.

- **Persistent SQLite cache** for every CE response, keyed by `(profile, account_id, metric, granularity, group_by, filter_hash, time_window)`. TTL by recency: today's data 15 min, yesterday 24 h, anything ≥7 days old → permanent.
- **One canonical CE call** per (profile, period): `GetCostAndUsage` with `Granularity=DAILY`, `GroupBy=SERVICE`, no resource-level. The summary, services, and trend pages all slice from this one cached blob in the frontend / a thin Python layer.
- **Kill the prewarm fan-out**. Replace with a single nightly refresh job (1 call/profile/day).
- **Resource attribution → Pricing API + describe + CloudWatch**, never CE. Drop EC2 RESOURCE_ID grouping entirely (or gate behind an explicit "I accept the cost" toggle that shows the estimated charge before running).
- Fix the trend-table caching bug.
- Add per-request CE-call counter + estimated-$ header (`X-CE-Calls-Spent: 0.02`). Surface in the UI footer so the user sees what they paid.

**Cost after**: ~1 CE call per profile per day = **$0.30/month for 1 profile, $0.90/month for 3** (vs ~$5–10 today). 90%+ reduction without changing language or adding services.

### Option B — CUR + DuckDB local warehouse (2–3 weeks)

Use AWS's free bulk export instead of the metered API.

- **One-time setup** (Terraform/SAM): enable Cost and Usage Report 2.0 (or Data Exports FOCUS view), daily delivery to an S3 bucket in the user's account.
- **Background ingestor**: pulls new CUR partitions daily, loads into local **DuckDB** file (`~/.cache/aws_cost_ultra/cur.duckdb`). DuckDB reads Parquet directly, no Athena cost.
- **All dashboard queries are local SQL.** $0 per query, sub-100ms latency, full resource-level data forever.
- CE is used only for "today's intraday" delta (CUR is up to 24h stale) — one DAILY call/refresh, optional.
- Resource attribution becomes a trivial DuckDB query (`SELECT line_item_resource_id, SUM(unblended_cost) ... GROUP BY ...`), no Pricing-API guessing.
- Frontend stays the same; backend swaps the CE client for a `CurStore` with the same interface.

**Cost after**: CUR delivery is free; S3 storage for typical CUR is **$0.01–$0.10/month**; CE bill **$0/month** in steady state.

**Tradeoffs**: 24h freshness for resource-level; one-time S3+CUR setup; ingestor needs to be reliable. Best fit for users who run the tool more than once a week.

### Option C — Same as B, but rewrite the hot path in Go (3–4 weeks)

Only worth it if you actually want a single-binary distribution or sub-second cold starts.

- Same DuckDB warehouse.
- Replace Python web + ingestor with Go: `chi` for routes, `aws-sdk-go-v2` for AWS, `marcboeker/go-duckdb` for queries, embed the React build via `embed.FS`.
- 5–10× faster cold start; 3–5× lower memory; single static binary.
- **Doesn't reduce CE calls** — that's purely architectural; language doesn't matter.
- Keep Python for the CLI / one-off scripts where Python's ergonomics win.

**Recommendation: don't do C yet.** The bottleneck is the CE API, not Python. A rewrite is a distraction until B is in place. Revisit once the tool is shipping to other users and you want a single binary.

---

## 5. Recommendation

Do **A first** as a 1-week sprint — it's almost pure cleanup and immediately drops the bill by ~10×. Then **B** as the strategic move — it makes the tool effectively free to run at any scale and unlocks resource-level analysis that CE either can't do or charges through the nose for. Defer **C** indefinitely.

### Why not just CUR?
Because CUR has a 24h ingest latency and a one-time setup the user may not want today. A still gives an immediate win. B without A still works, but during the 2–3 weeks of CUR setup you're paying the old bill.

### Why not "rewrite in Rust/Go for speed"?
Because there is no perf bottleneck in the Python code. Every measured slow request is **`boto3.client('ce').get_cost_and_usage(...)`** taking 600–2000 ms over the wire. The transform is microseconds. Switching language saves nothing on that. The right perf optimization is **not making the call at all** (cache or CUR).

---

## 6. Concrete fix list (in priority order)

### Week 1 — Option A: stop bleeding

| # | Item | File(s) | Win |
|---|---|---|---|
| 1 | Persistent SQLite cache replacing the JSON dict | `web/deps.py` | survives restarts, queryable, supports composite keys |
| 2 | Single canonical daily CE call: `(DAILY × SERVICE)` per profile, cached forever for closed days | new `aws/cost_store.py` | summary/services/trend all derive from one blob |
| 3 | Frontend slicing: `/api/cost/services` becomes a frontend pure-function over the cached blob | `frontend/src/api.js`, `App.jsx` | -1 CE call/load |
| 4 | Cache `/api/cost/trend-table` HTML route | `web/routes/cost.py:216` | -1 CE call/reload |
| 5 | Dedupe prewarm: 4 calls max per profile, gate behind explicit env var | `web/prewarm.py` | -5 calls × profiles per restart |
| 6 | Kill EC2 `RESOURCE_ID` CE path; switch to `describe_instances` + Pricing API + CloudWatch hours | `resources/ec2.py`, `aws/ce_attribution.py` | -$0.05 to -$1.00 per resources page load |
| 7 | Add `X-CE-Calls-Spent` response header + UI footer counter | `web/routes/*.py`, `App.jsx` | the user sees the bill in real time |
| 8 | `AbortController` + per-page request key in `useAsyncData` | `frontend/src/App.jsx:29-39` | no more stale renders |
| 9 | Debounce filter changes (300ms) | `App.jsx:217` | -50% redundant fetches when filtering |
| 10 | Replace bare `except Exception: pass` with `log.warning(..., exc_info=True)` | grep across `aws_cost_ultra/` | actually debuggable |
| 11 | Per-thread `CostExplorerClient` instances or a `threading.local` factory | `web/deps.py`, `cost_explorer.py:65` | doc'd risk goes to zero |
| 12 | Delete `static/js/app.js`, `templates/dashboard.html`, `AWS Costing Dashboard/` (after copying token CSS into `frontend/src/`) | various | -1500 lines of dead code |

### Weeks 2–3 — Option B: CUR + DuckDB

| # | Item | Notes |
|---|---|---|
| 13 | Add `iac/cur.tf` (Terraform) creating an S3 bucket + CUR 2.0 / Data Exports FOCUS report, daily Parquet, hourly granularity | gated behind a `--setup-cur` CLI subcommand |
| 14 | `aws_cost_ultra/cur/ingestor.py`: incremental S3 list → download new Parquet partitions → `DuckDB COPY FROM ...` | runs as APScheduler job or `cron` |
| 15 | `aws_cost_ultra/cur/store.py`: thin query layer mirroring CostExplorerClient's interface (`get_total_cost`, `get_cost_by_service`, `get_trend`, `attribute_resources`) | drop-in for the CE client |
| 16 | `CostSource` strategy: tries `CurStore` first; falls back to `CostExplorerClient` for today's intraday + when CUR not yet configured | route handlers don't change |
| 17 | New `/api/setup/cur` flow in the UI: detects whether CUR exists, walks the user through enabling it, shows ingestor progress | one-time UX |
| 18 | Resource-level attribution becomes a single DuckDB query joining `line_items` × `bills` × `resource_tags` | replaces the entire `resources/` describe-and-stitch logic |
| 19 | Optional Athena fallback for users who don't want a local cache | nice-to-have |

### Later — UX / perf polish

| # | Item |
|---|---|
| 20 | Code-split Recharts per route (lazy import) — bundle drops to ~250 KB initial |
| 21 | Skeleton loaders per section (no spinner pop-in) |
| 22 | Virtualize resource tables (react-window) |
| 23 | Mobile-responsive tables (CSS grid, horizontal scroll containers) |
| 24 | A11y pass: semantic roles on sidebar, focus management on charts |
| 25 | localStorage SWR for `profile`/`period`/`page` selection |
| 26 | Drift warning: surface `AttributedResource.variance_from_ground_truth_pct` in resources page |
| 27 | Inline cost basis toggle (real control, not a label) |

---

## 7. Cost projection (steady state)

Assume: 1 profile, 30 dashboard visits/month, 2 exports/month, 1 server restart.

| Scenario | CE calls/mo | Cost/mo |
|---|---|---|
| Today | ~150–300 (+ resource surcharges) | $1.50 – $3+ |
| After A | ~30–40 | $0.30 – $0.40 |
| After A+B | ~5–10 (only today's intraday) | $0.05 – $0.10 |

For a $20/mo workload, the tool tax drops from ~10–15% to ~0.5%. That's the goal.

---

## 8. Open questions for the user

1. **Are you OK with 24h staleness for resource-level cost?** If yes, B is unambiguous. If no, A is the stopping point.
2. **Single-account or multi-account?** If multi (org payer), CUR is even more compelling — one CUR covers all linked accounts and removes the per-profile fan-out.
3. **Do you actually want a single-binary distribution** (Option C) or is "run `acu` from venv" fine? This decides whether Go is ever on the table.
4. **Should the "I'm about to pay $X" gate live in the UI** (a confirmation modal before any CE call > $0.05), or just as a passive header?
5. **CUR setup**: are you OK with me writing Terraform that lives in this repo, or do you want the user to set it up out-of-band and just point at the bucket?

---

## 9. What I'm explicitly NOT proposing

- Rewriting the whole thing in Rust/Go right now. The bottleneck is not the language.
- Replacing FastAPI/React. Both are fine for this scale.
- Adding Redis/Postgres/Kafka. SQLite + DuckDB are enough for a single-user tool.
- Touching the CLI / exporters until A is done — they ride on the same CE layer and will inherit the win.
