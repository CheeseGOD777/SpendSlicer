"""Shared dataclasses + helpers for resource enumerators."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

REGION = "ap-south-1"


@dataclass
class Resource:
    arn: str
    service: str          # "EC2" | "EIP" | "EBS" | "RDS" | "ELB"
    resource_id: str
    name: str
    type: str             # instance type / volume type / LB type
    state: str
    attributes: dict = field(default_factory=dict)
    tags: dict = field(default_factory=dict)


@dataclass
class ResourceCost:
    resource: Resource
    cost: float
    raw_cost: float
    usage: dict = field(default_factory=dict)
    waste_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "arn": self.resource.arn,
            "service": self.resource.service,
            "resource_id": self.resource.resource_id,
            "name": self.resource.name,
            "type": self.resource.type,
            "state": self.resource.state,
            "attributes": self.resource.attributes,
            "tags": self.resource.tags,
            "cost": round(self.cost, 4),
            "raw_cost": round(self.raw_cost, 4),
            "usage": self.usage,
            "waste_reason": self.waste_reason,
        }


def normalize(rows: list[ResourceCost], ce_total: float) -> float:
    """Scale each row's `cost` so rows sum to `ce_total`. Returns scale factor.

    If raw sum is zero, leaves costs untouched and returns 1.0.
    """
    raw_sum = sum(r.raw_cost for r in rows)
    if raw_sum <= 0:
        for r in rows:
            r.cost = 0.0
        return 1.0
    factor = ce_total / raw_sum
    for r in rows:
        r.cost = r.raw_cost * factor
    return factor


def tag_name(tags: list[dict] | dict, fallback: str = "") -> str:
    """Extract the Name tag from an AWS tag list or dict."""
    if isinstance(tags, dict):
        return tags.get("Name", fallback)
    for t in tags or []:
        if t.get("Key") == "Name":
            return t.get("Value", fallback)
    return fallback


def tags_to_dict(tags: list[dict] | None) -> dict:
    if not tags:
        return {}
    return {t.get("Key", ""): t.get("Value", "") for t in tags if t.get("Key")}


def hours_between(start: datetime, end: datetime) -> float:
    """Return hours between two datetimes, clamped to >= 0."""
    if end <= start:
        return 0.0
    return (end - start).total_seconds() / 3600.0


def clamp_window(
    resource_start: Optional[datetime],
    window_start: datetime,
    window_end: datetime,
) -> tuple[datetime, datetime]:
    """Return (effective_start, effective_end) overlap between resource existence and query window."""
    rs = resource_start or window_start
    # Normalize to UTC naive for arithmetic
    if rs.tzinfo is not None:
        rs = rs.astimezone(timezone.utc).replace(tzinfo=None)
    effective_start = max(rs, window_start)
    effective_end = min(datetime.utcnow(), window_end)
    return effective_start, effective_end
