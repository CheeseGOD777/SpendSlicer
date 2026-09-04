"""Phase 4 — audit engine: untagged, idle, budgets, runner."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from costsight.audit.budgets import BudgetStatus, get_budget_findings
from costsight.audit.idle import (
    find_idle_resources,
    find_stopped_ec2,
    find_unattached_ebs,
    find_unused_eips,
)
from costsight.audit.runner import AuditResult, run_audit
from costsight.audit.untagged import scan_untagged

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# Untagged scanner
# ---------------------------------------------------------------------------

def test_scan_untagged_returns_empty_when_no_required_tags():
    result = scan_untagged(_session(), "us-east-1", required_tags=[])
    assert result == []


def test_scan_ec2_flags_missing_tags():
    session = _session()
    ec2_client = MagicMock()
    session.client.return_value = ec2_client
    ec2_client.get_paginator.return_value.paginate.return_value = [
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-abc123",
                            "State": {"Name": "running"},
                            "InstanceType": "t3.micro",
                            "Tags": [{"Key": "Name", "Value": "web-server"}],
                            # Missing "Team" and "CostCenter"
                        }
                    ]
                }
            ]
        }
    ]

    from costsight.audit.untagged import scan_ec2
    results = scan_ec2(session, "us-east-1", ["Name", "Team", "CostCenter"])
    assert len(results) == 1
    assert results[0].resource_id == "i-abc123"
    assert "Team" in results[0].missing_tags
    assert "CostCenter" in results[0].missing_tags
    assert "Name" not in results[0].missing_tags


def test_scan_ec2_skips_terminated_instances():
    session = _session()
    ec2_client = MagicMock()
    session.client.return_value = ec2_client
    ec2_client.get_paginator.return_value.paginate.return_value = [
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-dead",
                            "State": {"Name": "terminated"},
                            "InstanceType": "t3.micro",
                            "Tags": [],
                        }
                    ]
                }
            ]
        }
    ]

    from costsight.audit.untagged import scan_ec2
    results = scan_ec2(session, "us-east-1", ["Team"])
    assert results == []


# ---------------------------------------------------------------------------
# Idle resources
# ---------------------------------------------------------------------------

def test_find_stopped_ec2_identifies_stopped_instances():
    session = _session()
    ec2_client = MagicMock()
    session.client.return_value = ec2_client
    ec2_client.get_paginator.return_value.paginate.return_value = [
        {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-stopped",
                            "InstanceType": "m5.large",
                            "State": {"Name": "stopped"},
                            "Placement": {"AvailabilityZone": "us-east-1a"},
                            "StateTransitionReason": "User initiated stop",
                            "Tags": [{"Key": "Name", "Value": "my-server"}],
                        }
                    ]
                }
            ]
        }
    ]
    results = find_stopped_ec2(session, "us-east-1")
    assert len(results) == 1
    assert results[0].resource_id == "i-stopped"
    assert results[0].service == "EC2"
    assert "stopped" in results[0].reason.lower()


def test_find_unattached_ebs_returns_available_volumes():
    session = _session()
    ec2_client = MagicMock()
    session.client.return_value = ec2_client
    ec2_client.get_paginator.return_value.paginate.return_value = [
        {
            "Volumes": [
                {
                    "VolumeId": "vol-orphan",
                    "Size": 100,
                    "VolumeType": "gp2",
                    "State": "available",
                    "CreateTime": "2025-01-01",
                    "Tags": [],
                }
            ]
        }
    ]
    results = find_unattached_ebs(session, "us-east-1")
    assert len(results) == 1
    assert results[0].resource_id == "vol-orphan"
    # 100 GB * $0.10 = $10/month estimate
    assert results[0].estimated_monthly_cost_usd == pytest.approx(10.0)


def test_find_unused_eips_returns_unassociated():
    session = _session()
    ec2_client = MagicMock()
    session.client.return_value = ec2_client
    ec2_client.describe_addresses.return_value = {
        "Addresses": [
            {"AllocationId": "eipalloc-abc", "PublicIp": "1.2.3.4"},  # no AssociationId
            {"AllocationId": "eipalloc-xyz", "PublicIp": "5.6.7.8", "AssociationId": "eipassoc-111"},
        ]
    }
    results = find_unused_eips(session, "us-east-1")
    assert len(results) == 1
    assert results[0].resource_id == "eipalloc-abc"
    # ~730 h/month at the $0.005/hr public-IPv4 rate (was 720h/$3.60).
    assert results[0].estimated_monthly_cost_usd == pytest.approx(3.65)


def test_find_idle_resources_empty_checks_returns_empty():
    result = find_idle_resources(_session(), "us-east-1", checks=[])
    assert result == []


# ---------------------------------------------------------------------------
# Budget findings
# ---------------------------------------------------------------------------

def test_get_budget_findings_returns_empty_when_no_account():
    session = _session()
    session.client.return_value.get_caller_identity.side_effect = Exception("no sts")
    results = get_budget_findings(session)
    assert results == []


def test_budget_status_breached_when_actual_exceeds_limit():
    session = _session()
    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}
    budgets_client = MagicMock()
    budgets_client.get_paginator.return_value.paginate.return_value = [
        {
            "Budgets": [
                {
                    "BudgetName": "monthly-cap",
                    "BudgetType": "COST",
                    "TimeUnit": "MONTHLY",
                    "BudgetLimit": {"Amount": "100", "Unit": "USD"},
                    "CalculatedSpend": {
                        "ActualSpend": {"Amount": "120"},
                        "ForecastedSpend": {"Amount": "150"},
                    },
                }
            ]
        }
    ]

    def mock_client(service, **kwargs):
        if service == "sts":
            return sts
        return budgets_client

    session.client.side_effect = mock_client

    results = get_budget_findings(session)
    assert len(results) == 1
    assert results[0].status == BudgetStatus.BREACHED
    assert results[0].actual_spend == pytest.approx(120.0)


def test_budget_status_warning_at_threshold():
    session = _session()
    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}
    budgets_client = MagicMock()
    budgets_client.get_paginator.return_value.paginate.return_value = [
        {
            "Budgets": [
                {
                    "BudgetName": "dev-budget",
                    "BudgetType": "COST",
                    "TimeUnit": "MONTHLY",
                    "BudgetLimit": {"Amount": "100", "Unit": "USD"},
                    "CalculatedSpend": {
                        "ActualSpend": {"Amount": "85"},
                        "ForecastedSpend": {"Amount": "90"},
                    },
                }
            ]
        }
    ]

    def mock_client(service, **kwargs):
        if service == "sts":
            return sts
        return budgets_client

    session.client.side_effect = mock_client

    results = get_budget_findings(session, warn_at_pct=80.0)
    assert results[0].status == BudgetStatus.WARNING


def test_budget_status_ok_below_threshold():
    session = _session()
    sts = MagicMock()
    sts.get_caller_identity.return_value = {"Account": "123456789012"}
    budgets_client = MagicMock()
    budgets_client.get_paginator.return_value.paginate.return_value = [
        {
            "Budgets": [
                {
                    "BudgetName": "safe",
                    "BudgetType": "COST",
                    "TimeUnit": "MONTHLY",
                    "BudgetLimit": {"Amount": "100", "Unit": "USD"},
                    "CalculatedSpend": {
                        "ActualSpend": {"Amount": "40"},
                        "ForecastedSpend": {"Amount": "55"},
                    },
                }
            ]
        }
    ]

    def mock_client(service, **kwargs):
        if service == "sts":
            return sts
        return budgets_client

    session.client.side_effect = mock_client

    results = get_budget_findings(session, warn_at_pct=80.0)
    assert results[0].status == BudgetStatus.OK


# ---------------------------------------------------------------------------
# Audit runner
# ---------------------------------------------------------------------------

def test_run_audit_returns_audit_result():
    session = _session()
    # Mock all AWS calls to return empty
    mock_client = MagicMock()
    mock_client.get_paginator.return_value.paginate.return_value = []
    mock_client.describe_addresses.return_value = {"Addresses": []}
    mock_client.get_caller_identity.return_value = {"Account": "123456789012"}
    session.client.return_value = mock_client

    result = run_audit(
        session=session,
        profile="test",
        account_id="123456789012",
        regions=["us-east-1"],
        required_tags=["Team"],
        budget_warn_at_pct=80.0,
    )
    assert isinstance(result, AuditResult)
    assert result.profile == "test"
    assert "us-east-1" in result.regions_scanned


def test_audit_result_to_dict_has_summary_keys():
    result = AuditResult(
        profile="prod", account_id="111111111111", regions_scanned=["us-east-1"]
    )
    d = result.to_dict()
    assert "summary" in d
    assert "untagged_count" in d["summary"]
    assert "idle_count" in d["summary"]
    assert "estimated_waste_usd_monthly" in d["summary"]
