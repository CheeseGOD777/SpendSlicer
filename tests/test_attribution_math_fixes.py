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
