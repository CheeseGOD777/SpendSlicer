"""Smoke tests — package imports and basic sanity."""

from __future__ import annotations


def test_package_imports():
    import spendslicer
    assert spendslicer.__version__


def test_core_imports():
    from spendslicer.core import pricing, provenance, service_groups, types
    assert pricing.FALLBACK_RATES["ec2"]
    assert types.CostMetric.UNBLENDED.value == "UnblendedCost"
    assert provenance.VARIANCE_WARN_THRESHOLD_PCT == 1.0
    assert service_groups.EC2_DISPLAY_NAME


def test_aws_layer_imports():
    from spendslicer.aws import session
    from spendslicer.resources.ec2 import attribute_ec2, attribute_ec2_account
    assert callable(session.make_session)
    assert callable(session.list_profiles)
    assert callable(attribute_ec2)
    assert callable(attribute_ec2_account)


def test_resources_imports():
    from spendslicer.resources import enumerate_all
    from spendslicer.resources.runner import ALL_REGIONS
    assert callable(enumerate_all)
    assert ALL_REGIONS == "all"


def test_time_window_validation():
    from datetime import datetime, timedelta, timezone

    import pytest

    from spendslicer.core.types import TimeWindow

    now = datetime.now(tz=timezone.utc)
    w = TimeWindow(start=now - timedelta(days=7), end=now)
    start_s, end_s = w.iso()
    assert len(start_s) == 10 and len(end_s) == 10

    with pytest.raises(ValueError):
        TimeWindow(start=now, end=now - timedelta(days=1))

    with pytest.raises(ValueError):
        TimeWindow(start=datetime(2024, 1, 1), end=datetime(2024, 1, 2))


def test_merge_ec2_groups():
    from datetime import datetime, timedelta, timezone

    from spendslicer.aws.cost_explorer import GroupedCost
    from spendslicer.core.provenance import CostValue, Provenance
    from spendslicer.core.service_groups import merge_ec2_service_groups
    from spendslicer.core.types import CostMetric, TimeWindow

    now = datetime.now(tz=timezone.utc)
    window = TimeWindow(start=now - timedelta(days=30), end=now)
    prov = Provenance(source="cost_explorer", metric=CostMetric.UNBLENDED, window=window)

    groups = [
        GroupedCost(
            key=("Amazon Elastic Compute Cloud - Compute",),
            value=CostValue(amount_usd=10.0, provenance=prov),
        ),
        GroupedCost(
            key=("EC2 - Other",),
            value=CostValue(amount_usd=5.0, provenance=prov),
        ),
        GroupedCost(key=("Amazon S3",), value=CostValue(amount_usd=1.0, provenance=prov)),
    ]
    merged = merge_ec2_service_groups(groups)
    names = [g.primary_key() for g in merged]
    assert "Amazon Elastic Compute Cloud" in names
    assert "Amazon Elastic Compute Cloud - Compute" not in names
    ec2_row = next(g for g in merged if g.primary_key() == "Amazon Elastic Compute Cloud")
    assert ec2_row.value.amount_usd == 15.0
