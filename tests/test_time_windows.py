"""Time-window helpers — guard the UTC-only invariant."""

from __future__ import annotations

from datetime import datetime, timezone

from spendslicer.core.time_windows import (
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


# ---------------------------------------------------------------------------
# Forecast remainder window — month rollover must be based on TODAY, not
# tomorrow (on the last day of a month it forecast the entire NEXT month and
# the summary showed ~2x "projected month close").
# ---------------------------------------------------------------------------

def _freeze_today(monkeypatch, y, m, d):
    from datetime import datetime, timezone

    from spendslicer.core import time_windows as tw
    monkeypatch.setattr(
        tw, "_utc_today_midnight",
        lambda: datetime(y, m, d, tzinfo=timezone.utc),
    )


def test_remainder_is_none_on_last_day_of_month(monkeypatch):
    from spendslicer.core import time_windows as tw
    _freeze_today(monkeypatch, 2026, 7, 31)
    assert tw.remainder_of_current_month() is None


def test_remainder_is_none_on_last_day_of_november(monkeypatch):
    # Nov 30: tomorrow is Dec 1 — the old code took the month==12 branch and
    # forecast all of December.
    from spendslicer.core import time_windows as tw
    _freeze_today(monkeypatch, 2026, 11, 30)
    assert tw.remainder_of_current_month() is None


def test_remainder_is_none_on_dec_31(monkeypatch):
    from spendslicer.core import time_windows as tw
    _freeze_today(monkeypatch, 2026, 12, 31)
    assert tw.remainder_of_current_month() is None


def test_remainder_mid_month_covers_tomorrow_to_month_end(monkeypatch):
    from datetime import datetime, timezone

    from spendslicer.core import time_windows as tw
    _freeze_today(monkeypatch, 2026, 7, 7)
    w = tw.remainder_of_current_month()
    assert w.start == datetime(2026, 7, 8, tzinfo=timezone.utc)
    assert w.end == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_remainder_mid_december_stays_in_december(monkeypatch):
    from datetime import datetime, timezone

    from spendslicer.core import time_windows as tw
    _freeze_today(monkeypatch, 2026, 12, 15)
    w = tw.remainder_of_current_month()
    assert w.start == datetime(2026, 12, 16, tzinfo=timezone.utc)
    assert w.end == datetime(2027, 1, 1, tzinfo=timezone.utc)
