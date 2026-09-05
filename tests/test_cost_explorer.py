"""CE wrapper tests — verify provenance is populated and the default filter
matches the AWS Billing Console (all record types included).

These tests use ``unittest.mock`` to stub boto3 rather than moto, because
moto's CE coverage is sparse. We assert both on the returned values and
on the exact kwargs passed to ``get_cost_and_usage`` — so a future
change that silently drops Credit/Refund from the default will fail
here loudly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from spendslicer.aws.cost_explorer import CostExplorerClient
from spendslicer.core.filters import (
    CostFilterSpec,
    pre_credit_gross,
)
from spendslicer.core.types import CostMetric, Granularity, TimeWindow


def _window(days: int = 7) -> TimeWindow:
    now = datetime.now(tz=timezone.utc)
    return TimeWindow(start=now - timedelta(days=days), end=now)


def _fake_client_with(response: dict) -> MagicMock:
    client = MagicMock()
    client.get_cost_and_usage.return_value = response
    return client


# ---------------------------------------------------------------------------
# Defaults match AWS Billing Console
# ---------------------------------------------------------------------------

def test_default_filter_is_console_matching_no_record_type_filter():
    """Default call must NOT filter out any record types.

    This is the accuracy-critical invariant: the legacy tool excluded
    Credit/Refund/Upfront by default which made numbers diverge from
    the console. The new default must include all record types.
    """
    client = _fake_client_with(
        {"ResultsByTime": [{"TimePeriod": {"Start": "2026-03-01", "End": "2026-04-01"},
                            "Total": {"UnblendedCost": {"Amount": "42.50", "Unit": "USD"}},
                            "Groups": []}]}
    )
    ce = CostExplorerClient(session=MagicMock(), ce_client=client)
    result = ce.get_total_cost(_window(30))

    call_kwargs = client.get_cost_and_usage.call_args.kwargs
    # No Filter must be passed when spec is default:
    assert "Filter" not in call_kwargs
    assert call_kwargs["Metrics"] == ["UnblendedCost"]
    assert result.amount_usd == pytest.approx(42.50)
    # Provenance says nothing was excluded
    assert result.provenance.excluded_record_types in (None, ())
    assert "UnblendedCost" in result.provenance.label()


def test_pre_credit_gross_preset_excludes_credits_refunds_upfront():
    client = _fake_client_with(
        {"ResultsByTime": [{"TimePeriod": {"Start": "2026-03-01", "End": "2026-04-01"},
                            "Total": {"UnblendedCost": {"Amount": "100.00"}}, "Groups": []}]}
    )
    ce = CostExplorerClient(session=MagicMock(), ce_client=client)
    result = ce.get_total_cost(_window(30), spec=pre_credit_gross())

    filt = client.get_cost_and_usage.call_args.kwargs["Filter"]
    assert filt == {
        "Not": {
            "Dimensions": {
                "Key": "RECORD_TYPE",
                "Values": ["Credit", "Refund", "Upfront"],
            }
        }
    }
    # Label must expose the exclusion so UI can warn the user
    assert "Credit" in result.provenance.label()


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

def test_group_by_service_aggregates_across_buckets_and_sorts_desc():
    response = {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2026-03-01", "End": "2026-03-02"},
                "Groups": [
                    {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "10.00"}}},
                    {"Keys": ["Amazon S3"], "Metrics": {"UnblendedCost": {"Amount": "2.00"}}},
                ],
            },
            {
                "TimePeriod": {"Start": "2026-03-02", "End": "2026-03-03"},
                "Groups": [
                    {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "15.00"}}},
                    {"Keys": ["Amazon S3"], "Metrics": {"UnblendedCost": {"Amount": "3.00"}}},
                ],
            },
        ]
    }
    client = _fake_client_with(response)
    ce = CostExplorerClient(session=MagicMock(), ce_client=client)
    groups = ce.get_cost_by_service(_window(2), granularity=Granularity.DAILY)

    assert [g.primary_key() for g in groups] == ["Amazon EC2", "Amazon S3"]
    assert groups[0].value.amount_usd == pytest.approx(25.0)
    assert groups[1].value.amount_usd == pytest.approx(5.0)
    # Provenance captures the group_by dimension for debugging later
    assert groups[0].value.provenance.group_by == ("DIMENSION:SERVICE",)


def test_group_by_tag_key_passed_through():
    response = {"ResultsByTime": [{"TimePeriod": {"Start": "2026-03-01", "End": "2026-04-01"},
                                    "Groups": [{"Keys": ["Team$DevOps"],
                                               "Metrics": {"UnblendedCost": {"Amount": "7.00"}}}]}]}
    client = _fake_client_with(response)
    ce = CostExplorerClient(session=MagicMock(), ce_client=client)
    groups = ce.get_cost_by_tag(_window(30), tag_key="Team")

    call_kwargs = client.get_cost_and_usage.call_args.kwargs
    assert call_kwargs["GroupBy"] == [{"Type": "TAG", "Key": "Team"}]
    assert groups[0].primary_key() == "Team$DevOps"


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def test_pagination_follows_next_page_token():
    page1 = {
        "ResultsByTime": [{"TimePeriod": {"Start": "2026-03-01", "End": "2026-03-02"},
                           "Groups": [{"Keys": ["A"], "Metrics": {"UnblendedCost": {"Amount": "1"}}}]}],
        "NextPageToken": "tok",
    }
    page2 = {
        "ResultsByTime": [{"TimePeriod": {"Start": "2026-03-02", "End": "2026-03-03"},
                           "Groups": [{"Keys": ["A"], "Metrics": {"UnblendedCost": {"Amount": "2"}}}]}],
    }
    client = MagicMock()
    client.get_cost_and_usage.side_effect = [page1, page2]
    ce = CostExplorerClient(session=MagicMock(), ce_client=client)

    groups = ce.get_cost_by_service(_window(2), granularity=Granularity.DAILY)

    assert client.get_cost_and_usage.call_count == 2
    assert groups[0].value.amount_usd == pytest.approx(3.0)
    second_call = client.get_cost_and_usage.call_args_list[1].kwargs
    assert second_call.get("NextPageToken") == "tok"


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------

def test_get_trend_returns_one_point_per_bucket_with_provenance():
    response = {
        "ResultsByTime": [
            {"TimePeriod": {"Start": "2025-11-01", "End": "2025-12-01"},
             "Total": {"UnblendedCost": {"Amount": "100"}}, "Groups": []},
            {"TimePeriod": {"Start": "2025-12-01", "End": "2026-01-01"},
             "Total": {"UnblendedCost": {"Amount": "120"}}, "Groups": []},
        ]
    }
    client = _fake_client_with(response)
    ce = CostExplorerClient(session=MagicMock(), ce_client=client)
    points = ce.get_trend(_window(60), granularity=Granularity.MONTHLY)
    assert len(points) == 2
    assert points[0].period_start == "2025-11-01"
    assert points[0].value.amount_usd == pytest.approx(100.0)
    assert points[1].value.amount_usd == pytest.approx(120.0)
    # Every point carries full provenance
    for p in points:
        assert p.value.provenance.metric == CostMetric.UNBLENDED
        assert p.value.provenance.source == "cost_explorer"


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------

def test_get_forecast_wraps_response_with_provenance_source_forecast():
    session = MagicMock()
    ce_client = MagicMock()
    ce_client.get_cost_forecast.return_value = {"Total": {"Amount": "500.25", "Unit": "USD"}}
    ce = CostExplorerClient(session=session, ce_client=ce_client)

    v = ce.get_forecast(_window(15))
    assert v is not None
    assert v.amount_usd == pytest.approx(500.25)
    assert v.provenance.source == "forecast"


def test_get_forecast_returns_none_on_data_unavailable():
    # CE legitimately can't forecast (too little history) -> None, which callers
    # may safely cache as "no forecast".
    class DataUnavailableException(Exception):
        pass

    ce_client = MagicMock()
    ce_client.get_cost_forecast.side_effect = DataUnavailableException("insufficient data")
    ce = CostExplorerClient(session=MagicMock(), ce_client=ce_client)
    assert ce.get_forecast(_window(15)) is None


def test_get_forecast_reraises_transient_error():
    # A transient failure (throttle/timeout) must NOT be swallowed as None —
    # re-raise so the caller avoids caching a blank forecast for the whole TTL.
    import pytest

    ce_client = MagicMock()
    ce_client.get_cost_forecast.side_effect = Exception("ThrottlingException")
    ce = CostExplorerClient(session=MagicMock(), ce_client=ce_client)
    with pytest.raises(Exception, match="ThrottlingException"):
        ce.get_forecast(_window(15))


# ---------------------------------------------------------------------------
# Filter composition
# ---------------------------------------------------------------------------

def test_composite_filter_service_plus_tag_plus_exclude_record_types():
    spec = CostFilterSpec(
        service="Amazon EC2",
        tags=(("Team", "DevOps"),),
        excluded_record_types=("Credit",),
    )
    client = _fake_client_with({"ResultsByTime": [{"TimePeriod":{"Start":"2026-03-01","End":"2026-04-01"},
                                                     "Total":{"UnblendedCost":{"Amount":"1"}},"Groups":[]}]})
    ce = CostExplorerClient(session=MagicMock(), ce_client=client)
    ce.get_total_cost(_window(30), spec=spec)

    filt = client.get_cost_and_usage.call_args.kwargs["Filter"]
    assert "And" in filt
    names = []
    for part in filt["And"]:
        if "Dimensions" in part:
            names.append(part["Dimensions"]["Key"])
        if "Tags" in part:
            names.append("Tags:" + part["Tags"]["Key"])
        if "Not" in part:
            names.append("Not:" + part["Not"]["Dimensions"]["Key"])
    assert "SERVICE" in names
    assert "Tags:Team" in names
    assert "Not:RECORD_TYPE" in names
