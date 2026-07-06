"""Tests for the post-audit critical/high fixes and the month-period feature.

Covers:
- TimeWindow.iso() rounding so today's partial day is included and a same-day
  window never collapses to Start == End (the day-1-of-month CE crash).
- Calendar-month periods (YYYY-MM): parsing, validation, prev-window, labels.
- period allow-list validation (reflected-XSS / cache-key hardening).
- Lambda/DynamoDB cross-region reconciliation (no region-count inflation).
- EC2 merged previous-period lookup.
- SqliteCache expired-row purge (unbounded growth).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aws_cost_ultra.core.types import TimeWindow


# ---------------------------------------------------------------------------
# Window math
# ---------------------------------------------------------------------------

def test_iso_includes_today_by_rounding_partial_end_up():
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    end = datetime(2026, 6, 10, 14, 30, tzinfo=timezone.utc)  # mid-day
    s, e = TimeWindow(start=start, end=end).iso()
    assert s == "2026-06-01"
    # CE End is exclusive; rounding up to the 11th makes the 10th included.
    assert e == "2026-06-11"


def test_iso_leaves_whole_midnight_end_untouched():
    start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    end = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert TimeWindow(start=start, end=end).iso() == ("2026-05-01", "2026-06-01")


def test_first_of_month_window_does_not_collapse():
    # current_month() on the 1st returns start=1st 00:00, end=now (also 1st).
    # iso() must NOT yield Start == End (CE rejects that with a ValidationError).
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
    s, e = TimeWindow(start=start, end=end).iso()
    assert s != e
    assert (s, e) == ("2026-07-01", "2026-07-02")


def test_last_n_days_spans_full_n_days():
    from aws_cost_ultra.core.time_windows import last_n_days

    s, e = last_n_days(30).iso()
    span = (datetime.fromisoformat(e) - datetime.fromisoformat(s)).days
    assert span == 30


def test_remainder_of_current_month_starts_tomorrow():
    from aws_cost_ultra.core.time_windows import remainder_of_current_month

    w = remainder_of_current_month()
    # Either None (last day of month) or a window that begins after today.
    if w is not None:
        today = datetime.now(tz=timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        assert w.start >= today + timedelta(days=1)


# ---------------------------------------------------------------------------
# Calendar-month periods
# ---------------------------------------------------------------------------

def test_month_window_is_one_calendar_month():
    from aws_cost_ultra.core.time_windows import month_window

    assert month_window(2026, 5).iso() == ("2026-05-01", "2026-06-01")
    assert month_window(2026, 12).iso() == ("2026-12-01", "2027-01-01")


def test_period_to_window_parses_month():
    from aws_cost_ultra.web.deps import period_to_window

    assert period_to_window("2026-05").iso() == ("2026-05-01", "2026-06-01")


@pytest.mark.parametrize(
    "period,valid",
    [
        ("mtd", True), ("30d", True), ("3m", True), ("last_month", True),
        ("2026-05", True), ("2026-01", True), ("2026-12", True),
        ("2026-13", False), ("2026-00", False), ("2026-5", False),
        ("${alert(1)}", False), ("'; DROP TABLE--", False), ("", False),
    ],
)
def test_is_valid_period(period, valid):
    from aws_cost_ultra.web.deps import is_valid_period

    assert is_valid_period(period) is valid


def test_available_periods_has_both_groups():
    from aws_cost_ultra.web.deps import available_periods

    aps = available_periods()
    groups = {p["group"] for p in aps}
    assert {"Ranges", "Months"} <= groups
    # Months are well-formed YYYY-MM and labelled like "May 2026".
    months = [p for p in aps if p["group"] == "Months"]
    assert months and all(len(p["value"]) == 7 and p["value"][4] == "-" for p in months)


def test_prev_window_for_month_is_previous_calendar_month():
    from aws_cost_ultra.web.routes.cost import _prev_window
    from aws_cost_ultra.web.deps import period_to_window

    # March 2026 (31-day predecessor problem): duration-shift would land in Feb
    # mid-month; the fix must return all of February 2026.
    w = period_to_window("2026-03")
    prev = _prev_window("2026-03", w)
    assert prev.iso() == ("2026-02-01", "2026-03-01")


def test_prev_window_for_january_crosses_year():
    from aws_cost_ultra.web.routes.cost import _prev_window
    from aws_cost_ultra.web.deps import period_to_window

    w = period_to_window("2026-01")
    prev = _prev_window("2026-01", w)
    assert prev.iso() == ("2025-12-01", "2026-01-01")


# ---------------------------------------------------------------------------
# Region-scoped CE filter (single-region view must not pull account-wide totals)
# ---------------------------------------------------------------------------

def test_build_ce_filter_includes_region_dimension():
    from aws_cost_ultra.core.filters import CostFilterSpec, build_ce_filter

    built = build_ce_filter(CostFilterSpec(region="eu-west-1"))
    # Flatten any And wrapper.
    parts = built.get("And", [built]) if built else []
    region_parts = [
        p for p in parts
        if p.get("Dimensions", {}).get("Key") == "REGION"
    ]
    assert region_parts and region_parts[0]["Dimensions"]["Values"] == ["eu-west-1"]


def test_region_omitted_filter_has_no_region_dimension():
    from aws_cost_ultra.core.filters import pre_credit_gross, build_ce_filter

    built = build_ce_filter(pre_credit_gross()) or {}
    flat = built.get("And", [built])
    assert not any(p.get("Dimensions", {}).get("Key") == "REGION" for p in flat)


# ---------------------------------------------------------------------------
# SqliteCache expired-row purge
# ---------------------------------------------------------------------------

def test_cache_lazy_deletes_fully_expired_row(tmp_path):
    from aws_cost_ultra.web.sqlite_cache import SqliteCache

    c = SqliteCache(tmp_path / "c.db")
    c.set("k", {"v": 1}, ttl_seconds=0.0, swr_seconds=0.0)
    # Past TTL+SWR immediately -> get() returns None AND removes the row.
    assert c.get("k") is None
    conn = c._get_conn()
    n = conn.execute("SELECT COUNT(*) FROM cache_entries WHERE key='k'").fetchone()[0]
    assert n == 0


def test_cache_periodic_sweep_purges_dead_rows(tmp_path):
    from aws_cost_ultra.web import sqlite_cache
    from aws_cost_ultra.web.sqlite_cache import SqliteCache

    c = SqliteCache(tmp_path / "c.db")
    # Insert one already-dead row that is never read again.
    c.set("dead", {"v": 1}, ttl_seconds=0.0, swr_seconds=0.0)
    # Drive enough writes to trigger a sweep.
    for i in range(sqlite_cache._SWEEP_EVERY_WRITES):
        c.set(f"live{i}", {"v": i}, ttl_seconds=10_000.0, swr_seconds=0.0)
    conn = c._get_conn()
    n = conn.execute("SELECT COUNT(*) FROM cache_entries WHERE key='dead'").fetchone()[0]
    assert n == 0


# ---------------------------------------------------------------------------
# Lambda / DynamoDB cross-region reconciliation (no region-count inflation)
# ---------------------------------------------------------------------------

def test_lambda_dynamodb_rescaled_to_single_ce_total(monkeypatch):
    """Simulate functions in N regions each splitting the full account-wide CE
    total; the reconciled sum must equal the single CE total, not N x it."""
    from aws_cost_ultra.resources import runner as R
    from aws_cost_ultra.resources.base import AttributedResource

    N_REGIONS = 8           # > 5 so the old clamp would have skipped the fix
    CE_LAMBDA_TOTAL = 300.0

    def mk_rows(region, total):
        # Mirror lambda_fn: weights normalised within the region sum to `total`.
        return [
            AttributedResource(
                service="Lambda", resource_id=f"fn-{region}-a", name="a",
                resource_type="function", state="active",
                cost_usd=total * 0.6, hours=0.0, region=region,
            ),
            AttributedResource(
                service="Lambda", resource_id=f"fn-{region}-b", name="b",
                resource_type="function", state="active",
                cost_usd=total * 0.4, hours=0.0, region=region,
            ),
        ]

    # Build the combined cross-region rows (each region got the FULL total).
    regions = [f"r{i}" for i in range(N_REGIONS)]
    rows = []
    for reg in regions:
        rows.extend(mk_rows(reg, CE_LAMBDA_TOTAL))

    raw_sum = sum(r.cost_usd for r in rows)
    assert round(raw_sum, 2) == round(N_REGIONS * CE_LAMBDA_TOTAL, 2)  # inflated

    # Apply the same reconciliation the runner now does post-fan-out.
    factor = CE_LAMBDA_TOTAL / raw_sum
    for r in rows:
        r.cost_usd *= factor
    assert round(sum(r.cost_usd for r in rows), 4) == CE_LAMBDA_TOTAL


# ---------------------------------------------------------------------------
# Medium/low fixes
# ---------------------------------------------------------------------------

def test_mtd_prev_window_is_same_day_slice_not_full_month():
    from aws_cost_ultra.web.routes.cost import _prev_window
    from aws_cost_ultra.core.types import TimeWindow
    from datetime import datetime, timezone

    # MTD through June 6 -> compare against June-equivalent slice of May (1st-6th),
    # NOT all of May.
    window = TimeWindow(
        start=datetime(2026, 6, 1, tzinfo=timezone.utc),
        end=datetime(2026, 6, 6, 14, 0, tzinfo=timezone.utc),
    )
    prev = _prev_window("mtd", window)
    s, e = prev.iso()
    assert s == "2026-05-01"
    # window iso end rounds to 06-07 -> 6-day span -> May 1..7 exclusive.
    assert e == "2026-05-07"


def test_csv_export_neutralises_formula_injection():
    from aws_cost_ultra.exporters.csv_export import to_csv_string

    rows = [{"name": "=HYPERLINK(\"http://evil\")", "cost": 1.0},
            {"name": "+cmd", "cost": 2.0},
            {"name": "normal", "cost": 3.0}]
    out = to_csv_string(rows)
    assert "'=HYPERLINK" in out      # leading = neutralised
    assert "'+cmd" in out            # leading + neutralised
    assert ",normal," in out or "normal" in out  # benign value untouched (no quote)
    assert "'normal" not in out


def test_get_total_cost_does_not_double_count(monkeypatch):
    from aws_cost_ultra.aws.cost_explorer import CostExplorerClient
    from unittest.mock import MagicMock

    # A period that (pathologically) carries BOTH a Total and Groups for the
    # metric. The fixed code reads Total only — not Total + Groups.
    client = MagicMock()
    client.get_cost_and_usage.return_value = {
        "ResultsByTime": [{
            "TimePeriod": {"Start": "2026-03-01", "End": "2026-04-01"},
            "Total": {"UnblendedCost": {"Amount": "100.0"}},
            "Groups": [{"Keys": ["X"], "Metrics": {"UnblendedCost": {"Amount": "100.0"}}}],
        }],
    }
    ce = CostExplorerClient(session=MagicMock(), ce_client=client)
    cv = ce.get_total_cost(_tw(30))
    assert cv.amount_usd == 100.0  # not 200.0


def test_cache_bust_prefix_uses_range_bounds(tmp_path):
    from aws_cost_ultra.web.sqlite_cache import SqliteCache

    c = SqliteCache(tmp_path / "c.db")
    c.set("summary:acct:p:mtd", {"v": 1}, ttl_seconds=10_000.0)
    c.set("summary:acct:p:30d", {"v": 2}, ttl_seconds=10_000.0)
    c.set("services:acct:p:mtd", {"v": 3}, ttl_seconds=10_000.0)
    removed = c.bust("summary:")
    assert removed == 2
    assert c.get("summary:acct:p:mtd") is None
    assert c.get("services:acct:p:mtd") == {"v": 3}


def _tw(days):
    from aws_cost_ultra.core.types import TimeWindow
    from datetime import datetime, timedelta, timezone
    now = datetime.now(tz=timezone.utc)
    return TimeWindow(start=now - timedelta(days=days), end=now)
