# aws-cost-ultra

Self-hosted AWS cost visibility for DevOps teams. Uses your **local AWS CLI profiles** — no cloud account linking, no data leaves your machine.

## Why

The AWS Billing console shows usage types (`t4g.small · 500 hrs`) without resource names, hides top spenders behind nested expanders, and splits EC2 across confusing line items. This tool answers:

- **Which named resource** cost how much (instance ID, Name tag, state)
- **Top services and top resources** on one screen
- **Waste radar** — stopped EC2, unattached EBS, unused EIPs, untagged resources
- Numbers **reconciled to Cost Explorer** (pre-credit, matching the Billing console)

## Quick start

```bash
cd aws-cost-dashboard
python -m venv venv && source venv/bin/activate
pip install -e ".[web]"
aws configure   # or use existing ~/.aws/credentials profiles
python -m aws_cost_ultra.web.app
```

Open http://127.0.0.1:8080 — pick an **AWS CLI profile** from the dropdown (same as `AWS_PROFILE`).

## IAM permissions (minimum)

Your profile needs read-only access including:

- `ce:GetCostAndUsage`, `ce:GetCostForecast`
- `ec2:Describe*`, `rds:Describe*`, `elasticloadbalancing:Describe*`, `s3:List*`, `lambda:List*`, `dynamodb:List*`
- `sts:GetCallerIdentity`, `iam:ListAccountAliases`
- `budgets:ViewBudget` (for budget alerts)

## Architecture

```
aws_cost_ultra/
  core/       Filters, provenance, pricing, service grouping
  aws/        Session factory, Cost Explorer, CE RESOURCE_ID queries
  resources/  Per-resource attribution (EC2, EBS, RDS, …)
  audit/      Idle + untagged + budgets
  exporters/  JSON / CSV / PDF / Slack / S3
  web/        FastAPI + HTMX dashboard
```

**Accuracy model:** Service totals come from Cost Explorer. EC2 prefers CE `RESOURCE_ID` (billed instance → exact cost). Other services use list-price estimates scaled to CE service totals. Unattributed drift is shown explicitly.

## Open source

MIT licensed. Contributions welcome — especially CUR-based attribution and more service enumerators.
