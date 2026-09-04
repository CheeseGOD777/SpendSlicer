# CostSight

**Self-hosted AWS cost visibility that runs on your laptop.** Point it at your
existing AWS CLI profiles and get named-resource cost attribution, a waste
radar, and numbers that reconcile against the Billing console.

No account linking. No agent. No telemetry. Every AWS call is made from your
machine with your own credentials, and no cost data ever leaves it.

[![CI](https://github.com/CheeseGOD777/costsight/actions/workflows/ci.yml/badge.svg)](https://github.com/CheeseGOD777/costsight/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)

---

## Why this exists

The AWS Billing console tells you that `t4g.small · 500 hrs` cost $18.40. It
does not tell you *which instance*, what it was named, or whether it has been
sitting idle since March. Top spenders hide behind nested expanders, and EC2 is
split across a dozen line items that never add up on first read.

CostSight answers the questions you actually opened the console for:

- **Which named resource** cost what — instance ID, `Name` tag, current state
- **Top services and top resources** on one screen, sorted by spend
- **Waste radar** — stopped EC2 still paying for EBS, unattached volumes,
  unassociated Elastic IPs, untagged resources, budget breaches
- **Numbers you can defend** — every figure carries a provenance record saying
  which API produced it, over what window, with what filters

### Honest accuracy

This is the part most cost tools are vague about, so to be explicit:

| Source | How the number is produced |
| --- | --- |
| Service totals | Cost Explorer `GetCostAndUsage`. Ground truth — matches the console. |
| Per-resource cost | **Estimated.** Cost Explorer `USAGE_TYPE` buckets, split across the resources in that bucket by running hours and list price, then rescaled to match the service total. |
| Per-resource cost, with CUR enabled | **Exact.** Real billed line items from your Cost and Usage Report. See [docs/CUR.md](docs/CUR.md). |

So: **service totals are exact, per-resource splits are estimates** unless you
enable the CUR warehouse. CostSight says which you are looking at rather than
blurring the two.

Per-resource attribution deliberately does *not* use Cost Explorer's
`GetCostAndUsageWithResources`. That call bills $0.00001 per usage record on
top of the $0.01 per request, and on a real account it dominated the tool's
running cost. CUR gives the same per-resource precision from a local warehouse
for free.

Whatever cannot be attributed to a named resource is shown as explicit
**unattributed drift** rather than being silently spread across rows. Rescaling
is skipped entirely when the raw attributed sum falls outside 0.2x–5x of the
Cost Explorer total, since a tiny raw sum would otherwise inflate every row.

Costs are **pre-credit gross**, matching what the Billing console shows by
default.

---

## Install

### Desktop app (easiest)

Download from [Releases](https://github.com/CheeseGOD777/costsight/releases):

| Platform | File |
| --- | --- |
| macOS, Apple Silicon | `CostSight-<version>-macos-arm64.dmg` |
| macOS, Intel | `CostSight-<version>-macos-x86_64.dmg` |
| Windows x64 | `CostSight-<version>-windows-x64.zip` |

> **These builds are not code-signed yet.** macOS will claim the app "is
> damaged and can't be opened" — that is what Gatekeeper says about any
> unsigned download, not a real problem with the file. Windows SmartScreen will
> warn similarly. [docs/DESKTOP.md](docs/DESKTOP.md) has the one-line fix for
> each, and instructions for building it yourself if you would rather not trust
> a binary.

### pip

```bash
pip install "costsight[web,cur]"
costsight-web           # http://127.0.0.1:8080/app
```

The dashboard bundle ships inside the wheel, so Node.js is not required.

### From source

```bash
git clone https://github.com/CheeseGOD777/costsight.git
cd costsight
./run.sh                # Windows: run.bat
```

Requires Python 3.10+. The script creates a virtualenv, installs the `web` and
`cur` extras, and starts the server.

---

## First run

Pick an **AWS CLI profile** from the dropdown — the same profiles `aws
configure list-profiles` shows. If you have never set one up:

```bash
aws configure --profile my-account
```

CostSight reads `~/.aws/credentials` and `~/.aws/config` directly. SSO profiles
work as long as `aws sso login` has been run.

### A note on Cost Explorer costs

Cost Explorer is a paid API: **$0.01 per request**. CostSight is built around
that fact rather than ignoring it.

- Every response carries `X-CE-Calls-Spent` and `X-CE-Estimated-Cost-USD`
  headers, and the UI shows a running session meter
- Results are cached on disk for 30 minutes, then served stale for another
  6 hours while refreshing in the background
- Background refreshes are deduplicated per cache key and capped globally

A typical dashboard session costs a few cents. Tune it with
`COSTSIGHT_CACHE_TTL_SECONDS` — see [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

---

## IAM permissions

CostSight is strictly read-only. It never creates, modifies, or deletes
anything. The minimum policy is in [docs/IAM.md](docs/IAM.md), which lists
every API call the code actually makes and which feature breaks without it.

The short version: `ReadOnlyAccess` works, or attach the least-privilege policy
from that document.

---

## Documentation

| Document | What's in it |
| --- | --- |
| [docs/DESKTOP.md](docs/DESKTOP.md) | Installing the unsigned builds; building your own |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every environment variable |
| [docs/IAM.md](docs/IAM.md) | Least-privilege policy, per-call breakdown |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How attribution works, module layout |
| [docs/CUR.md](docs/CUR.md) | Optional CUR warehouse for exact line-item costs |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup, tests, PR expectations |
| [SECURITY.md](SECURITY.md) | Threat model, reporting a vulnerability |

---

## Security posture

CostSight binds to `127.0.0.1` and nothing else by default.

- **Desktop builds** mint a random auth token per launch and bind an ephemeral
  port. Nothing else on the machine can drive them.
- **Self-hosted** runs are unauthenticated on loopback by default, which is
  fine on a laptop. If you bind any other interface, you **must** set
  `COSTSIGHT_AUTH_TOKEN` — the server logs a loud warning if you don't.

Cost Explorer requests spend real money, so an open port is a financial
exposure and not just a data one. [SECURITY.md](SECURITY.md) covers the full
threat model.

---

## Project status

Beta. The test suite covers the attribution math, time-window handling, cache
semantics, and the audit engine, and it runs against Python 3.10–3.13 on every
push. The accuracy model is the part still moving — CUR-based attribution is
the path to making the estimates exact, and it is the most valuable place to
contribute.

Known limitations:

- **PDF export needs Node.js.** It renders through Puppeteer, so it does not
  work in the desktop builds or a bare `pip install`. CSV and JSON export work
  everywhere.
- The Pricing API fallback table only carries `ap-south-1` rates; other regions
  fall through to the live API.

## Contributing

Contributions welcome — especially CUR-based attribution, more service
enumerators, and regional pricing coverage. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).
