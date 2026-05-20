"""Time-window helpers — guard the UTC-only invariant."""

from __future__ import annotations

from datetime import datetime, timezone

from aws_cost_ultra.core.time_windows import (
    current_month,
    last_month,
    last_n_days,
    month_before_last,
    trailing_months,
)


def test_last_n_days_uses_utc_midnight_boundary():
    w = last_n_days(7)
    assert w.start.tzinfo == timezone.utc
    assert w.start.hour == 0 and w.start.minute == 0


def test_current_month_starts_at_first_of_month_utc():
    w = current_month()
    assert w.start.day == 1
    assert w.start.tzinfo == timezone.utc


def test_last_month_is_first_to_first():
    lm = last_month()
    assert lm.start.day == 1
    assert lm.end.day == 1
    # end is the first of the current month
    now = datetime.now(tz=timezone.utc)
    assert lm.end.year == now.year and lm.end.month == now.month


def test_month_before_last_comes_before_last_month():
    mbl = month_before_last()
    lm = last_month()
    assert mbl.end == lm.start


def test_trailing_months_covers_n_full_months():
    w = trailing_months(6)
    # end is the 1st of the current month in UTC
    assert w.end.day == 1
    # start is 6 months earlier on a 1st-of-month boundary
    assert w.start.day == 1
    diff = (w.end.year - w.start.year) * 12 + (w.end.month - w.start.month)
    assert diff == 6


def test_trailing_months_rejects_zero():
    import pytest
    with pytest.raises(ValueError):
        trailing_months(0)
