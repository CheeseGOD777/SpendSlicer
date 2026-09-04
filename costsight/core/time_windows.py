"""Time-window helpers.

Cost Explorer is UTC-native. All windows are half-open [start, end)
in UTC. The day boundary mismatches we see in the wild come from callers
mixing local tz and UTC; these helpers eliminate that class of bug.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from costsight.core.types import TimeWindow


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


def remainder_of_current_month() -> Optional[TimeWindow]:
    """Tomorrow's UTC midnight → 1st of next month. For CE forecast calls.

    Starts *tomorrow*, not today: month-to-date actuals already include
    today's partial-day spend (``TimeWindow.iso`` rounds the exclusive End
    up past today), so a forecast that also started today would double-count
    the current day. The forecast therefore covers only the days strictly
    after today.

    Returns ``None`` on the last day of the month — there is no remainder to
    forecast, so the caller should fall back to the actual MTD total alone.
    """
    today = _utc_today_midnight()
    tomorrow = today + timedelta(days=1)
    # Roll over based on TODAY's month. Basing it on tomorrow meant that on
    # the last day of a month the window became the ENTIRE next month, and
    # "projected month close" showed this month's actuals plus a full month
    # of forecast (~2x reality).
    if today.month == 12:
        end = today.replace(year=today.year + 1, month=1, day=1)
    else:
        end = today.replace(month=today.month + 1, day=1)
    if tomorrow >= end:
        # Today is the last day of the month — nothing left to forecast.
        return None
    return TimeWindow(start=tomorrow, end=end)


def month_window(year: int, month: int) -> TimeWindow:
    """Full calendar month ``[1st 00:00, 1st-of-next-month 00:00)`` in UTC.

    Powers the month-picker periods (e.g. ``2026-05`` → all of May 2026).
    Both bounds are whole UTC midnights, so ``iso()`` does not round and the
    window is exactly one calendar month — matching how the AWS console
    reports a selected month.
    """
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1..12, got {month}")
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return TimeWindow(start=start, end=end)


def recent_months(n: int) -> list[tuple[int, int]]:
    """The ``n`` most recent calendar months, newest first, as (year, month).

    Includes the current month. Used to build the month-picker option list.
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    now = datetime.now(tz=timezone.utc)
    y, mo = now.year, now.month
    out: list[tuple[int, int]] = []
    for _ in range(n):
        out.append((y, mo))
        mo -= 1
        if mo == 0:
            mo = 12
            y -= 1
    return out


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
