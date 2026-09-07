# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Primary — the platform / DevOps engineer.** Runs infrastructure for a team of
roughly 10–100 people, is AWS-fluent, and juggles several CLI profiles across
accounts. They open SpendSlicer for two jobs: find waste worth acting on, and
answer "why did the bill jump?" for engineers who are not going to read the
Billing console themselves. They are the one who installs it, and the one whose
laptop it runs on.

**Second — the FinOps / finance-facing analyst.** Their job is reporting, not
remediation. They need figures they can defend to finance and reconcile against
the Billing console, and they need to get numbers out of the tool (CSV, JSON,
PDF) rather than only look at them. They care more about provenance and
export than about the waste radar.

Both audiences are already running the AWS CLI with configured profiles
(including SSO). SpendSlicer never asks for credentials it does not already
find on the machine.

## Product Purpose

Self-hosted AWS cost visibility that runs entirely on the user's own machine.
It answers the questions the AWS Billing console evades: which *named* resource
cost what, which services and resources are the top spenders on one screen,
what is being paid for and not used, and where every figure came from.

Success is open-source adoption — people running it on their own accounts,
trusting it enough to defend its numbers, and contributing back. Credibility is
the currency: the project wins by being the AWS cost tool engineers believe.

## Positioning

Three things a neighboring product cannot truthfully copy:

1. **No account linking, no agent, no telemetry.** Every AWS call is made from
   the user's machine with their own credentials, and no cost data ever leaves
   it. Competing tools require granting a vendor read access to the billing
   account; SpendSlicer never does.
2. **Explicit accuracy tiers.** Service totals are exact (Cost Explorer ground
   truth). Per-resource splits are *estimates* unless CUR is enabled, in which
   case they are exact billed line items. The tool always says which one the
   user is looking at instead of blurring the two.
3. **Cost Explorer spend is treated as a real cost of using the tool.** CE bills
   $0.01 per request, so SpendSlicer surfaces a running session meter, caches
   aggressively (30 min TTL, 6 h stale-while-revalidate), deduplicates
   background refreshes, and deliberately refuses `GetCostAndUsageWithResources`
   because its per-usage-record billing dominated the tool's own running cost.

## Operating Context

- Launched from a laptop: `./run.sh`, `pip install "spendslicer[web,cur]"` then
  `spendslicer-web`, or an unsigned native desktop build (macOS `.dmg`,
  Windows `.zip`) that binds an ephemeral loopback port and mints a per-launch
  auth token.
- Reads `~/.aws/credentials` and `~/.aws/config` directly; the profile picker
  mirrors `aws configure list-profiles`. SSO profiles work once `aws sso login`
  has run.
- Strictly read-only against AWS. `ReadOnlyAccess` is sufficient; a
  least-privilege policy is documented per API call in `docs/IAM.md`.
- Binds `127.0.0.1` and nothing else by default. Any other bind requires
  `SPENDSLICER_AUTH_TOKEN`; an open port is a financial exposure, not only a
  data one.
- Optional CUR warehouse (DuckDB + Parquet from the user's own S3 bucket)
  upgrades per-resource attribution from estimated to exact, ingested by a
  background worker.

## Capabilities and Constraints

**Shipped surfaces:** Dashboard, Services, Resources, Audit, Export — a
collapsible sidebar plus a topbar carrying the period selector, AWS profile
selector, and CE session meter.

**Attribution:** service totals from Cost Explorer `GetCostAndUsage` grouped by
`SERVICE`, filtered to pre-credit gross so figures match the Billing console.
Per-resource estimates come from running hours × list price (Pricing API or a
built-in fallback table), then rescaled to the CE total — with rescaling
skipped entirely when the raw sum falls outside 0.2×–5× of the total. The
remainder is surfaced as explicit **unattributed drift**, never spread silently
across rows. Every number carries a provenance record naming the API, window,
and filters that produced it.

**Resource coverage:** EC2, EBS, RDS, S3, ELB, Elastic IP, Lambda, DynamoDB.

**Waste radar:** idle/stopped resources still billing (stopped EC2 with live
EBS, unattached volumes, unassociated EIPs), untagged resources, budget
breaches.

**Export:** CSV, JSON, PDF, Slack, S3, SES, plus a scheduler.

**Stack:** Python 3.10+ / FastAPI backend serving a prebuilt React 18 + Vite
dashboard (Recharts for charts, Hanken Grotesk and JetBrains Mono via
Fontsource). SQLite for the CE cache, DuckDB for CUR. The dashboard bundle
ships inside the wheel, so Node.js is not required to run it. PyInstaller +
pywebview produce the desktop builds.

**Known limitations, not to be papered over:**
- PDF export renders through Puppeteer and therefore needs Node.js — it does
  not work in the desktop builds or a bare `pip install`. CSV and JSON do.
- The Pricing API fallback table only carries `ap-south-1` rates; other regions
  fall through to the live API.
- Desktop builds are not code-signed. macOS Gatekeeper and Windows SmartScreen
  will warn.
- Costs are pre-credit gross, matching the Billing console default.

**Status:** v1.0.0, first public release 2026-09-07. CUR-based
attribution is the accuracy model still in motion.

## Brand Commitments

- **Name:** SpendSlicer. MIT licensed, public on GitHub.
- **Voice:** direct, specific, and unflinching about limitations. The README
  names what the tool estimates, what it costs to run, and what is broken. That
  candor is the trust mechanism and must survive every rewrite.
- **Visual identity:** open. On 2026-09-05 the user explicitly released the
  original "Editorial Ledger" system (warm cream page, deep emerald accent,
  Hanken Grotesk, paper grain) for full replacement, asking for a modern, clean,
  minimal interface with seamless interaction across all five pages. The earlier
  record treating that system as binding is superseded. Nothing about the name,
  the license, or any accuracy behavior was released with it.

Three constraints the user made binding; nothing may contradict them:
1. Local-only, zero telemetry — no account linking, no agent, no data leaving
   the machine.
2. Honest accuracy labeling — exact vs. estimated always visibly distinguished;
   unattributed drift always shown explicitly.
3. Cost Explorer spend visibility — the per-request meter and cache behavior
   stay surfaced in the UI.

## Evidence on Hand

- **Real product documentation:** `README.md`, `docs/ARCHITECTURE.md`,
  `docs/CONFIGURATION.md`, `docs/IAM.md`, `docs/CUR.md`, `docs/DESKTOP.md`,
  `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`.
- **Working software:** the full FastAPI + React application, a test suite over
  attribution math, time windows, cache semantics, and the audit engine, and CI
  across Python 3.10–3.13 with PyInstaller smoke builds on macOS and Windows.
- **Icons:** `packaging/icons/icon.png`, `.icns`, `.ico`.
- **Absences future work must not fabricate:** there are no users, customers,
  testimonials, case studies, press mentions, adoption numbers, benchmarks,
  pricing, or hosted service. Nothing is code-signed. No logo mark exists
  beyond the packaging icon.

## Product Principles

1. **The number must be defensible.** Every figure carries where it came from.
   A user who cannot explain a number to their finance team has not been served.
2. **Estimated is never dressed as exact.** The accuracy tier is part of the
   data, shown at the point of reading — not disclosed in a footnote.
3. **Using the tool costs money, so say so.** CE spend is surfaced, not hidden
   behind a spinner. Design that encourages careless refetching is a bug.
4. **Nothing leaves the machine.** Any feature that would send cost data
   anywhere is out of scope by definition, not a trade-off to weigh.
5. **Candor beats polish.** Limitations are stated plainly in the product, the
   way they are in the README. Credibility is the adoption strategy.

## Accessibility & Inclusion

No product-specific standard has been established with the user. The shipped
frontend already honors `prefers-reduced-motion` and defines `:focus-visible`
styling; treat those as a floor to keep, not a target reached. Dense numeric
tables are the primary reading surface, so color must never be the sole carrier
of meaning (over/under budget, positive/negative delta, exact/estimated).
