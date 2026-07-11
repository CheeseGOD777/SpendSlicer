"""Tests for the three attribution-math bugs found in real-account usage.

1. Report KPI tiles showed capped-list lengths ("Top Resources 50" = the cap),
   not real counts.
2. EIP rows were rescaled into the "EC2 - Other" CE pool, but public IPv4
   charges bill under "Amazon Virtual Private Cloud" since Feb 2024 — six
   $3.65/mo EIPs rendered as $0.97 each while VPC sat as an opaque aggregate.
3. EC2 usage-type buckets with no matching live instance (terminated/replaced,
   e.g. Elastic Beanstalk churn on a closed month) were silently dropped into
   drift, so the Resources tab showed 1 of 4 instances.
"""

from __future__ import annotations

from datetime import datetime

from aws_cost_ultra.resources.base import AttributedResource


# ---------------------------------------------------------------------------
# Bug 3 — EC2 buckets with no live instance must surface as aggregate rows
# ---------------------------------------------------------------------------

class _FakeCe:
    """Single-page CE response with two BoxUsage buckets + one CPUCredits."""

    def get_cost_and_usage(self, **kwargs):
        return {
            "ResultsByTime": [{
                "Groups": [
                    {"Keys": ["APS3-BoxUsage:t4g.small"],
                     "Metrics": {"UnblendedCost": {"Amount": "24.07"},
                                 "UsageQuantity": {"Amount": "720"}}},
                    {"Keys": ["APS3-BoxUsage:t4g.medium"],
                     "Metrics": {"UnblendedCost": {"Amount": "14.16"},
                                 "UsageQuantity": {"Amount": "720"}}},
                    {"Keys": ["APS3-CPUCredits:t4g"],
                     "Metrics": {"UnblendedCost": {"Amount": "0.48"},
                                 "UsageQuantity": {"Amount": "12"}}},
                ],
            }],
        }


def _live_t4g_small():
    return {
        "InstanceId": "i-live",
        "InstanceType": "t4g.small",
        "InstanceLifecycle": None,
        "LaunchTime": datetime(2026, 1, 1),
        "State": {"Name": "running"},
        "Placement": {"AvailabilityZone": "ap-south-1a"},
        "PrivateIpAddress": "10.0.0.1",
        "PublicIpAddress": "3.3.3.3",
        "Tags": [{"Key": "Name", "Value": "live-instance"}],
    }


def test_unmatched_ec2_bucket_becomes_aggregate_row_not_drift():
    from aws_cost_ultra.resources.ec2 import _attribute_from_usage_type

    rows = _attribute_from_usage_type(
        session=None, ce_client=_FakeCe(),
        window_start=datetime(2026, 6, 1), window_end=datetime(2026, 7, 1),
        region="ap-south-1", instances=[_live_t4g_small()],
    )
    by_id = {r.resource_id: r for r in rows}

    # The live t4g.small absorbs its own bucket as before.
    assert round(by_id["i-live"].cost_usd, 2) == 24.07

    # The t4g.medium bucket has NO live instance — it must appear as a
    # labelled aggregate row instead of vanishing into drift.
    unmatched = [r for r in rows if r.attributes.get("aggregate")
                 and "t4g.medium" in (r.resource_type or "")]
    assert len(unmatched) == 1
    assert round(unmatched[0].cost_usd, 2) == 14.16
    assert unmatched[0].service == "EC2"

    # Total attributed == total CE cost (nothing silently dropped).
    assert round(sum(r.cost_usd for r in rows), 2) == round(24.07 + 14.16 + 0.48, 2)


def test_non_instance_ec2_usage_surfaces_as_single_aggregate():
    from aws_cost_ultra.resources.ec2 import _attribute_from_usage_type

    rows = _attribute_from_usage_type(
        session=None, ce_client=_FakeCe(),
        window_start=datetime(2026, 6, 1), window_end=datetime(2026, 7, 1),
        region="ap-south-1", instances=[_live_t4g_small()],
    )
    other = [r for r in rows if r.resource_id.startswith("ce-usage:") and
             "non-instance" in r.resource_id]
    assert len(other) == 1
    assert round(other[0].cost_usd, 2) == 0.48  # CPUCredits


# ---------------------------------------------------------------------------
# Bug 2 — EIP keeps its exact rate; EBS alone rescales to "EC2 - Other";
#          the VPC aggregate is reduced by what EIP rows already attribute
# ---------------------------------------------------------------------------

def _row(service, rid, cost, **attrs):
    return AttributedResource(
        service=service, resource_id=rid, name=rid, resource_type=service.lower(),
        state="active", cost_usd=cost, hours=0.0, region="ap-south-1",
        attributes=dict(attrs),
    )


def test_eip_not_rescaled_and_vpc_aggregate_reduced():
    from aws_cost_ultra.resources import runner as R

    buckets = {
        "EBS": [_row("EBS", "vol-1", 4.0), _row("EBS", "vol-2", 4.0)],
        "EIP": [_row("EIP", f"eip-{i}", 3.60) for i in range(6)],  # exact rate
    }
    totals = {
        "EC2 - Other": 6.0,                          # EBS pool (vols cost 8 raw)
        "Amazon Virtual Private Cloud": 31.35,       # includes the EIPs' 21.60
    }
    other_rows = R._reconcile_pools(buckets, totals, failed_services=set(),
                                    want=None, display_region="all")

    # EIP rows keep their exact $0.005/hr-derived cost — no pool squashing.
    assert all(round(r.cost_usd, 2) == 3.60 for r in buckets["EIP"])

    # EBS alone rescaled to the EC2-Other pool.
    assert round(sum(r.cost_usd for r in buckets["EBS"]), 2) == 6.0

    # VPC aggregate = 31.35 - 21.60 attributed via EIP rows.
    vpc = [r for r in other_rows if r.attributes.get("ce_service_name") ==
           "Amazon Virtual Private Cloud"]
    assert len(vpc) == 1
    assert round(vpc[0].cost_usd, 2) == round(31.35 - 21.60, 2)
    assert vpc[0].attributes.get("reduced_by_attributed_eip_usd")


def test_vpc_aggregate_dropped_when_eips_cover_it():
    from aws_cost_ultra.resources import runner as R

    buckets = {"EIP": [_row("EIP", "eip-1", 31.35)]}
    totals = {"Amazon Virtual Private Cloud": 31.35}
    other_rows = R._reconcile_pools(buckets, totals, failed_services=set(),
                                    want=None, display_region="all")
    assert not [r for r in other_rows if r.attributes.get("ce_service_name") ==
                "Amazon Virtual Private Cloud"]


def test_auto_assigned_public_ips_get_rows_at_exact_rate():
    from aws_cost_ultra.resources.eip import auto_assigned_ip_rows

    def inst(ip, state="running", launch=datetime(2026, 1, 1), iid="i-x"):
        return {"InstanceId": iid, "PublicIpAddress": ip,
                "State": {"Name": state}, "LaunchTime": launch}

    ws, we = datetime(2026, 6, 1), datetime(2026, 7, 1)
    rows = auto_assigned_ip_rows(
        [
            inst("1.1.1.1", iid="i-a"),                      # billable
            inst("2.2.2.2", iid="i-b"),                      # covered by an EIP
            inst("", iid="i-c"),                             # no public IP
            inst("3.3.3.3", state="stopped", iid="i-d"),     # not running
            inst("4.4.4.4", launch=datetime(2026, 7, 5), iid="i-e"),  # post-window
        ],
        "ap-south-1", ws, we, exclude_ips=frozenset({"2.2.2.2"}),
    )
    assert [r.resource_id for r in rows] == ["public-ip:1.1.1.1"]
    # Full June at the flat $0.005/hr public-IPv4 rate: 720h -> $3.60.
    assert round(rows[0].cost_usd, 2) == 3.60
    assert rows[0].service == "EIP"


# ---------------------------------------------------------------------------
# Bug 1 — report carries real counts, not capped-list lengths
# ---------------------------------------------------------------------------

def test_report_dict_has_real_counts_not_caps():
    from aws_cost_ultra.web.routes.export_api import _assemble_report

    services = [{"service": f"svc-{i}", "cost_usd": float(i + 1)} for i in range(30)]
    resources = [{"service": "EC2", "resource_id": f"r{i}", "cost": float(i)}
                 for i in range(80)]

    report = _assemble_report(
        profile="p", period="2026-06", total=123.45,
        services=services, raw_resources=resources,
        trend_points=[], budget_findings=[],
    )
    # Tables stay capped…
    assert len(report["top_services"]) == 25
    assert len(report["top_resources"]) == 50
    # …but the KPI counts reflect reality.
    assert report["services_count"] == 30
    assert report["resources_count"] == 80


# ---------------------------------------------------------------------------
# Remainder rows — when a service's attribution can't cover its CE total
# (rescale clamp tripped, empty inventory, unpriced classes), the difference
# must surface as a labelled remainder row, not vanish (EC2 got this fix
# first; generalize to every enumerated pool).
# ---------------------------------------------------------------------------

def _remainder_rows(other_rows, ce_name):
    return [r for r in other_rows if r.resource_id == f"ce-remainder:{ce_name}"]


def test_rds_rescale_clamp_skip_emits_remainder_row():
    from aws_cost_ultra.resources import runner as R

    # A db.r6g.large priced $0 by the fallback table: raw sum $15 vs CE $170
    # -> factor 11.3 > 5.0 -> rescale skipped. The missing $155 must appear.
    buckets = {"RDS": [_row("RDS", "db-small", 15.0)]}
    totals = {"Amazon Relational Database Service": 170.0}
    other_rows = R._reconcile_pools(buckets, totals, failed_services=set(),
                                    want=None, display_region="all")
    rem = _remainder_rows(other_rows, "Amazon Relational Database Service")
    assert len(rem) == 1
    assert round(rem[0].cost_usd, 2) == 155.0
    assert rem[0].attributes.get("aggregate") is True


def test_empty_inventory_emits_full_total_remainder():
    from aws_cost_ultra.resources import runner as R

    # Every DB deleted since the closed month: no rows at all -> the whole
    # CE total used to disappear from the Resources view.
    other_rows = R._reconcile_pools({}, {"Amazon Elastic Load Balancing": 17.44},
                                    failed_services=set(), want=None,
                                    display_region="all")
    rem = _remainder_rows(other_rows, "Amazon Elastic Load Balancing")
    assert len(rem) == 1
    assert round(rem[0].cost_usd, 2) == 17.44


def test_successful_rescale_emits_no_remainder():
    from aws_cost_ultra.resources import runner as R

    buckets = {"EBS": [_row("EBS", "vol-1", 4.0), _row("EBS", "vol-2", 4.0)]}
    totals = {"EC2 - Other": 12.0}  # factor 1.5, in band -> rescale runs
    other_rows = R._reconcile_pools(buckets, totals, failed_services=set(),
                                    want=None, display_region="all")
    assert round(sum(r.cost_usd for r in buckets["EBS"]), 2) == 12.0
    assert not _remainder_rows(other_rows, "EC2 - Other")


def test_ec2_other_pool_gap_surfaces_as_remainder():
    from aws_cost_ultra.resources import runner as R

    # NAT gateways ($43) share the pool with volumes ($8 raw): factor 6.4
    # trips the clamp; volumes keep raw cost and the pool gap must surface.
    buckets = {"EBS": [_row("EBS", "vol-1", 8.0)]}
    totals = {"EC2 - Other": 51.0}
    other_rows = R._reconcile_pools(buckets, totals, failed_services=set(),
                                    want=None, display_region="all")
    rem = _remainder_rows(other_rows, "EC2 - Other")
    assert len(rem) == 1
    assert round(rem[0].cost_usd, 2) == 43.0


# ---------------------------------------------------------------------------
# Lambda/DynamoDB cross-region split — each region must split ITS OWN CE
# total, not an equal 1/N share of the account-wide bill.
# ---------------------------------------------------------------------------

class _FakeCeRegional:
    """CE response grouped by [SERVICE, REGION]."""

    def get_cost_and_usage(self, **kwargs):
        return {
            "ResultsByTime": [{
                "Groups": [
                    {"Keys": ["AWS Lambda", "us-east-1"],
                     "Metrics": {"UnblendedCost": {"Amount": "99.999"}}},
                    {"Keys": ["AWS Lambda", "ap-south-1"],
                     "Metrics": {"UnblendedCost": {"Amount": "0.001"}}},
                    {"Keys": ["Amazon DynamoDB", "us-east-1"],
                     "Metrics": {"UnblendedCost": {"Amount": "40.0"}}},
                ],
            }],
        }


def test_service_region_totals_maps_service_region_pairs():
    from datetime import datetime
    from aws_cost_ultra.resources import runner as R
    from aws_cost_ultra.core.filters import pre_credit_gross

    totals = R._service_region_totals(
        _FakeCeRegional(), datetime(2026, 6, 1), datetime(2026, 7, 1),
        pre_credit_gross(), ["AWS Lambda", "Amazon DynamoDB"],
    )
    assert totals[("AWS Lambda", "us-east-1")] == 99.999
    assert totals[("AWS Lambda", "ap-south-1")] == 0.001
    assert totals[("Amazon DynamoDB", "us-east-1")] == 40.0


def test_region_scoped_lambda_rows_are_not_renormalized():
    from aws_cost_ultra.resources import runner as R

    # Region-scoped totals: us-east-1 carries $99.999, ap-south-1 $0.001.
    buckets = {"Lambda": [
        _row("Lambda", "fn-use1", 99.999),
        _row("Lambda", "fn-aps3", 0.001),
    ]}
    totals = {"AWS Lambda": 100.0}
    R._reconcile_pools(buckets, totals, failed_services=set(), want=None,
                       display_region="all", lambda_ddb_region_scoped=True)
    # The old account-wide normalization would have forced each region to
    # exactly half: fn-aps3 at $50. Region-scoped rows must stay as-is.
    by_id = {r.resource_id: r.cost_usd for r in buckets["Lambda"]}
    assert round(by_id["fn-aps3"], 3) == 0.001
    assert round(by_id["fn-use1"], 3) == 99.999


def test_unscoped_lambda_rows_still_normalize_to_ce_total():
    from aws_cost_ultra.resources import runner as R

    # Fallback path (regional CE call failed): two regions each split the
    # full $100 -> raw sum $200 -> normalize back to $100.
    buckets = {"Lambda": [_row("Lambda", "fn-a", 100.0),
                          _row("Lambda", "fn-b", 100.0)]}
    totals = {"AWS Lambda": 100.0}
    R._reconcile_pools(buckets, totals, failed_services=set(), want=None,
                       display_region="all", lambda_ddb_region_scoped=False)
    assert round(sum(r.cost_usd for r in buckets["Lambda"]), 2) == 100.0


# ---------------------------------------------------------------------------
# RDS pricing — Pricing API wired in; stopped instances still bill storage;
# Multi-AZ doubles; billing states beyond "available" earn instance hours.
# ---------------------------------------------------------------------------

def test_rds_instance_rate_uses_pricing_api(monkeypatch):
    from aws_cost_ultra.core import pricing

    monkeypatch.setattr(pricing, "_fetch_from_api", lambda *a, **k: 0.353)
    rate = pricing.rds_instance_rate(None, "db.r6g.large", "postgres", "us-east-1")
    assert rate == 0.353


def test_rds_instance_rate_falls_back_when_api_empty(monkeypatch):
    from aws_cost_ultra.core import pricing

    monkeypatch.setattr(pricing, "_fetch_from_api", lambda *a, **k: None)
    rate = pricing.rds_instance_rate(None, "db.t3.micro", "mysql", "eu-west-9")
    assert rate == 0.021  # fallback table


def _db(state="available", multi_az=False, storage_gb=500, cls="db.m5.large"):
    return {
        "DBInstanceIdentifier": "db-1",
        "DBInstanceClass": cls,
        "Engine": "postgres",
        "DBInstanceStatus": state,
        "InstanceCreateTime": datetime(2026, 1, 1),
        "AllocatedStorage": storage_gb,
        "StorageType": "gp2",
        "MultiAZ": multi_az,
        "TagList": [],
    }


def test_stopped_rds_still_bills_storage():
    from aws_cost_ultra.resources.rds import _row_for_db

    row = _row_for_db(
        _db(state="stopped"), "ap-south-1",
        datetime(2026, 6, 1), datetime(2026, 7, 1),
        inst_rate=0.2, storage_rate=0.138,
    )
    # No instance hours, but 500 GB gp2 storage bills the full window:
    # 500 * 0.138 * (720/730) ≈ $68.05 — the old code showed $0.00.
    assert row.hours == 0.0
    assert round(row.cost_usd, 1) == round(500 * 0.138 * (720 / 730.0), 1)


def test_backing_up_rds_earns_instance_hours():
    from aws_cost_ultra.resources.rds import _row_for_db

    row = _row_for_db(
        _db(state="backing-up"), "ap-south-1",
        datetime(2026, 6, 1), datetime(2026, 7, 1),
        inst_rate=0.2, storage_rate=0.138,
    )
    assert row.hours > 0  # only "stopped"/"stopping" suspend instance billing


def test_multi_az_rds_doubles_instance_and_storage():
    from aws_cost_ultra.resources.rds import _row_for_db

    single = _row_for_db(_db(), "ap-south-1",
                         datetime(2026, 6, 1), datetime(2026, 7, 1),
                         inst_rate=0.2, storage_rate=0.138)
    double = _row_for_db(_db(multi_az=True), "ap-south-1",
                         datetime(2026, 6, 1), datetime(2026, 7, 1),
                         inst_rate=0.2, storage_rate=0.138)
    assert round(double.cost_usd, 2) == round(single.cost_usd * 2, 2)


def test_region_to_location_covers_newer_regions():
    from aws_cost_ultra.core.pricing import _region_to_location

    assert _region_to_location("eu-north-1") == "EU (Stockholm)"
    assert _region_to_location("ap-southeast-3") == "Asia Pacific (Jakarta)"
    assert _region_to_location("il-central-1") == "Israel (Tel Aviv)"


# ---------------------------------------------------------------------------
# Region filter — the Resources page's primary path ignored ?region= and
# served (and cached) account-wide data under the region-scoped cache key.
# ---------------------------------------------------------------------------

class _FakeCur:
    def has_data(self, account_id, window):
        return True

    def attribute_resources(self, account_id, window):
        return [{"resource_id": "cur-row", "name": "cur-row", "service": "EC2",
                 "tags": {}, "cost": 1.0, "usage_amount": None}]


class _FakeCeStore:
    def __init__(self):
        self.calls = []

    def attribute_resources_via_describe(self, account_id, window, *, session,
                                         spec, errors=None, region="all"):
        self.calls.append(region)
        return [{"resource_id": f"describe-{region}", "name": "x", "service": "EC2",
                 "tags": {}, "cost": 2.0, "usage_amount": None}]


def test_cost_source_passes_region_to_describe_path():
    from aws_cost_ultra.aws.cost_source import CostSource

    ce = _FakeCeStore()
    src = CostSource(cur_store=None, cost_store=ce)
    src.attribute_resources("123", None, session=None, spec=None, region="us-east-1")
    assert ce.calls == ["us-east-1"]


def test_cost_source_skips_cur_for_region_scoped_requests():
    from aws_cost_ultra.aws.cost_source import CostSource

    ce = _FakeCeStore()
    src = CostSource(cur_store=_FakeCur(), cost_store=ce)
    # CUR rows carry no region -> a region-filtered request must use describe.
    rows = src.attribute_resources("123", None, session=None, spec=None,
                                   region="us-east-1")
    assert rows[0]["resource_id"] == "describe-us-east-1"
    # Account-wide requests still prefer CUR.
    rows_all = src.attribute_resources("123", None, session=None, spec=None,
                                       region="all")
    assert rows_all[0]["resource_id"] == "cur-row"


# ---------------------------------------------------------------------------
# Planned budgets — PlannedBudgetLimits is keyed by epoch-second period-start
# strings, never "MONTHLY"; the old lookup dropped every planned budget.
# ---------------------------------------------------------------------------

def test_planned_budget_limit_picks_current_period():
    from aws_cost_ultra.audit.budgets import _budget_limit

    # Periods starting Jun 1 and Jul 1 2026 (epoch seconds, as AWS returns).
    planned = {
        "1780272000": {"Amount": "300.0", "Unit": "USD"},  # Jul 1 2026
        "1777680000": {"Amount": "200.0", "Unit": "USD"},  # Jun 1 2026
    }
    amount, unit = _budget_limit({"PlannedBudgetLimits": planned},
                                 now_epoch=1780358400)  # Jul 2 2026
    assert amount == 300.0
    assert unit == "USD"


def test_planned_budget_before_first_period_uses_earliest():
    from aws_cost_ultra.audit.budgets import _budget_limit

    planned = {"1780272000": {"Amount": "300.0", "Unit": "USD"}}
    amount, unit = _budget_limit({"PlannedBudgetLimits": planned},
                                 now_epoch=1000)  # long before the plan starts
    assert amount == 300.0


def test_fixed_budget_limit_still_wins():
    from aws_cost_ultra.audit.budgets import _budget_limit

    amount, unit = _budget_limit(
        {"BudgetLimit": {"Amount": "50", "Unit": "USD"},
         "PlannedBudgetLimits": {"1780272000": {"Amount": "300.0", "Unit": "USD"}}},
        now_epoch=1780358400,
    )
    assert amount == 50.0


# ---------------------------------------------------------------------------
# Audit waste estimates — stopped EC2/RDS showed $0.00 while the finding text
# itself said charges continue; EBS used a flat $0.10/GB for every type.
# ---------------------------------------------------------------------------

def test_ebs_monthly_estimate_is_type_aware():
    from aws_cost_ultra.audit.idle import _ebs_monthly_estimate

    assert round(_ebs_monthly_estimate(100, "gp3", 3000), 2) == 8.0
    assert round(_ebs_monthly_estimate(1024, "sc1", 0), 2) == round(1024 * 0.015, 2)
    # io2 100 GB with 10,000 provisioned IOPS: storage + IOPS, not $10 flat.
    est = _ebs_monthly_estimate(100, "io2", 10_000)
    assert est > 600  # ~ $12.5 storage + ~$650 IOPS
    # gp3 provisioned IOPS above the 3000 baseline bill extra.
    assert _ebs_monthly_estimate(100, "gp3", 5000) > _ebs_monthly_estimate(100, "gp3", 3000)


def test_stopped_rds_estimate_bills_storage():
    from aws_cost_ultra.audit.idle import _rds_stopped_estimate

    assert round(_rds_stopped_estimate(500, 0.138, multi_az=False), 2) == 69.0
    assert round(_rds_stopped_estimate(500, 0.138, multi_az=True), 2) == 138.0


def test_idle_eip_estimate_uses_730_hours():
    from aws_cost_ultra.audit.idle import _EIP_MONTHLY_USD

    assert _EIP_MONTHLY_USD == round(730 * 0.005, 2)  # 3.65, not 3.60
