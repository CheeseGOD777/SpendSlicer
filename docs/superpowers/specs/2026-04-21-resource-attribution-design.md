# AWS Cost Dashboard — Resource-Level Cost Attribution (Phase 1)

**Date:** 2026-04-21
**Status:** Approved design, awaiting implementation plan
**Scope:** Phase 1 — `ap-south-1` region, five services (EC2, EIP, EBS, RDS, ELB)

## Goal

Replace the "Cost Explorer grouped by usage type" tables with a resource-first
view. Enumerate real AWS resources via boto3 describe APIs, attribute cost to
each resource by name/ARN, and surface idle-resource waste. Cost Explorer
service totals remain the ground-truth dollar anchor.

## Problem statement

Cost Explorer groups cost by `USAGE_TYPE`, which collapses all instances of the
same type (e.g., every `t4g.small`) into a single row. Cost allocation tags
(e.g., `Name`) can disambiguate, but require manual activation in the Billing
console and take ~24h to populate — and in this account they are not activated,
so every row currently renders as `(untagged)`.

With account-level CLI access, we can enumerate the real resources and
attribute cost ourselves. This spec defines that mechanism for five services in
`ap-south-1`.

## Non-goals (Phase 1)

- Multi-region scanning (Phase 2).
- S3 per-bucket cost, NAT Gateway, snapshots, CloudWatch Logs (Phase 2).
- Historical per-resource cost (we attribute over the selected CE date range
  only).
- CUR ingestion or enabling hourly CE granularity.

## Architecture

```
app.py                (Flask routes, unchanged shape)
  ├── resources/       (NEW — one enumerator per service)
  │    ├── __init__.py
  │    ├── base.py     (Resource / ResourceCost dataclasses, normalize helper)
  │    ├── ec2.py      (describe_instances)
  │    ├── eip.py      (describe_addresses)
  │    ├── ebs.py      (describe_volumes)
  │    ├── rds.py      (describe_db_instances)
  │    └── elb.py      (describe_load_balancers v1+v2)
  ├── pricing.py       (NEW — AWS Pricing API wrapper with TTL cache)
  └── cost_sources.py  (NEW — refactor of existing CE helpers)
```

### Data flow per service

1. **Enumerate** — describe API returns the resource list (ARN, name tag,
   type, state, attach info, creation time).
2. **Compute raw cost** — for each resource, compute cost using actual usage
   from the describe payload × AWS Pricing API rate, bounded to the
   selected date range.
3. **Normalize** — sum all raw costs for this service/usage-type; fetch the
   CE total for the same window; scale each resource's cost by
   `ce_total / raw_sum`. This corrects for credits, free tier, and timing
   drift so rows always sum to the CE service total the user sees up top.
4. **Return** — list of `{arn, name, type, state, raw_cost, cost, attributes,
   waste_reason?}`.

### `Resource` / `ResourceCost` shape

```python
@dataclass
class Resource:
    arn: str
    service: str        # "EC2", "EIP", "EBS", "RDS", "ELB"
    resource_id: str    # i-xxx, eipalloc-xxx, vol-xxx, db-xxx, lb-xxx
    name: str           # Name tag, or fallback to resource_id
    type: str           # "t4g.small", "gp3", "db.t3.micro", "application", etc.
    state: str          # "running", "attached", "unassociated", etc.
    attributes: dict    # service-specific (e.g., attached_instance_id, size_gb)
    tags: dict

@dataclass
class ResourceCost:
    resource: Resource
    cost: float                     # normalized
    raw_cost: float                 # before normalization
    usage: dict                     # hours, gb_month, etc.
    waste_reason: str | None        # "unattached", "idle", "no targets", ...
```

## Per-service rules

### EC2 instances (`resources/ec2.py`)
- Enumerate: `ec2.describe_instances()` — all states (we still cost stopped
  instances' EBS volumes, which are handled separately in `ebs.py`).
- Cost basis: `(running_hours_in_window) × on_demand_rate[instance_type]`.
  - `running_hours_in_window = min(now, window_end) - max(launch_time, window_start)`
    when state is currently `running`; for instances that stopped mid-window we
    approximate using `LaunchTime` only (acceptable for Phase 1, flagged in the
    "limitations" doc footer).
- Normalize against CE `Amazon Elastic Compute Cloud - Compute` service total
  filtered to `BoxUsage:*` usage types.
- Waste: none in Phase 1 (idle detection via CloudWatch is Phase 2).

### Elastic IPs (`resources/eip.py`)
- Enumerate: `ec2.describe_addresses()`.
- Cost basis: EIPs are free when **associated with a running instance**,
  otherwise billed at `$0.005/hour` (list price; Pricing API is authoritative).
- Compute hours-unassociated in window. For currently-unassociated IPs we use
  `allocation_time → now`; for associated IPs we treat as zero-cost.
  (Historic attach/detach isn't reliably available from describe APIs —
  acknowledged limitation.)
- Normalize against CE `EC2 - Other` / `PublicIPv4:InUseAddress` total.
- Waste: `unattached` — any EIP with `AssociationId == None`.

### EBS volumes (`resources/ebs.py`)
- Enumerate: `ec2.describe_volumes()`.
- Cost basis: `size_gb × rate[volume_type] × (hours_in_window / 730)`.
- Resolve attached instance name via `Attachments[*].InstanceId` → join with
  EC2 enumeration.
- Normalize against CE `EC2 - Other` / `EBS:VolumeUsage*` totals.
- Waste: `unattached` when `State == 'available'`.

### RDS instances (`resources/rds.py`)
- Enumerate: `rds.describe_db_instances()`.
- Cost basis: `uptime_hours × instance_rate + storage_gb × storage_rate × month_fraction`.
- Normalize against CE `Relational Database Service` total.
- Waste: none in Phase 1.

### Load balancers (`resources/elb.py`)
- Enumerate both `elbv2.describe_load_balancers()` (ALB/NLB) and
  `elb.describe_load_balancers()` (Classic).
- Cost basis: `(window_hours) × lb_hour_rate[type]`. LCU cost is left in the
  normalization residual.
- Resolve target group counts via `elbv2.describe_target_health` (only to flag
  "no targets").
- Normalize against CE `Elastic Load Balancing` total.
- Waste: `no targets` when all target groups have zero healthy targets.

## Pricing API (`pricing.py`)

- Use `pricing` client pinned to `us-east-1` (Pricing API is only available
  there and in `ap-south-1`; we'll use `us-east-1` for stability).
- One function: `get_rate(service_code, attributes: dict) -> float`.
- In-memory TTL cache (24h) keyed by `(service_code, sorted attrs)`.
- Handles the JSON structure: `terms.OnDemand.*.priceDimensions.*.pricePerUnit.USD`.
- If the Pricing API call fails, fall back to a small hard-coded ap-south-1
  rate table (documented in the module) so the dashboard still renders.

## New/changed endpoints

- **`GET /api/resources-detailed?service=<SERVICE>&start=&end=&credits=`**
  - Returns `{service, resources: [ResourceCost...], ce_total, raw_sum,
    normalization_factor, limitations: [str]}`.
  - `service` is one of `EC2`, `EIP`, `EBS`, `RDS`, `ELB`. Unknown → 400.
- **Existing `/api/resources`** — unchanged. Used as fallback when a service
  has no enumerator (Phase 1 fallback for everything except the five).

## UI changes (to be implemented with `frontend-design` skill)

1. **New tab: `Resources`** (replaces default `By Resource Name` in the
   resource table). Sub-filter row shows service pills (EC2 · EIP · EBS · RDS
   · ELB · Other); clicking a pill calls `/api/resources-detailed` for that
   service. "Other" falls back to the old usage-type view.
2. **Row layout**: `Name` · `Type` · `State` · `Attached to` · `Cost` · `%` ·
   optional red `Waste` badge on the right.
3. **Waste finder panel** (above the table): small card summarizing
   `N unattached EIPs · $X/mo`, `M orphaned EBS volumes · $Y/mo`, `K LBs with
   no targets · $Z/mo`. Click-through scrolls/filters the table.
4. **Gross/Net tooltip**: info icon next to the toggle explains the
   credit-delta (addresses original item #1 / $86 vs $81).
5. **Tag activation banner**: when a user switches to the legacy `By Resource
   Name` view and every row is `(untagged)`, show a dismissible banner with a
   direct link to Billing → Cost Allocation Tags and a note about the ~24h
   activation lag.
6. **Usage-type polish** (item #5): widen `Usage Type` column, drop the
   verbose `Raw Usage Type` column into a hover/expand, right-align numbers.

Detailed visual design deferred to the frontend-design invocation during
implementation.

## IAM permissions required

Additive to the profile's existing `ce:*` permissions:

- `ec2:DescribeInstances`
- `ec2:DescribeAddresses`
- `ec2:DescribeVolumes`
- `rds:DescribeDBInstances`
- `elasticloadbalancing:DescribeLoadBalancers`
- `elasticloadbalancing:DescribeTargetGroups`
- `elasticloadbalancing:DescribeTargetHealth`
- `pricing:GetProducts`

If a profile lacks any of these, the affected service's `resources-detailed`
response returns the usage-type fallback with an `error` field explaining what
is missing.

## Caching & performance

- Resource enumerations cached 5 min per service (existing `_cached` TTL).
- Pricing API cached 24h.
- All five enumerators called in parallel (ThreadPoolExecutor) when the UI
  loads the dashboard.
- Typical first-load budget (ap-south-1 only): < 3 s.

## Error handling

- Each enumerator is wrapped so a single service failing (e.g., missing IAM)
  does not take down the endpoint. Failures surface as a banner on the
  affected tab, not a 500.
- Pricing API failures fall back to the hard-coded rate table; UI flags
  `using fallback rates`.

## Testing

- Unit tests for:
  - `normalize()` — verify `sum(result) == ce_total` within float tolerance.
  - Each enumerator with a boto3 stub (`botocore.stub.Stubber`).
  - Pricing API cache hit/miss and JSON parsing.
- Manual smoke: run against the `terraform-learning` profile in `ap-south-1`;
  verify that EC2 rows list `creators-service-server-test2-shared-env`,
  `worker-server-test2`, `analytics-server-test2-shared-env`,
  `influenzer-server-test2-shared-env` with non-zero cost that sums to the CE
  EC2 Compute total shown in the summary card.

## Known limitations (surfaced in UI footer)

- EC2 cost assumes instances were running continuously since launch when the
  current state is `running`. Instances stopped mid-window are approximated.
- EIP cost assumes current association state held for the full window.
- LCU cost on ALB/NLB is absorbed into normalization rather than computed
  per-LB.
- Phase 1 is `ap-south-1` only. Spend outside that region will appear under
  the "Other" fallback tab.

## Out of scope / Phase 2

- S3 per-bucket (list_buckets + CloudWatch BucketSizeBytes).
- NAT Gateway, snapshots, AMIs, CloudWatch Logs.
- Multi-region scan with region picker.
- Idle detection via CloudWatch metrics (CPU, connections, request count).
- CUR-based historical per-resource cost.
