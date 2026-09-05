"""Shared dataclasses + time helpers for resource enumerators."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from spendslicer.core.time_windows import utcnow_naive


@dataclass
class AttributedResource:
    """One physical AWS resource with its attributed cost for a window.

    Fields
    ------
    service : Short label — "EC2", "EBS", "RDS", "EIP", "ELB".
    resource_id : AWS identifier (instance-id, volume-id, eip alloc id, …).
    name : Best-effort name (Name tag, falling back to the id).
    resource_type : instance type / volume type / LB kind.
    state : running / available / in-use / terminated / …
    cost_usd : Attributed cost for the window.
    hours : Billable hours used to compute the attribution.
    region : AWS region the resource lives in.
    waste_reason : If this looks idle/wasteful, a short human phrase.
    attributes : Free-form extras (az, size, public_ip, …).
    tags : Tag dict (may be empty).
    """

    service: str
    resource_id: str
    name: str
    resource_type: str
    state: str
    cost_usd: float
    hours: float
    region: str
    waste_reason: str | None = None
    attributes: dict = field(default_factory=dict)
    tags: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "service": self.service,
            "resource_id": self.resource_id,
            "name": self.name,
            "type": self.resource_type,
            "state": self.state,
            "cost": round(self.cost_usd, 4),
            "hours": round(self.hours, 2),
            "region": self.region,
            "waste_reason": self.waste_reason,
            "attributes": self.attributes,
            "tags": self.tags,
        }


def tag_name(tags: list[dict] | dict | None, fallback: str = "") -> str:
    if not tags:
        return fallback
    if isinstance(tags, dict):
        return tags.get("Name", fallback)
    for t in tags:
        if t.get("Key") == "Name":
            return t.get("Value", fallback)
    return fallback


def tags_to_dict(tags: list[dict] | None) -> dict:
    if not tags:
        return {}
    return {t.get("Key", ""): t.get("Value", "") for t in tags if t.get("Key")}


def hours_between(start: datetime, end: datetime) -> float:
    if end <= start:
        return 0.0
    return (end - start).total_seconds() / 3600.0


def clamp_window(
    resource_start: datetime | None,
    window_start: datetime,
    window_end: datetime,
) -> tuple[datetime, datetime]:
    """Intersect [resource_start, now] with [window_start, window_end].

    All times normalised to UTC-naive so subtraction is safe.
    """
    ws = _to_naive_utc(window_start)
    we = _to_naive_utc(window_end)
    rs = _to_naive_utc(resource_start) if resource_start else ws
    eff_start = max(rs, ws)
    eff_end = min(utcnow_naive(), we)
    return eff_start, eff_end


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
