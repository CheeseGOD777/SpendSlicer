"""Pure-math checks for the services added beyond the original eight.

Each enumerator's row builder is deliberately free of boto3 so the pricing
arithmetic can be tested directly.
"""

from __future__ import annotations

from datetime import datetime, timezone

from spendslicer.resources.efs import _row_for_fs
from spendslicer.resources.elasticache import _row_for_cluster
from spendslicer.resources.natgateway import _row_for_nat
from spendslicer.resources.route53 import _row_for_zone
from spendslicer.resources.secretsmanager import _row_for_secret

WS = datetime(2026, 8, 1, tzinfo=timezone.utc)
WE = datetime(2026, 8, 31, tzinfo=timezone.utc)   # 720 hours
HOURS = 720.0


def test_elasticache_multiplies_by_node_count():
    row = _row_for_cluster(
        {"CacheClusterId": "cache-1", "CacheNodeType": "cache.t3.micro",
         "NumCacheNodes": 3, "CacheClusterStatus": "available",
         "CacheClusterCreateTime": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        "ap-south-1", WS, WE, 0.018)
    assert row.cost_usd == 3 * HOURS * 0.018
    assert row.hours == HOURS


def test_elasticache_deleting_cluster_does_not_bill():
    row = _row_for_cluster(
        {"CacheClusterId": "c", "CacheNodeType": "cache.t3.micro", "NumCacheNodes": 1,
         "CacheClusterStatus": "deleting",
         "CacheClusterCreateTime": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        "ap-south-1", WS, WE, 0.018)
    assert row.cost_usd == 0.0


def test_nat_gateway_charges_hourly_and_names_itself():
    row = _row_for_nat(
        {"NatGatewayId": "nat-abc", "State": "available",
         "CreateTime": datetime(2026, 1, 1, tzinfo=timezone.utc),
         "VpcId": "vpc-1", "SubnetId": "subnet-1",
         "Tags": [{"Key": "Name", "Value": "egress"}],
         "NatGatewayAddresses": [{"PublicIp": "1.2.3.4"}]},
        "ap-south-1", WS, WE, 0.045)
    assert row.cost_usd == HOURS * 0.045
    assert row.name == "egress"
    # The row must not imply it covers per-GB processing.
    assert "data processing" in row.attributes["cost_basis"]


def test_secret_is_prorated_not_charged_a_full_month():
    """A secret created mid-window bills for the part of the window it existed."""
    half = _row_for_secret(
        {"Name": "s", "ARN": "arn:s", "CreatedDate": datetime(2026, 8, 16, tzinfo=timezone.utc)},
        "ap-south-1", WS, WE, 0.40)
    full = _row_for_secret(
        {"Name": "s", "ARN": "arn:s", "CreatedDate": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        "ap-south-1", WS, WE, 0.40)
    assert full.cost_usd > half.cost_usd
    assert abs(full.cost_usd - 0.40 * (HOURS / 730.0)) < 1e-9


def test_efs_prices_standard_tier_only():
    row = _row_for_fs(
        {"FileSystemId": "fs-1", "Name": "shared",
         "SizeInBytes": {"ValueInStandard": 100 * 1024 ** 3, "ValueInIA": 50 * 1024 ** 3},
         "CreationTime": datetime(2026, 1, 1, tzinfo=timezone.utc),
         "LifeCycleState": "available"},
        "ap-south-1", WS, WE, 0.33)
    assert abs(row.cost_usd - 100 * 0.33 * (HOURS / 730.0)) < 1e-6
    assert row.attributes["size_gb_infrequent_access"] == 50.0


def test_route53_zone_is_global_not_regional():
    row = _row_for_zone(
        {"Id": "/hostedzone/Z123", "Name": "example.com.",
         "ResourceRecordSetCount": 12, "Config": {"PrivateZone": False}},
        HOURS, 0.50)
    assert row.resource_id == "Z123"
    # Region must be "global": a per-region label would let the same zone be
    # counted once per region in a multi-region scan.
    assert row.region == "global"
    assert abs(row.cost_usd - 0.50 * (HOURS / 730.0)) < 1e-9


def test_nat_gateway_is_netted_off_the_shared_ec2_other_pool():
    """NAT and EBS share the "EC2 - Other" CE pool.

    NAT is priced exactly and not rescaled, so if the pool is not reduced by
    what NAT claims, EBS rescales up to the full pool and the NAT rows add
    their cost on top — over-attributing the whole gateway bill.
    """
    from spendslicer.resources.base import AttributedResource
    from spendslicer.resources.runner import _reconcile_pools

    def row(service, cost):
        return AttributedResource(
            service=service, resource_id=f"{service}-1", name=service,
            resource_type="t", state="available", cost_usd=cost, hours=0.0,
            region="ap-south-1")

    buckets = {"EBS": [row("EBS", 10.0)], "NATGateway": [row("NATGateway", 30.0)]}
    _reconcile_pools(buckets, {"EC2 - Other": 40.0}, set(), None, "ap-south-1")

    ebs = sum(r.cost_usd for r in buckets["EBS"])
    nat = sum(r.cost_usd for r in buckets["NATGateway"])
    assert nat == 30.0, "NAT is priced exactly and must not be rescaled"
    assert abs(ebs - 10.0) < 1e-6, f"EBS should fill only the remaining pool, got {ebs}"
    assert abs((ebs + nat) - 40.0) < 0.01, "pool must not be over-attributed"
