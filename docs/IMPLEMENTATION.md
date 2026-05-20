# aws-cost-ultra — Implementation Log

Running log of architecture decisions and phase progress.
User chose to skip the formal spec; this file is the decision paper trail.

---

## Product positioning (locked 2026-04-22)

- **End-state**: Self-hosted unified tool for the complete AWS billing problem
- **Distribution**: `pipx install` + Docker + optional PyInstaller binary
- **Data custody**: Zero. The tool reads the user's local `~/.aws/credentials`; every AWS call runs from the user's machine. No remote server stores credentials or cost data.
- **Commercial path (optional, later)**: If traction warrants, add a hosted control-plane tier with cross-account IAM roles — never stored credentials.

## MVP scope

Six sub-projects + one cross-cutting invariant:
1. Core Engine & Data Model
2. Cost Visibility & Attribution
3. FinOps Audit Engine
6. Reporting & Distribution
7. Web UI & UX
8. Packaging & Install

**Dropped**: Optimization/Recommendations (was 4), Anomaly Detection (was 5) — natural future paid-tier features.

**Accuracy invariant (non-negotiable)**: Every displayed cost number carries provenance metadata (metric type, time range, record-type filter, timezone). Default metric = `UnblendedCost` to match AWS Console. Attribution math normalized to Cost Explorer ground truth; drift >1% surfaces as a warning. Nightly CI compares against CE directly.

## Architecture approach

**Approach B — Core library + CLI + Web UI (three surfaces, one engine):**
- `aws_cost_ultra.core` — pure business logic, framework-free, unit-testable
- `aws_cost_ultra.aws` — AWS API wrappers (sessions, CE, resource enumerators)
- `aws_cost_ultra.audit` — audit engine
- `aws_cost_ultra.exporters` — PDF / CSV / JSON / Slack / S3
- `aws_cost_ultra.cli` — Typer + Rich CLI
- `aws_cost_ultra.web` — FastAPI + Jinja + HTMX UI

## Phase plan

Phase 3 pulled ahead of Phase 2 because the user flagged accuracy as the #1 trust issue. Order:

1. **Phase 1** ✓: Package scaffold + migrate `pricing.py` and `resources/` into new layout.
2. **Phase 3** ✓: CE wrapper (`aws/cost_explorer.py`) + filters + time windows, all returning `CostValue` with full provenance. Defaults match AWS Billing Console.
3. **Phase 2** ✓: Multi-profile orchestration, multi-region support, ThreadPoolExecutor fan-out.
4. **Phase 4** ✓: Audit engine (untagged, idle, unused, budget breach).
5. **Phase 5** ✓: Exporters (PDF, CSV, JSON, Slack, S3, SES/SMTP, scheduled runs).
6. **Phase 6**: CLI (Typer + Rich) with matching ref-tool flag surface.
7. **Phase 7**: Web UI migration — Flask → FastAPI, add multi-account views, dark mode, HTMX interactivity. Wire new CE wrapper into every UI cost figure.
8. **Phase 8**: Packaging, Docker, first-run wizard, opt-in telemetry, README rewrite, PyPI publish.

## Decisions

| # | Decision | Rationale | Phase |
|---|---|---|---|
| 1 | Working package name: `aws_cost_ultra` | Final brand name TBD; keeps import path stable during development | 1 |
| 2 | Python target: `>=3.9` | `dict[...]` union syntax already used in codebase; broad boto3 compat | 1 |
| 3 | Migration strategy: build new package alongside old, shim old modules | Zero downtime during rewrite; `app.py` keeps working | 1 |
| 4 | Phase 1 preserves existing CE `RECORD_TYPE` filter (excludes Credit/Refund/Upfront) | Behavior parity during scaffold; make configurable in Phase 3 | 1 → 3 |
| 5 | Phase 1 preserves `REGION = "ap-south-1"` hardcode | Remove in Phase 2 with multi-region support | 1 → 2 |
| 6 | CLI framework: Typer (not Click, not argparse) | Type-hint-native, produces nice `--help`, pairs cleanly with Rich | 6 |
| 7 | Web framework: FastAPI | Async, OpenAPI docs free, easy to mount Jinja + HTMX | 7 |
| 8 | Frontend: HTMX + Alpine + Chart.js (no React in v1) | Matches approach B's "polished without React overhead" decision | 7 |
| 9 | Local storage: SQLite via stdlib `sqlite3` for cache + history | No extra dependency; local-only; user-controlled | 1 → 2 |

## Phase 3 delivered (accuracy foundation)

Root cause of mismatch identified in legacy code: `app.py:76` sets `_EXCLUDE_RECORD_TYPES = ["Credit", "Refund", "Upfront"]` as the default CE filter, which strips Credit/Refund/Upfront lines before totaling. Result: the tool reports pre-credit *gross* cost while AWS Billing Console shows *net* cost. For any account with credits (AWS Activate, support credits, promotional credits), the two numbers diverge significantly.

**Fix shipped in `aws_cost_ultra.aws.cost_explorer`:**

- `CostExplorerClient.get_*` methods default to `console_default()` filter spec → no record-type exclusion, matches Console.
- `pre_credit_gross()` preset remains available for the "true cost of usage" view but is explicit, labeled, and never default.
- Every returned number is a `CostValue` with a `Provenance` carrying: metric, time window, timezone=UTC, included/excluded record types, group_by dimensions, filter summary. `Provenance.label()` renders a one-line human caption for UI tooltips.
- `build_ce_filter()` composes service/tag/linked-account/record-type/usage-type filters deterministically — the only place in the codebase that produces a CE Filter dict.
- `variance_warning(provenance)` returns a user-facing message when attribution drift vs CE ground truth exceeds 1%. Phase-4+ attribution paths populate `variance_from_ground_truth_pct` so the UI can warn automatically.
- Pagination (NextPageToken) handled internally.
- Time windows (`core.time_windows`) are UTC-only and timezone-aware; passing a naive datetime raises `ValueError`.

**Test coverage (28 tests, all green):**
- `test_cost_explorer.py` — 9 tests; most critical: `test_default_filter_is_console_matching_no_record_type_filter` asserts no Filter is sent when using default spec. A future regression that silently re-introduces the legacy exclusion will fail this test loudly.
- `test_filters.py` — 8 tests on filter composition.
- `test_time_windows.py` — 6 tests on UTC boundary correctness.
- `test_smoke.py` — 5 package-level sanity tests.

Legacy `app.py` still runs unchanged; Phase 7 cuts its routes over to the new CE wrapper.

## Phase 2 delivered (multi-profile & multi-region)

`aws_cost_ultra/aws/session.py` extended with:

- `ProfileBundle` dataclass — `profile`, `session`, `account_id`, `account_alias`, `regions`. `display_name()` returns alias → account_id → profile in preference order.
- `account_alias_for(session)` — IAM `list_account_aliases`, returns first alias or None.
- `accessible_regions(session)` — EC2 `describe_regions` filtered to opted-in regions, sorted. Falls back to an 11-region hardcoded safe list on permission failures.
- `load_profile_bundle(profile, regions=None)` — single-profile loader; skips region discovery if explicit list provided.
- `all_profile_bundles(regions, max_workers=8)` — parallel load for all local profiles; silently skips profiles whose credentials can't authenticate.
- `fanout(bundles, fn, max_workers=8)` — runs `fn(bundle)` in parallel, returns `(bundle, result_or_exception)` pairs; callers decide how to handle per-profile failures.
- `fanout_regions(bundle, fn, max_workers=8)` — same pattern, runs `fn(session, region)` per region within one profile.

Resource enumerators (`ec2.py`, `ebs.py`, etc.) already accept a `region` parameter; the hardcoded `REGION = "ap-south-1"` constant in `resource_base.py` is now the default only — callers driven by `ProfileBundle.regions` never hit it.

**Test coverage (17 tests, all green):** `test_session.py` — make_session, account_id_for, account_alias_for, accessible_regions, ProfileBundle display_name, load_profile_bundle region bypass, fanout happy path + exception capture + empty input, fanout_regions.

## Phase 4 delivered (FinOps audit engine)

Four modules in `aws_cost_ultra/audit/`:

- `untagged.py` — `scan_untagged(session, region, required_tags, services)`: scans EC2, RDS, Lambda, ELBv2 for resources missing any required cost-allocation tag. Per-service helpers tolerate `ClientError` (missing permissions) and skip gracefully.
- `idle.py` — `find_idle_resources(session, region, checks)`: six check types — stopped EC2, unattached EBS (with $/month estimate), unused EIPs ($3.60/mo each), orphaned snapshots (source volume deleted), stopped RDS, idle ELBs (no healthy targets). Each check is independently selectable via the `checks` list.
- `budgets.py` — `get_budget_findings(session, warn_at_pct=80)`: reads all AWS Budgets for the account, classifies each as BREACHED / WARNING / OK / UNKNOWN. Sorted: breached first. Returns empty list gracefully if STS or Budgets access fails.
- `runner.py` — `run_audit(session, profile, account_id, regions, ...)`: parallel per-region untagged+idle scan via `ThreadPoolExecutor`, followed by account-level budget check. Returns `AuditResult` with `.total_estimated_waste_usd`, `.to_dict()` with summary block.

**Test coverage (13 tests, all green):** untagged scanner (required tags, tag filtering, terminated instance skip), idle finders (stopped EC2, unattached EBS cost estimate, unused EIP), budget status transitions (BREACHED/WARNING/OK/no-account), runner returns typed AuditResult.

## Phase 5 delivered (exporters)

Seven modules in `aws_cost_ultra/exporters/`:

- `base.py` — `ExportResult` dataclass: format, destination, success, error, bytes_written, exported_at.
- `json_export.py` — `export_json(data, path)` + `to_json_string(data)`. No extra deps.
- `csv_export.py` — `export_csv(rows, path, flatten=True)` + `to_csv_string`. Recursive dict flattening to dot-notation columns. No extra deps.
- `pdf_export.py` — `export_pdf(report, path)` using ReportLab. Deferred ImportError if `reportlab` not installed. Renders header, top-services table, audit summary, budget status table.
- `slack_export.py` — `export_slack(report, channel, token)` using Block Kit. Deferred ImportError if `slack_sdk` not installed.
- `s3_export.py` — `upload_file(local_path, bucket, key, session)` + `upload_bytes(...)`. Content-type inferred from extension.
- `email_export.py` — `send_via_ses(...)` and `send_via_smtp(...)`. Both support optional PDF attachment. HTML body generated inline.
- `scheduler.py` — `run_scheduled_export(report, config)`: one-shot runner that writes local files, optionally uploads to S3, posts to Slack, and sends SES email. `ScheduledExportConfig` dataclass controls all knobs. Idempotent: each run creates a timestamped file.

**Test coverage (16 tests, all green):** JSON write + parent dir creation + bytes_written; CSV header/data/flatten/no-flatten/empty; scheduler JSON + CSV + both formats + row flattener; ExportResult.to_dict keys.

## Open questions (non-blocking)

- Brand name — defer to Phase 8
- Hosted tier pricing model — post-MVP
- Organization integration model (assume-role vs. profile-per-account) — Phase 2 will support both
