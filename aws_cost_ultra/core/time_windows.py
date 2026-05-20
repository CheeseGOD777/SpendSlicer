"""Time-window helpers.

Cost Explorer is UTC-native. All windows are half-open [start, end)
in UTC. The day boundary mismatches we see in the wild come from callers
mixing local tz and UTC; these helpers eliminate that class of bug.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aws_cost_ultra.core.types import TimeWindow


def _utc_today_midnight() -> datetime:
    now = datetime.now(tz=timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def last_n_days(n: int) -> TimeWindow:
    """Trailing n days ending at 'now' (UTC). Includes today's partial day."""
    now = datetime.now(tz=timezone.utc)
    return TimeWindow(start=_utc_today_midnight() - timedelta(days=n - 1), end=now)


def current_month() -> TimeWindow:
    """First day of the current UTC month → now."""
    now = datetime.now(tz=timezone.utc)
    first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return TimeWindow(start=first, end=now)


def last_month() -> TimeWindow:
    """Previous calendar month in UTC. Full [1st, 1st-of-next)."""
    now = datetime.now(tz=timezone.utc)
    this_first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_end = this_first
    prev_first = (this_first - timedelta(days=1)).replace(day=1)
    return TimeWindow(start=prev_first, end=last_end)


def month_before_last() -> TimeWindow:
    """Two full calendar months ago — useful for MoM comparisons."""
    lm = last_month()
    prev_first = (lm.start - timedelta(days=1)).replace(day=1)
    return TimeWindow(start=prev_first, end=lm.start)


def remainder_of_current_month() -> TimeWindow:
    """Tomorrow (UTC) → 1st of next month. For CE forecast calls.

    CE's ``get_cost_forecast`` requires Start >= today, and its results
    project only across the queried window. Pass this to forecast the
    leftover portion of the current month.
    """
    now = datetime.now(tz=timezone.utc)
    start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1, day=1)
    else:
        end = start.replace(month=start.month + 1, day=1)
    return TimeWindow(start=start, end=end)


def trailing_months(months: int) -> TimeWindow:
    """Last ``months`` full months up to (but not including) the current month.

    For a 6-month trend chart, callers pass months=6 and get a window
    covering Jan-1 through the 1st of the current month (UTC).
    """
    if months < 1:
        raise ValueError("months must be >= 1")
    now = datetime.now(tz=timezone.utc)
    end = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start = end
    for _ in range(months):
        start = (start - timedelta(days=1)).replace(day=1)
    return TimeWindow(start=start, end=end)
