"""Route 53 attribution — flat monthly charge per hosted zone.

Route 53 is global, not regional: list_hosted_zones returns the same set from
every endpoint. The runner therefore submits this once for the account rather
than once per region, or every zone would be counted seventeen times.

Zones are $0.50/month each (the first 25; $0.10 beyond that), prorated. Query
charges are not attributed — they need per-zone CloudWatch query metrics, and
`cost_basis` says so rather than implying the row is the whole bill.
"""

from __future__ import annotations

from datetime import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from spendslicer.core import pricing

from .base import AttributedResource, hours_between

_ADAPTIVE_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})

_HOURS_PER_MONTH = 730.0
# AWS charges $0.50/zone for the first 25 zones, $0.10 for each one after.
_FIRST_TIER_ZONES = 25
_EXTRA_TIER_RATE = 0.10


def _row_for_zone(
    zone: dict,
    window_hours: float,
    month_rate: float,
) -> AttributedResource:
    """Price one hosted zone. Pure math — testable without boto3."""
    zone_id = (zone.get("Id") or "").rsplit("/", 1)[-1]
    name = zone.get("Name", zone_id)
    private = bool((zone.get("Config") or {}).get("PrivateZone", False))

    return AttributedResource(
        service="Route53",
        resource_id=zone_id,
        name=name,
        resource_type="private-zone" if private else "public-zone",
        state="active",
        cost_usd=month_rate * (window_hours / _HOURS_PER_MONTH),
        hours=window_hours,
        region="global",
        tags={},
        attributes={
            "record_count": zone.get("ResourceRecordSetCount", 0),
            "private": private,
            "month_rate_usd": month_rate,
            "cost_basis": "hosted-zone monthly charge, prorated; queries not included",
        },
    )


def attribute_route53(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
) -> list[AttributedResource]:
    """Account-wide, not per region — Route 53 has no regional endpoint."""
    r53 = session.client("route53", config=_ADAPTIVE_RETRY_CONFIG)
    zones: list[dict] = []
    try:
        for page in r53.get_paginator("list_hosted_zones").paginate():
            zones.extend(page.get("HostedZones", []))
    except ClientError:
        return []

    window_hours = hours_between(window_start, window_end)
    base_rate = pricing.hosted_zone_month_rate()
    rows = []
    for i, zone in enumerate(zones):
        rate = base_rate if i < _FIRST_TIER_ZONES else _EXTRA_TIER_RATE
        rows.append(_row_for_zone(zone, window_hours, rate))
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows
