# Cost Explorer — Definitive Audit (verified)

_54 findings, each independently re-verified against the code. **48 confirmed, 3 false-positive, 3 uncertain.** Severity = post-verification (calibrated for the localhost/no-auth deployment model)._


## 🔴 CRITICAL — confirmed (1)

### 1. EC2 per-region CE query has no REGION filter, so the same account-wide EC2 cost is counted once per region
`aws_cost_ultra/resources/ec2.py:42-58, 72-116` · data-accuracy

**Why it's real:** The mechanism holds against the real code. runner.py:84 creates one CE client ce_raw = session.client("ce", region_name="us-east-1") and passes it to attribute_ec2_account once (runner.py:108-110) with the full regions list and spec. attribute_ec2_account (ec2.py:53-56) loops over every region and calls _attribute_from_usage_type with that same ce_raw client and same spec each time. Inside _attribute_from_usage_type the CE filter (ec2.py:72-79) is built from base_filter = build_ce_filter(spec) AND {Dimensions:…

**Fix:** Correct: add a REGION dimension to the per-iteration CE filter (And SERVICE with {Dimensions:{Key:'REGION',Values:[region]}}), or query CE once with GroupBy [USAGE_TYPE, REGION] and partition by region before splitting across that region's instances.


## 🟠 HIGH — confirmed (7)

### 2. Reflected XSS: profile/period query params raw-interpolated into inline <script> in trend-chart
`aws_cost_ultra/web/routes/cost.py:362-370` · vulnerability

**Why it's real:** The cited code is exactly as described. api_trend_chart (cost.py:362-370) takes profile and period as untyped FastAPI Query params (default str, no constraint/regex/enum), builds data_url via f-string at line 363, then embeds data_url unescaped inside an inline <script> body at line 366: fetch("{data_url}"). The result is returned via HTMLResponse(html) at line 370 with no escaping. I verified there is NO validation anywhere in the path: period_to_window (deps.py:170-191) does mapping.get(period, current_month)…

**Fix:** Proposed fix is correct: build the URL with urllib.parse.urlencode and emit it into a data-* attribute on the canvas read by static JS (charts.js already has the trend-canvas pattern at charts.js:169), never interpolating request input into a <script> body; additionally validate profile against…

### 3. S3 attribution makes per-bucket get_bucket_location + get_bucket_tagging + CloudWatch calls for ALL buckets in EVERY region
`aws_cost_ultra/resources/s3.py:20-99` · scale

**Why it's real:** The mechanism holds exactly as described. In runner.py:135 the S3 attribution is dispatched through `_fanout_regions(attribute_s3, ce_total("S3"))`, which (runner.py:112-124) submits one call to `attribute_s3` per region in `regions` (from `accessible_regions`, session.py:142-152, which returns all opted-in regions — up to ~20+). Each invocation of `attribute_s3` (s3.py:27-29) calls the GLOBAL `list_buckets()`, returning every bucket in the account every time. Then s3.py:37-45 loops over ALL buckets calling…

**Fix:** Fix is correct in substance: list_buckets once globally, resolve+cache each bucket's region once, group by region before dispatch. Minor inaccuracy: Lambda is NOT bounded (lambda_fn.py:56 is a plain sequential loop) so "as already done for Lambda/DynamoDB" overstates existing bounding; still,…

### 4. Month-end forecast drops the remainder of today (forecast window starts tomorrow midnight)
`aws_cost_ultra/core/time_windows.py:49-62` · data-accuracy

**Why it's real:** The mechanism holds exactly as described, and the date-granularity of CE queries makes it slightly worse. In cost.py:52-99, fcast_window = remainder_of_current_month() and ctx['forecast'] = mtd_amount + forecast_cv.amount_usd, where mtd_amount comes from current_month() (time_windows.py:26-30, start=1st-midnight, end=now). remainder_of_current_month() (time_windows.py:56-62) sets start=(now+1day).replace(hour=0,...) = tomorrow midnight UTC. So the two windows are MTD=[month-1st 00:00, now] and forecast=[tomorrow…

**Fix:** Fix is directionally correct but must respect CE's date granularity: forecast Start should be today's date (the same date MTD's End covers, since MTD excludes today), i.e. start = _utc_today_midnight(), not tomorrow. CE's get_cost_forecast allows Start = today, so the partial day is forecast rather…

### 5. Previous-period comparison uses a calendar month against a non-month window (length mismatch)
`aws_cost_ultra/web/routes/cost.py:51` · data-accuracy

**Why it's real:** The code matches the finding exactly. In cost.py:50-51, window = period_to_window(period) and prev_window = period_to_window("last_month") if period in ("mtd","3m","30d") else period_to_window("3m"). In deps.py:178-189 the mapping confirms: "3m" -> last_n_days(90), "30d" -> last_n_days(30), "mtd" -> current_month(), "last_month" -> last_month(). In time_windows.py: last_n_days(n) spans n days ending at now (line 20-23); last_month() is a full calendar month [1st, 1st-of-next) i.e. ~28-31 days (line 33-39);…

**Fix:** Proposed fix is correct: derive prev_window with the same length/alignment as the current window (preceding N-day window for rolling periods; prior calendar month vs full last_month only when current is a full month). Have period_to_window return the window length so the comparison window can…

### 6. Services-page prev-period map mismatched for 3m and uses calendar month for 30d
`aws_cost_ultra/web/routes/cost.py:117` · data-accuracy

**Why it's real:** Read the real code. cost.py:117 sets prev_window = period_to_window("last_month") if period in ("mtd","30d") else period_to_window("3m"). deps.py:178-191 maps both "3m" and the else-branch to last_n_days(90), and the current window for period="3m" is also period_to_window("3m")=last_n_days(90) (cost.py:116). time_windows.last_n_days (lines 20-23) is a pure function of now/today, so the two calls produce the same rolling 90-day window covering the same UTC days. cost_store.by_service() (lines 48-52) aggregates…

**Fix:** Correct: compute prev_window as the immediately preceding window of the SAME length/alignment as the current period (e.g. shift the current window back by its own duration) and share one helper with _build_summary_ctx; current ad hoc mapping makes 3m deltas always 0% and 30d/6m/12m deltas…

### 7. Trend table/data endpoints ignore the configured cost basis (no pre_credit_gross spec)
`aws_cost_ultra/web/routes/cost.py:390 and 417` · data-accuracy

**Why it's real:** The mechanism holds exactly as described. In aws_cost_ultra/web/routes/cost.py, api_trend_data (line 349) calls ce.get_trend(window, granularity=gran, spec=spec) with spec=pre_credit_gross() (line 347), which sets excluded_record_types=("Credit","Refund","Upfront"). By contrast api_trend_table (line 390) and api_trend_table_data (line 417) both call ce.get_trend(window, granularity=gran) with NO spec argument. get_trend (cost_explorer.py:217-220) declares spec: Optional[CostFilterSpec]=None and then executes `spec…

**Fix:** Correct: add spec=pre_credit_gross() to get_trend at cost.py:390 and 417, and set ctx["cost_basis_label"] in both trend-table contexts to match the chart/summary basis.

### 8. Closed-window classification uses end <= today, treating yesterday's still-finalizing data as immutable _(was medium)_
`aws_cost_ultra/aws/cost_store.py:100-105` · data-accuracy

**Why it's real:** The mechanism holds, and is in fact broader than the finding describes. _is_closed_window (cost_store.py:100-105) returns True when end <= dt.date.today(). When True, get_matrix caches the matrix for 30 days with SWR=0 (cost_store.py:129-130). SqliteCache.get (sqlite_cache.py:67-78) serves the value for the entire ttl regardless of staleness, and get_matrix is never called with force=True from any route (deps/cost.py grep confirms force defaults to False everywhere; only a manual cache_bust endpoint exists).  The…

**Fix:** Correct: require end <= today - N days (e.g. 3) before treating a window as closed, AND use datetime.now(timezone.utc).date() for 'today'; otherwise apply the open-window TTL/SWR. This also fixes the dominant current-month/trailing-window freeze, not just month-end true-ups.


## 🟡 MEDIUM — confirmed (26)

### 9. SWR cache stores full unbounded payloads in localStorage with no per-entry size cap or eviction _(was high)_
`frontend/src/lib/swrCache.js:22-28` · scale

**Why it's real:** The core mechanism is real and verified against the code. writeSwr (frontend/src/lib/swrCache.js:22-28) calls localStorage.setItem with JSON.stringify of the full server value, no size cap, and an empty catch {} (lines 25-27) that silently swallows QuotaExceededError. The caller in api.js:34 writes any non-warming response: writeSwr(key, data). The resources detail endpoint /api/resources/data is fetched with limit=0 (App.jsx:372-375 -> api.resources(profile, period, "all", debouncedService, 0)) and the backend…

**Fix:** Proposed fix is correct in direction: add a per-entry size cap (skip caching payloads over ~256KB) and on QuotaExceededError delete oldest acu:swr: keys by ts then retry; better, do not SWR-cache the unbounded resources/composition responses at all (cache bounded summaries only). IndexedDB is…

### 10. Resource and service tables render every row with no virtualization, freezing the UI at scale _(was high)_
`frontend/src/App.jsx:419-434` · scale

**Why it's real:** The mechanism is real and verified end-to-end. ResourcesPage requests resources with limit=0 (App.jsx:373) and the backend treats limit=0 as "no cap" — api_resources_data/api_resources only truncate when `limit > 0` (resources_api.py:125-126), so the full attributed resource set is returned. The frontend then maps over (d.rows || []) emitting one <tr> per resource with no windowing/virtualization, each row containing a clipboard-bound copy button (App.jsx:419-434). For an account with thousands of attributed…

**Fix:** Proposed fix is correct: virtualize (react-window) or paginate the resource/service tables and request a bounded server-side top-N with explicit "load more" instead of limit=0; cap or virtualize the "Show all usage types" expansion. Resource table is the priority.

### 11. Resources fetched with limit=0 pulls the entire account resource list to the browser
`frontend/src/App.jsx:372-375` · scale

**Why it's real:** The mechanism holds, though the finding's server citation is slightly mislabeled. The finding cites cost.py:144 (effective_limit = limit if limit > 0 else None), which is actually the /cost/services endpoint, not resources. But the real resources endpoint at aws_cost_ultra/web/routes/resources_api.py:131-155 (/api/resources/data) exhibits the identical pattern: rows are only sliced when limit > 0 (line 151-152: `if limit > 0: rows = sorted(...)[:limit]`). With no slice, it returns the entire ctx['rows'] built in…

**Fix:** Proposed fix is correct: send an explicit server-side top-N limit from ResourcesPage (e.g. limit=200) plus a paged 'load more' control, keeping the full-list path off the client; also consider not SWR-caching very large resource payloads.

### 12. Arbitrary directory creation and file write via unvalidated output_dir query param _(was high)_
`aws_cost_ultra/web/routes/export_api.py:101-119` · vulnerability

**Why it's real:** The mechanism is fully real and unguarded. In export_api.py the POST /api/export/run handler declares output_dir as a raw query param with default "./exports" (line 106), performs no validation, and passes it directly into ScheduledExportConfig(output_dir=output_dir, formats=[fmt]) (line 110). run_scheduled_export then executes Path(config.output_dir).mkdir(parents=True, exist_ok=True) (scheduler.py:52-53) and writes cost_report_<ts>.{json,csv,pdf} via export_json/export_csv/export_pdf into that directory.…

**Fix:** Proposed fix is correct: drop output_dir from the web API (mirror /export/download's forced tempdir), or confine via Path(base, output_dir).resolve() + is_relative_to(base.resolve()) and reject absolute/traversal paths; add auth/CSRF protection to the export routes.

### 13. Unvalidated profile query param selects arbitrary local AWS profile (cross-account selection / credential_process execution)
`aws_cost_ultra/web/deps.py:106-112` · vulnerability

**Why it's real:** The mechanism holds end-to-end. deps.py:106-112 get_session(profile: str = Query("default")) maps "default"/empty -> None else passes the raw string to make_session(profile=p). session.py:75-83 make_session puts that into boto3.Session(profile_name=profile) with zero validation against list_profiles(). The data-path route handlers in cost.py (api_cost_summary -> _build_summary_ctx, _build_services_ctx, composition, trend, etc.) call get_session(profile) positionally with the raw query param (e.g. cost.py:42, 113,…

**Fix:** Fix is correct: validate profile against list_profiles() (+ "default") in get_session and return 400 instead of silently falling back; also add auth/origin checks since all endpoints are unauthenticated GETs (CSRF-exploitable even on localhost).

### 14. No authentication/authorization on any route; all cost/resource/audit endpoints spend AWS money unauthenticated _(was high)_
`aws_cost_ultra/web/app.py:24-39` · vulnerability

**Why it's real:** The mechanism is real. app.py:24-39 builds FastAPI() with no dependencies=[...], no Depends/Security gate, and registers all five routers. The only middleware is CECountingMiddleware (middleware.py:44-54), which merely counts CE calls/records and writes X-CE-* headers — it performs no authentication. A grep across the entire aws_cost_ultra/web/ tree returns zero auth/token/HTTPBearer/Depends-security/rate-limit hits; the only "auth" matches are unrelated error-message strings in context.py. The cost-incurring…

**Fix:** Proposed fix is correct: add a shared-secret token via Depends/Security on the AWS-calling routers (or strictly enforce + document loopback bind), plus rate limiting and a profile allow-list; add CSRF/Origin checks since GETs spend money. Even a localhost tool should require a token to defend…

### 15. Cross-site request can trigger state/cost-affecting POSTs (cache clear, export run) — no CSRF protection
`aws_cost_ultra/web/app.py:31-39` · vulnerability

**Why it's real:** Read the actual code. app.py (lines 24-39) installs only CECountingMiddleware (middleware.py: a request-counter, not security-related). There is no CORSMiddleware, no authentication dependency, and no CSRF/Origin/Referer/SameSite check anywhere in the app or routers. Two state/cost-affecting POST routes exist and are unauthenticated: export_api.py:101 `POST /api/export/run` calls `_build_report` (export_api.py:41-98), which fires 3 parallel CE calls (get_matrix, get_trend, attribute_resources across regions) plus…

**Fix:** Proposed fix is correct: add Origin/Referer allow-list check (or anti-CSRF token) on all POST routes plus an auth token; keep loopback binding and add a Host/DNS-rebinding allow-list. Do not rely on CORS for protection.

### 16. Full resource/service contexts (entire row sets) serialized to JSON / re-sorted per request — unbounded memory and O(n log n) per call for huge accounts
`aws_cost_ultra/web/routes/resources_api.py:75-100, 120-155, 201-206` · scale

**Why it's real:** The core mechanism holds. build_resources_ctx materializes the full per-resource list into ctx["rows"]: the CUR path (cur/store.py:94-131) emits one dict per resource_id grouped, and the describe path (resources/runner.py:64+, via enumerate_all -> r.to_dict()) emits one AttributedResource per discovered resource. So ctx["rows"] scales with total account resource count. There is NO server-side cap when limit<=0: api_resources_data gates truncation behind `if limit > 0:` (resources_api.py:151) and the HTML…

**Fix:** Fix is directionally correct: enforce a hard server-side row cap even when limit<=0, store a pre-sorted/pre-truncated top-N plus aggregate totals + services_summary in cache instead of the full row list, and paginate/stream full exports. Note the bigger lever the finding understates: the SQLite…

### 17. Nested ThreadPoolExecutors multiply into 70+ concurrent threads, and each thread opens many boto3 clients/connections _(was high)_
`aws_cost_ultra/resources/runner.py:104-150` · concurrency

**Why it's real:** The nested-executor mechanism is real and matches the code. runner.py:104 sizes the outer pool min(16, max(len(regions)*2,4)) = 16 with ~20 regions. runner.py:112-124 defines _fanout_regions, which opens its OWN inner ThreadPoolExecutor sized min(12, len(regions)) = 12 with ~20 regions. Six services use it: RDS (127), EIP (129), ELB (131), Lambda (133), S3 (135), DynamoDB (137). Only 8 jobs total are submitted to the 16-slot outer pool (6 fan-outs + EC2 at 108 + EBS at 150), so all 6 fan-out jobs run truly…

**Fix:** Proposed fix is correct: flatten all (service, region) work units into one shared bounded ThreadPoolExecutor (cap ~16-24) instead of nesting a per-service inner pool; this caps total threads/connections regardless of region or service count.

### 18. CE-total rescaling factor can divide by a near-zero raw_sum, massively inflating per-resource cost _(was high)_
`aws_cost_ultra/resources/runner.py:164-189` · data-accuracy

**Why it's real:** The rescaling code is exactly as cited (runner.py:164-189): EBS/EIP use factor = other_pool/raw_sum, RDS/ELB use factor = ce_tot/raw_sum, guarded ONLY by `raw_sum > 0` with no clamp on factor magnitude, then multiplied onto every row. The output flows to the user-facing resources API (resources_api.py:72) and ce_total_by_service holds real Cost Explorer service totals (runner.py:89). So an unbounded factor multiplying nonzero rows while leaving zero-cost rows at 0 is a real, reachable misattribution.  The…

**Fix:** Proposed fix is directionally correct: skip/clamp rescaling when raw_sum is tiny relative to the pool (or cap factor) and surface variance as a drift warning; better still, distribute residual pool across zero-cost rows by size/hours instead of letting one nonzero row absorb it. Note the fix…

### 19. ELB attribution issues describe_target_health once per target group (N+1), unbounded under many TGs _(was high)_
`aws_cost_ultra/resources/elb.py:40-48` · scale

**Why it's real:** The mechanism holds exactly as described, and is in one respect worse. In aws_cost_ultra/resources/elb.py the code paginates describe_target_groups (line 40), and for every target group calls elbv2.describe_target_health(TargetGroupArn=tg[...]) serially on a single thread (line 43). There is no batching (the API supports none) and no cap on the number of TGs inspected. The call is nested inside `for lb_arn in tg.get("LoadBalancerArns", [])` (line 42), so a TG attached to multiple LBs triggers more than one…

**Fix:** Fix is correct in direction: catch throttling per-call (not around the whole loop) with retry/backoff (botocore adaptive retries), cap TGs inspected and resolve health only for cost-relevant LBs; also fix the redundant per-LB-ARN call so each TG is queried once.

### 20. EBS attribution runs strictly sequentially across all regions on a single thread
`aws_cost_ultra/resources/runner.py:139-150` · scale

**Why it's real:** The mechanism is exactly as described. In runner.py the six services RDS/EIP/ELB/Lambda/S3/DynamoDB are all submitted through _fanout_regions (lines 126-137), which fans each region out to an inner ThreadPoolExecutor of up to min(12, len(regions)) workers (line 114). EBS alone uses _ebs_all_regions (lines 139-150), a single outer-pool task that walks `for reg in regions` strictly sequentially. Within each region it calls live_instance_names(ts, reg) — a full describe_instances pagination over all non-terminated…

**Fix:** Correct: submit one per-region task to the shared pool that calls live_instance_names then attribute_ebs, mirroring _fanout_regions (which already passes a per-region frozen session); replace the sequential _ebs_all_regions loop.

### 21. live_instance_names is called for EBS and then describe_instances is paginated AGAIN for EC2 — duplicate full instance scans
`aws_cost_ultra/resources/ec2.py:121-147, 214-226` · scale

**Why it's real:** Both DescribeInstances scans are real and run in the same enumerate_all call over the same region set. In ec2.py, _attribute_from_usage_type paginates ec2.get_paginator("describe_instances").paginate() with no Filters (line 123) to build inst_by_key carrying full metadata including id and name (lines 138-139). live_instance_names independently paginates the same unfiltered describe_instances (line 218) to build only an id->name map (lines 223-224). In runner.py the EC2 job (attribute_ec2_account, submitted line…

**Fix:** Correct: build the per-region instance list once (id->name plus type/lifecycle/hours) and pass the id->name subset to attribute_ebs; reconcile that EC2 currently uses the shared session while EBS uses frozen per-region sessions.

### 22. All resources for the entire account are accumulated into one fully-buffered list, sorted, and returned/serialized
`aws_cost_ultra/resources/runner.py:102-221` · scale

**Why it's real:** The mechanism described is real and reading the code confirms there is no guard, top-N, or pagination anywhere in the build path. enumerate_all (runner.py:102-221) accumulates every AttributedResource from all services across all regions into per-service buckets (102, 159), then flattens them all into one list (216-219: `flat.extend(svc_rows)` over `buckets.values()` plus `other_rows`), sorts the whole thing (220), and returns the entire list (221). Each row's to_dict (base.py:41-54) embeds the full `attributes`…

**Fix:** Proposed fix is correct: cap at server-side top-N and aggregate the long tail into a synthetic "other resources" row (mirroring the existing other_rows aggregation), and/or paginate, so the full per-resource list is never materialized/serialized/cached for very large accounts. Severity stays…

### 23. DynamoDB describe_table called serially for every table (N+1) with no cap, blocking on large table counts
`aws_cost_ultra/resources/dynamodb.py:37-43` · scale

**Why it's real:** The cited code in aws_cost_ultra/resources/dynamodb.py behaves exactly as the finding describes. After listing all tables (lines 28-30, fully paginated, no cap), describe_table is called serially per table in a loop with no upper bound (lines 38-43). The should_collect_cw guard at line 49 (`window_days <= 45 and len(descs) <= 50`) only short-circuits the CloudWatch get_metric_statistics fan-out (lines 50-74); it does NOT gate the describe_table loop nor the per-table list_tags_of_resource call. The second loop…

**Fix:** Correct: bound the describe_table loop like CloudWatch, and gate list_tags_of_resource on should_collect_cw and cost>0 as Lambda already does (lambda_fn.py:97).

### 24. Broad bare-Exception swallowing in fan-out hides throttling and returns partial/zero attribution silently
`aws_cost_ultra/resources/runner.py:119-162` · data-accuracy

**Why it's real:** The mechanism holds against the real code. (1) Per-region fan-out catches bare Exception and only logs: runner.py:119-123 — `for fut in as_completed(futs): try: out.extend(fut.result()) except Exception: log.warning(...)`. A throttled region's rows are silently dropped. (2) Job-level collection sets buckets[label]=[] on any failure: runner.py:156-162. (3) Throttling realistically reaches these handlers. In attribute_rds, only `get_paginator().paginate()` is wrapped (rds.py:22-25), but the actual…

**Fix:** Proposed fix is correct: enable botocore adaptive retries (Config(retries={'mode':'adaptive','max_attempts':...})) on the resource clients and propagate a per-service partial/incomplete flag into the result so the UI warns; also skip RDS/ELB rescaling (or scale conservatively) when a region failed,…

### 25. Composition route drops negative line items, diverging the composition total from the service total
`aws_cost_ultra/web/routes/cost.py:287-298` · data-accuracy

**Why it's real:** The mechanism holds as described. In _build_services_composition_ctx (cost.py:269-319), line 288 `if amount <= 0: continue` drops every SERVICE×USAGE_TYPE group with non-positive cost, and the composition total is computed at line 303 as `"total": sum(buckets.values())` — i.e. only over the retained positive buckets. The Services page uses service_rows_from_groups (core/service_groups.py:56) whose total is `sum(g.value.amount_usd for g in groups)` over ALL groups with no sign filtering. Both views are built from…

**Fix:** Proposed fix is correct: keep negatives in the bucket math (drop the `amount <= 0` continue) so composition total reconciles with the service net; if hiding tiny rows is desired, filter usage_types on display only (e.g. abs(cost) threshold) without touching bucket accumulation.

### 26. Summary/services contexts are cached even when they contain an error
`aws_cost_ultra/web/routes/cost.py:165-167 and 197-198` · bug

**Why it's real:** The finding is accurate. In aws_cost_ultra/web/routes/cost.py, both _build_summary_ctx (lines 29-151) and _build_services_ctx (lines ~104-151) catch any exception and set ctx["error"] = friendly_error(exc) while leaving numeric fields at their None/empty defaults, then return the populated ctx dict. The handlers api_cost_summary (line 165-166) and api_cost_services (line 197-198) call cache_set(ckey, ctx) unconditionally — no error guard. The same unguarded pattern exists in the /data variants:…

**Fix:** Correct: wrap cache_set in `if ctx.get("error") is None:` in api_cost_summary, api_cost_summary_data, api_cost_services, and api_cost_services_data (mirroring line 332); or cache errors with a short ttl_seconds (e.g. 15-30s).

### 27. CE call counter does not propagate into ThreadPoolExecutor worker threads; X-CE-Calls-Spent severely undercounts _(was high)_
`aws_cost_ultra/web/middleware.py:32-41` · data-accuracy

**Why it's real:** The mechanism holds exactly as described. The CE counter is incremented only inside cost_explorer CE calls via get_current_counter().add(...) at cost_explorer.py:295 (get_forecast) and cost_explorer.py:392-395 (_get_cost_and_usage, the pagination loop that backs daily_service_matrix/get_matrix/get_total_cost). The counter lives in a module-level ContextVar with default=None (middleware.py:32). CECountingMiddleware.dispatch sets it on the async request task and reads back its own `counter` object into the headers…

**Fix:** Correct: wrap pool submissions with ctx = contextvars.copy_context(); pool.submit(ctx.run, fn, ...) (cost.py:59-66, :121-123, export_api.py:57-58). For _refresh_pool, attach an explicit counter or document that background refreshes are uncounted.

### 28. Per-thread CostExplorerClient dict is keyed by id(session) on freshly-created sessions → unbounded growth and id-reuse returning a wrong/dead client _(was high)_
`aws_cost_ultra/web/deps.py:118-136` · scale

**Why it's real:** The finding has two claims; one is real, the other is impossible.  CLAIM 1 — unbounded memory growth: CONFIRMED. get_ce_client (deps.py:127-136) keys the per-thread dict _ce_local.clients by id(session). get_session (deps.py:106-112) -> make_session (session.py:75-83) builds a NEW boto3.Session on every call and never caches it. Handlers invoke get_session(profile) per request (cost.py:42, 113, 272, 345, 387, 414; export_api.py:49, 169, 191; resources_api.py:58), so every request produces a distinct Session object…

**Fix:** Fix is partially right: bound/evict the cache and key by stable identity (profile/account) instead of id(session); but the id-reuse/wrong-account concern is moot since the client already pins its session — the only genuine need is eviction/LRU to stop the leak.

### 29. Closed-window TTL classification uses local date (date.today()) against UTC window end → 30-day caching of a still-open day, or never-closing near midnight
`aws_cost_ultra/aws/cost_store.py:100-105` · data-accuracy

**Why it's real:** The core mechanism is real and confirmed, though the finding's tz framing is partly inverted. cost_store.py:104-105 does `end = dt.date.fromisoformat(e); return end <= dt.date.today()`, where `e` is the UTC end-date string from TimeWindow.iso() (types.py:56-58, formatting the UTC `end` datetime). Open windows produced by time_windows.current_month()/last_n_days() set `end = datetime.now(tz=utc)` (time_windows.py:23,30), so their iso end-date == the current UTC date. These open windows are exactly what the routes…

**Fix:** Proposed fix (use UTC date) is necessary but INSUFFICIENT — `end <= today` with `<=` still mis-classifies an open window ending today. Use strict `<` against UTC today, or compare the window's end datetime to datetime.now(utc): closed only when end is strictly before the current UTC day.

### 30. SWR refresh pool (max_workers=4) saturates across many keys; deduped-but-still-serialized refreshes starve and never-refresh hot keys
`aws_cost_ultra/web/deps.py:70-99` · concurrency

**Why it's real:** The core mechanism is real. deps.py:70 creates a single module-global _refresh_pool = ThreadPoolExecutor(max_workers=4) shared across every SWR key. schedule_refresh (deps.py:75-99) dedupes per-key via _refreshing/_refresh_lock, then calls _refresh_pool.submit(_run) (deps.py:99) with no in-flight cap, no shedding, and no producer timeout. Python's stdlib ThreadPoolExecutor uses an unbounded SimpleQueue, so submit never blocks or rejects — excess tasks queue without bound. The producers are genuinely heavy:…

**Fix:** Proposed fix is correct in direction: add a per-producer timeout (e.g. wrap producer/Future with a deadline), bound/shed when an in-flight cap is reached instead of submitting unbounded, and reuse cached sessions/clients in producers to stop the id(session) growth; per-profile rate limiting is…

### 31. CE call counter undercounts: contextvar not propagated to ThreadPoolExecutor workers _(was high)_
`aws_cost_ultra/web/routes/cost.py:59-66` · concurrency

**Why it's real:** The mechanism is real and I reproduced its root cause empirically. (1) The request counter is a contextvars.ContextVar set only in CECountingMiddleware.dispatch (middleware.py:46-47), and the response headers are written from that same request-scoped `counter` local (middleware.py:52-53). (2) get_current_counter (middleware.py:35-41) returns _current.get(), and if it is None it fabricates a NEW throwaway counter and sets it in the *current* context only. (3) In _build_summary_ctx (cost.py:59-66) ALL four…

**Fix:** Proposed fix is correct: wrap each submit with ctx = contextvars.copy_context(); pool.submit(ctx.run, fn, ...) in both _build_summary_ctx and _build_services_ctx (or pass the counter explicitly into CostExplorerClient). copy_context() captures the handler thread's context, which anyio has already…

### 32. Per-thread CostExplorerClient cache keyed by id(session) leaks unboundedly and risks id reuse _(was high)_
`aws_cost_ultra/web/deps.py:118-136` · concurrency

**Why it's real:** The leak mechanism is real. get_ce_client caches a CostExplorerClient in a per-thread dict keyed by id(session) and never evicts (deps.py:127-135). get_session (deps.py:106-112) calls make_session, which constructs a brand-new boto3.Session() on every call (session.py:75-83), so every request yields a session with a distinct id(). Handlers call get_session(profile) then get_ce_client(session) directly per request (e.g. cost.py:42-43, 272-273, 345-346, 387-388, 414-415; resources_api.py:58/91; export_api.py:49-50).…

**Fix:** Fix is correct; simplest is option (c): drop the cache and construct CostExplorerClient per call (client creation is cheap vs the CE round-trip), or option (b) memoize one session per profile name so id() is stable and the dict stays bounded by profile count.

### 33. SqliteCache opens a new connection per operation and never closes it _(was high)_
`aws_cost_ultra/web/sqlite_cache.py:49-108` · scale

**Why it's real:** The core mechanism is real and verified both by reading code and empirically. SqliteCache._connect() (sqlite_cache.py:49-55) does sqlite3.connect() plus two PRAGMA statements on every call, and every cache op (get:68, get_swr:81/95, set:60, bust:103, _init_db:41/46) uses `with self._connect() as conn:`. The sqlite3 Connection context manager only commits/rolls back; it does NOT close the connection — confirmed correct. The cache is a module-level singleton (deps.py:32 `_cache = SqliteCache(...)`), reached on the…

**Fix:** Proposed fix is correct and worth doing: use a threading.local connection opened once per thread (run PRAGMAs at creation), or wrap each op in try/finally with conn.close(); this also removes per-op PRAGMA overhead.

### 34. Nested ThreadPoolExecutors + per-region session/client creation cause thread and connection explosion at region/service scale
`aws_cost_ultra/resources/runner.py:104-150` · scale

**Why it's real:** The core mechanism is real and verified in code. enumerate_all opens an outer ThreadPoolExecutor (max_workers=min(16, max(len(regions)*2,4)), runner.py:104) and submits up to 7 service jobs. Six of them (RDS, EIP, ELB, Lambda, S3, DynamoDB; runner.py:126-137) call _fanout_regions, which opens its OWN inner ThreadPoolExecutor(max_workers=min(12, len(regions)), runner.py:114) submitting one task per region. Each inner task calls _frozen_session(session, reg) which constructs a brand-new boto3.Session…

**Fix:** Proposed fix is correct and appropriate: flatten to one bounded executor over (region x service) tasks, build one frozen Session per region and reuse it/its clients across services, and cap total worker threads regardless of region count.


## ⚪ LOW — confirmed (13)

### 35. Clipboard write promise rejection is unhandled
`frontend/src/App.jsx:426` · bug

**Why it's real:** The cited code matches the finding exactly: frontend/src/App.jsx:426 is `onClick={() => navigator.clipboard?.writeText(r.resource_id)}`. The `?.` optional chaining only guards against `navigator.clipboard` being null/undefined (in which case the expression yields undefined and nothing happens silently). It does NOT guard the returned Promise. When `navigator.clipboard.writeText` exists but rejects — which is exactly what happens in an insecure context (plain HTTP on a LAN IP, a realistic deployment for a…

**Fix:** Proposed fix is correct: wrap in async try/catch (or attach .catch), show transient Copied/Copy failed state, and fall back to textarea+execCommand or select-on-click when Clipboard API is unavailable.

### 36. Inline-script chart fragment uses json.dumps for labels, which does not escape </script> or angle brackets _(was medium)_
`aws_cost_ultra/web/routes/cost.py:200-208` · vulnerability

**Why it's real:** The coding defect is real and matches the finding exactly. cost.py:200-208 (chart=1 branch of api_cost_services) builds an inline-script HTML fragment by embedding json.dumps(labels) and json.dumps(values) directly between <script>...</script>. I empirically confirmed json.dumps(['</script><img src=x onerror=alert(1)>']) emits the literal string ["</script><img src=x onerror=alert(1)>"] with the closing tag intact — json.dumps does NOT escape <, >, & or U+2028/U+2029. The fragment is delivered to the browser via…

**Fix:** Fix is correct: escape JSON for HTML-script context (.replace('<','<').replace('>','>').replace('&','&') plus U+2028/U+2029), or better use a JSON data island / the existing /services/data endpoint fetched by charts.js. Worth applying as defense-in-depth even though current data sources are…

### 37. friendly_error leaks raw AWS exception text (ARNs, account IDs, internal detail) to clients _(was medium)_
`aws_cost_ultra/web/context.py:75-83` · vulnerability

**Why it's real:** The cited code is exactly as described: friendly_error (context.py:75-83) matches a few literal substrings (NoCredentialsError/credentials, ExpiredToken/expired, AccessDenied/not authorized) and otherwise falls through to `return f"AWS error: {msg[:160]}"`, echoing the raw exception string. This string is genuinely returned to clients: ctx["error"] is rendered in templates as {{ error }} (cost_cards.html:10, resource_table.html:10, audit_findings.html:10, service_table.html, trend_table.html, budget_alerts.html)…

**Fix:** Fix is correct: drop msg[:160] echo, log full exc server-side (log already present in context.py), and return a fixed generic fallback like "AWS error — see server logs"; optionally map known botocore error codes to category strings.

### 38. EIP cost is computed from window length, not actual association state over the window — and idle rate applied to attached EIPs _(was medium)_
`aws_cost_ultra/resources/eip.py:26-37` · data-accuracy

**Why it's real:** The core mechanism is real. eip.py:28 computes window_hours = hours_between(window_start, effective_end) using the full window, and eip.py:37 charges cost = window_hours * idle_rate for EVERY address with no clamp to allocation/creation time. Every other resource enumerator does clamp: ec2.py:133, ebs.py:39, elb.py:59/96, rds.py:40 all call clamp_window(created/launch, window_start, window_end) before hours_between. EIP is the sole module that imports hours_between but NOT clamp_window (eip.py:11). So an EIP…

**Fix:** describe_addresses exposes no allocation timestamp, so a precise clamp is impossible; best fix is to flag EIP cost as best-effort/full-window in attributes and rename eip_idle_rate to eip_ipv4_rate. The proposed "clamp to allocation time" cannot be done without an extra data source (e.g. CloudTrail…

### 39. get_trend assigns the whole-window provenance to every per-bucket point (dead `if False` branch)
`aws_cost_ultra/aws/cost_explorer.py:240-256` · data-accuracy

**Why it's real:** The cited code at cost_explorer.py:240-243 builds bucket_window with the expression `TimeWindow(...) if False else window`. The `if False` condition is a compile-time-constant dead branch, so bucket_window is unconditionally bound to the caller's full `window`. That value is passed to _build_provenance (line 250-256), so every TimeSeriesPoint in a multi-bucket trend receives a Provenance whose `.window` is the entire trend window rather than the single bucket. Provenance.label() (provenance.py:48-51) renders…

**Fix:** Correct: parse period["TimePeriod"] Start/End as UTC-midnight datetimes into a per-bucket TimeWindow and pass it to _build_provenance, deleting the `if False` dead branch.

### 40. Forecast metric not validated/mapped for UsageQuantity and NormalizedUsageAmounts
`aws_cost_ultra/aws/cost_explorer.py:276-293` · data-accuracy

**Why it's real:** The mechanism holds as described. The forecast_metric translation dict (cost_explorer.py:276-282) maps only the five cost metrics. CostMetric.USAGE_QUANTITY ("UsageQuantity") and NORMALIZED_USAGE ("NormalizedUsageAmounts") (core/types.py:27-28) are absent, so .get(metric.value, metric.value) at line 282 falls through to the CamelCase value, which is not a valid get_cost_forecast Metric (CE expects SNAKE_CASE, and in fact does not support usage metrics for forecasting at all). The resulting boto3 error is caught by…

**Fix:** Prefer raising a clear ValueError for unsupported forecast metrics over mapping USAGE_QUANTITY/NORMALIZED_USAGE through — CE's get_cost_forecast does not support usage metrics, so the proposed mapping to 'USAGE_QUANTITY'/'NORMALIZED_USAGE_AMOUNT' would still fail at the API; an explicit guard…

### 41. Per-service usage_type list is unbounded — huge serialized JSON for high-cardinality services _(was medium)_
`aws_cost_ultra/web/routes/cost.py:300-314` · scale

**Why it's real:** The mechanism holds as described. In _build_services_composition_ctx, usage_by_svc accumulates one float per distinct USAGE_TYPE string per service across every region/bucket (cost.py:297-298). CE USAGE_TYPE is region-prefixed (APN1-BoxUsage:..., USE1-BoxUsage:...), so cardinality genuinely scales with regions x instance/usage types. The ctx comprehension (cost.py:300-314) emits a fully sorted usage_types list for every service with no cap and no limit query param. The entire ctx is json.dumps-serialized into…

**Fix:** Proposed fix is correct and appropriate: cap usage_types per service (e.g. top N by cost with an aggregated 'other' remainder) before serialization, or add a limit query param; keep the exact bucket totals untouched. Low priority unless serving large multi-region management accounts.

### 42. CostStore matrix cache stores and reloads the full sparse daily×service dict — unbounded cached blob _(was medium)_
`aws_cost_ultra/aws/cost_store.py:120-142` · scale

**Why it's real:** The described mechanism is real and exactly matches the code. get_matrix at aws_cost_ultra/aws/cost_store.py:134-142 serializes the full sparse cells dict as {f"{d}\x1f{s}": v} and stores it via cache_set; on a hit (lines 120-123) it rebuilds the entire dict by splitting every key on \x1f. The cache backend (sqlite_cache.py:57-58, 67-78) JSON-serializes the whole value and json.loads the whole blob on every read, so each cache hit does deserialize the full matrix even when callers only need…

**Fix:** Proposed fix is reasonable but low-priority: caching reduced by_service/trend rollups (or a compact columnar form) would shrink blobs and skip per-read dict rebuild; only worth doing if profiling shows cache deserialization is a real hotspot, which is unlikely at realistic service cardinality.

### 43. cache_bust() with empty prefix does a full-table LIKE '%' scan/delete with no index; bust of large cache blocks all writers under the global lock _(was medium)_
`aws_cost_ultra/web/sqlite_cache.py:102-108` · scale

**Why it's real:** The core mechanism is real and confirmed in the code. bust() (sqlite_cache.py:102-108) executes `DELETE FROM cache_entries WHERE key LIKE ?` binding `prefix + "%"`, inside `with self._lock, self._connect()`. deps.py:61-62 exposes cache_bust(prefix="") -> _cache.bust(prefix), and export_api.py:204 (POST /cache/clear) calls cache_bust() with no argument, so prefix="" yields `LIKE '%'`, which matches and deletes every row — an O(rows) full-table delete under the process-wide threading.Lock (sqlite_cache.py:35), in…

**Fix:** Fix is partially correct: use `DELETE FROM cache_entries` (or DROP/recreate) for full bust — that is the real win. Prefix-range-bound is a minor optimization. Better: bump an epoch counter for O(1) invalidation. But low priority given operator-only trigger and that reads don't contend on the lock.

### 44. Serializing very large matrices/resource lists to JSON in SQLite blows up memory and write cost; sparse-cell JSON encoding is O(days x services) _(was medium)_
`aws_cost_ultra/aws/cost_store.py:134-142` · scale

**Why it's real:** Every mechanical claim in the finding holds against the real code. (1) get_matrix serializes the entire sparse matrix to a JSON dict keyed by f"{d}\x1f{s}", one entry per non-empty cell (cost_store.py:137), and on a cache hit rebuilds tuple keys via {tuple(k.split("\x1f")): v ...} (cost_store.py:121). (2) daily_service_matrix uses DAILY granularity grouped by SERVICE (cost_explorer.py:115,124), and period_to_window exposes 90d/3m (90 days) and 6m/12m (trailing_months(6/12), up to ~365 days) (deps.py:181-188), so…

**Fix:** Fix direction is correct: store matrix columnar/per-day-aligned to cut key overhead and parse cost, and for resources persist rows in a queryable table (or cache pre-trimmed/top-N views) so service/limit filtering happens in SQL instead of loading the whole list. Avoid rebuilding tuple keys on…

### 45. Prewarm builds a CE client via get_ce_client on a transient session, seeding the leaking id(session) cache and running uncounted
`aws_cost_ultra/web/prewarm.py:26-39` · scale

**Why it's real:** The mechanics described are accurate. prewarm_background (prewarm.py:25) runs on a single daemon thread "acu-prewarm" (app.py:49-54) and loops serially over every profile. Each iteration calls get_session(profile) -> make_session(), which returns a fresh, never-pooled boto3.Session (deps.py:106-112, session.py:75-83). get_ce_client then keys its per-thread client dict by id(session) (deps.py:127-135), so the prewarm thread accumulates one CostExplorerClient entry per profile, and each loop-local session becomes…

**Fix:** Fixing get_ce_client to key by profile (not id(session)) also fixes the prewarm path; optionally bound prewarm concurrency / add backoff. Low priority since prewarm is opt-in and the thread dies after the loop so id-reuse is inert here.

### 46. Throwaway counter leaks across requests in reused pool worker threads _(was medium)_
`aws_cost_ultra/web/middleware.py:35-41` · concurrency

**Why it's real:** The described mechanism holds exactly. get_current_counter() (middleware.py:35-41) does the get/create/set fallback. The .add() calls live in cost_explorer.py:295 and :393-395, which execute inside pool.submit() worker threads (cost.py:59-66 for /summary, :121-123 for /services; also deps.py _refresh_pool at :70/:99). concurrent.futures.ThreadPoolExecutor.submit does NOT copy contextvars to the worker, so the worker's _current.get() returns the default None and takes the fallback branch, calling _current.set(c) in…

**Fix:** Proposed fix is correct and the right priority order: make the fallback side-effect-free (return CECallCounter() without _current.set()) to stop the orphan leak, and fix propagation by passing contextvars.copy_context().run at each pool.submit so worker .add()s reach the request counter (which also…

### 47. Forecast metric translation falls through to CamelCase for unmapped metrics, breaking get_cost_forecast
`aws_cost_ultra/aws/cost_explorer.py:276-282` · bug

**Why it's real:** The mechanism described is real and present in the code. The forecast metric translation at cost_explorer.py:276-282 is a dict with 5 keys (UnblendedCost, BlendedCost, AmortizedCost, NetUnblendedCost, NetAmortizedCost) accessed via `.get(metric.value, metric.value)`. The CostMetric enum (core/types.py:14-28) has 7 members; two of them — USAGE_QUANTITY ("UsageQuantity") and NORMALIZED_USAGE ("NormalizedUsageAmounts") — are NOT keys in the forecast map. For those, `.get` falls through to `metric.value`, passing the…

**Fix:** Fix is correct in spirit: replace the silent CamelCase passthrough with an explicit error/log for unmapped metrics, or derive SNAKE_CASE generically from the enum; restricting forecast to dollar metrics is also reasonable since usage metrics make no sense here.


## ▫️ NEGLIGIBLE — confirmed (1)

### 48. Region/account opt-in discovery and CE filter Values arrays have no cardinality guard against CE limits _(was low)_
`aws_cost_ultra/core/filters.py:92-138` · scale

**Why it's real:** The code matches the finding exactly. build_ce_filter (aws_cost_ultra/core/filters.py:92-100) places list(spec.linked_accounts) directly into a single Dimensions LINKED_ACCOUNT Values array with no cap, and lines 133-138 fan usage_type_substrings out into one Dimensions CONTAINS clause per substring wrapped in an "Or" (O(n) clauses). There is no length guard anywhere on these arrays, and CostFilterSpec carries no documented bound. AWS Cost Explorer does enforce a hard limit of 200 values per Dimensions filter and…

**Fix:** Proposed fix (cap/chunk Values to 200 and bound OR clauses, document limit on CostFilterSpec) is technically correct as preventative hardening, but is not required for current correctness since no caller populates these fields; treat as low-priority defensive work, not a live bug.


## ❓ Uncertain (real mechanism, negligible/unclear impact)

- **EC2 merge set in service_groups.py does not match the EC2 raw names used in the composition route** — `aws_cost_ultra/core/service_groups.py:13-16`
  The two definitions do NOT mismatch each other — the title is misleading. service_groups.py:13-16 (EC2_MERGE_SOURCES) and cost.py:236-239 (_EC2_RAW_NAMES) are byte-for-byte identical frozensets ({"Amazon Elastic Compute Cloud - Compute", "EC2 - Other"}). So the route and the merge agree; there is no internal inconsistency bug. The only real, narrower issue is the one in the…

- **New SQLite connection opened per cache call (connect + 2 PRAGMAs) — connection/PRAGMA churn and WAL contention under load and large payloads** — `aws_cost_ultra/web/sqlite_cache.py:49-65`
  The factual mechanism in sqlite_cache.py is real: _connect() (lines 52-55) opens a brand-new sqlite3.Connection and runs PRAGMA journal_mode=WAL + PRAGMA synchronous=NORMAL on every get/set/get_swr/bust, and these methods (lines 60, 68, 81, 95, 103) all use `with self._connect() as conn`, which in Python's sqlite3 commits/rolls back but does NOT close the connection. So the…

- **trend() aggregation is O(days × cells) — quadratic on wide daily windows** — `aws_cost_ultra/aws/cost_store.py:54-60`
  The algorithmic claim is literally true: DailyServiceMatrix.trend() at cost_store.py:54-60 builds values via a nested comprehension `sum(v for (d,_s),v in self.cells.items() if d==day) for day in labels`, which is O(len(days) × len(cells)). by_service() (lines 48-52) is by contrast single-pass O(cells). So the code shape the finding describes is genuine.  However, the IMPACT…


## ✅ False positives (verified NOT bugs — do not act)

- **EC2 USAGE_TYPE parser drops us-east-1 (un-prefixed) usage types entirely** — `aws_cost_ultra/resources/ec2.py:102-110`
  The finding's headline claim — that un-prefixed (us-east-1) EC2 usage types are "dropped entirely" — is false, and the finding itself concedes this mid-description. The code at aws_cost_ultra/resources/ec2.py:102 is `rest = raw.split("-", 1)[1] if "-" in raw else raw`. For us-east-1, CE returns bare keys like `BoxUsage:t3.micro`, `SpotUsage:m5.large`, `HeavyUsage:c5.xlarge`.…

- **S3 row name lookup references tag_resp which may be unbound when get_bucket_tagging raised** — `aws_cost_ultra/resources/s3.py:94-104`
  Read s3.py lines 83-115 and base.py (tag_name/tags_to_dict). In the loop body, `tags` is reset to `{}` at the start of every iteration (line 94). `tag_resp` is assigned on line 96 and `tags = tags_to_dict(tag_resp)` on line 97 — line 97 only runs if line 96 succeeded (no exception). If get_bucket_tagging raises ClientError, line 97 never executes, so `tags` remains `{}`…

- **get_swr lazy-delete opens a second connection under the lock for every expired read; expired-but-popular keys repeatedly DELETE** — `aws_cost_ultra/web/sqlite_cache.py:80-100`
  The finding's core mechanism — "every poll past the SWR window re-runs the DELETE (row already gone, matches 0 rows, but still takes the lock and a connection)" — cannot occur. get_swr first does a LOCK-FREE SELECT (sqlite_cache.py:81-85). If the row is absent it returns (None, True) at line 86-87, never reaching the locked DELETE block (lines 95-99). The first past-SWR read…
