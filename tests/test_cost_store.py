import datetime as dt
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from costsight.aws.cost_store import CostStore, DailyServiceMatrix


def _fake_ce_response():
    return [
        {
            "TimePeriod": {"Start": "2026-05-18", "End": "2026-05-19"},
            "Groups": [
                {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "1.50", "Unit": "USD"}}},
                {"Keys": ["Amazon S3"],  "Metrics": {"UnblendedCost": {"Amount": "0.20", "Unit": "USD"}}},
            ],
        },
        {
            "TimePeriod": {"Start": "2026-05-19", "End": "2026-05-20"},
            "Groups": [
                {"Keys": ["Amazon EC2"], "Metrics": {"UnblendedCost": {"Amount": "1.55", "Unit": "USD"}}},
                {"Keys": ["Amazon S3"],  "Metrics": {"UnblendedCost": {"Amount": "0.22", "Unit": "USD"}}},
            ],
        },
    ]


@dataclass
class W:
    start: dt.date
    end: dt.date
    def iso(self):
        return (self.start.isoformat(), self.end.isoformat())


def test_matrix_total_sums_all_cells():
    m = DailyServiceMatrix.from_ce(_fake_ce_response())
    assert m.total() == pytest.approx(1.50 + 0.20 + 1.55 + 0.22)


def test_matrix_by_service_aggregates_across_days():
    m = DailyServiceMatrix.from_ce(_fake_ce_response())
    by_svc = dict(m.by_service())
    assert by_svc["Amazon EC2"] == pytest.approx(3.05)
    assert by_svc["Amazon S3"] == pytest.approx(0.42)


def test_matrix_trend_returns_daily_totals():
    m = DailyServiceMatrix.from_ce(_fake_ce_response())
    labels, values = m.trend()
    assert labels == ["2026-05-18", "2026-05-19"]
    assert values == [pytest.approx(1.70), pytest.approx(1.77)]


def test_store_returns_matrix():
    ce = MagicMock()
    ce.daily_service_matrix.return_value = _fake_ce_response()
    store = CostStore(ce_client=ce, cache_get=lambda k: None, cache_set=lambda k, v, **kw: None)
    w = W(dt.date(2026, 5, 18), dt.date(2026, 5, 20))
    m = store.get_matrix("p1", "acct1", w, spec="pre_credit_gross")
    assert m.total() == pytest.approx(1.50 + 0.20 + 1.55 + 0.22)
    ce.daily_service_matrix.assert_called_once()


def test_store_uses_cache_when_present():
    cache: dict = {}
    def cg(k): return cache.get(k)
    def cs(k, v, **kw): cache[k] = v

    ce = MagicMock()
    ce.daily_service_matrix.return_value = _fake_ce_response()
    w = W(dt.date(2026, 5, 18), dt.date(2026, 5, 20))
    store = CostStore(ce_client=ce, cache_get=cg, cache_set=cs)
    store.get_matrix("p1", "acct1", w, spec="pre_credit_gross")
    store.get_matrix("p1", "acct1", w, spec="pre_credit_gross")
    assert ce.daily_service_matrix.call_count == 1


def test_store_force_bypasses_cache():
    cache: dict = {}
    def cg(k): return cache.get(k)
    def cs(k, v, **kw): cache[k] = v

    ce = MagicMock()
    ce.daily_service_matrix.return_value = _fake_ce_response()
    w = W(dt.date(2026, 5, 18), dt.date(2026, 5, 20))
    store = CostStore(ce_client=ce, cache_get=cg, cache_set=cs)
    store.get_matrix("p1", "acct1", w, spec="pre_credit_gross")
    store.get_matrix("p1", "acct1", w, spec="pre_credit_gross", force=True)
    assert ce.daily_service_matrix.call_count == 2


def test_store_cache_key_namespaces_account():
    """Two accounts with the same window must not collide in cache."""
    cache: dict = {}
    def cg(k): return cache.get(k)
    def cs(k, v, **kw): cache[k] = v

    ce = MagicMock()
    ce.daily_service_matrix.return_value = _fake_ce_response()
    w = W(dt.date(2026, 5, 18), dt.date(2026, 5, 20))
    store = CostStore(ce_client=ce, cache_get=cg, cache_set=cs)
    store.get_matrix("p1", "acct1", w, spec="pre_credit_gross")
    store.get_matrix("p1", "acct2", w, spec="pre_credit_gross")
    assert ce.daily_service_matrix.call_count == 2  # different account → different key


def test_to_grouped_cost_list_preserves_order_and_totals():
    from datetime import datetime, timezone

    from costsight.core.provenance import Provenance
    from costsight.core.types import CostMetric, TimeWindow
    m = DailyServiceMatrix.from_ce(_fake_ce_response())
    win = TimeWindow(
        start=datetime(2026, 5, 18, tzinfo=timezone.utc),
        end=datetime(2026, 5, 20, tzinfo=timezone.utc),
    )
    prov = Provenance(
        source="cost_explorer",
        metric=CostMetric.UNBLENDED,
        window=win,
        timezone_str="UTC",
        excluded_record_types=("Credit", "Refund", "Upfront"),
        included_record_types=None,
        group_by=("SERVICE",),
        filter_summary="",
    )
    groups = m.to_grouped_cost_list(prov)
    assert [g.primary_key() for g in groups] == ["Amazon EC2", "Amazon S3"]
    assert groups[0].value.amount_usd == pytest.approx(3.05)
    assert groups[1].value.amount_usd == pytest.approx(0.42)
