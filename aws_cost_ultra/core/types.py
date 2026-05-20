"""Shared type definitions used across the package.

Kept intentionally small; each module owns its own domain types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class CostMetric(str, Enum):
    """Cost Explorer metric names.

    Default throughout the tool is `UNBLENDED` to match the AWS Console.
    See provenance.py for the accuracy invariant — every number returned
    to the UI carries its metric label.
    """

    UNBLENDED = "UnblendedCost"
    AMORTIZED = "AmortizedCost"
    NET_UNBLENDED = "NetUnblendedCost"
    NET_AMORTIZED = "NetAmortizedCost"
    BLENDED = "BlendedCost"
    USAGE_QUANTITY = "UsageQuantity"
    NORMALIZED_USAGE = "NormalizedUsageAmounts"


class Granularity(str, Enum):
    DAILY = "DAILY"
    MONTHLY = "MONTHLY"
    HOURLY = "HOURLY"


@dataclass(frozen=True)
class TimeWindow:
    """Closed-open window [start, end) in UTC."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("TimeWindow datetimes must be timezone-aware")
        if self.end <= self.start:
            raise ValueError(f"TimeWindow end ({self.end}) must be after start ({self.start})")

    @classmethod
    def last_n_days(cls, days: int) -> TimeWindow:
        now = datetime.now(tz=timezone.utc)
        return cls(start=now.replace(hour=0, minute=0, second=0, microsecond=0)
                   - _days(days), end=now)

    def iso(self) -> tuple[str, str]:
        """CE-friendly ISO date strings (YYYY-MM-DD)."""
        return self.start.strftime("%Y-%m-%d"), self.end.strftime("%Y-%m-%d")


def _days(n: int):  # pragma: no cover — trivial
    from datetime import timedelta
    return timedelta(days=n)


@dataclass
class AccountRef:
    """Identifies an AWS account as seen from the local machine."""

    profile: str
    account_id: str
    alias: Optional[str] = None
    regions: list[str] = field(default_factory=list)
