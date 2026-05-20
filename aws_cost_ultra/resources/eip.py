"""Elastic IP attribution — $0.005/hr for every public IPv4 since Feb 2024."""

from __future__ import annotations

from datetime import datetime

import boto3
from botocore.exceptions import ClientError

from aws_cost_ultra.core import pricing
from .base import AttributedResource, hours_between, tag_name, tags_to_dict


def attribute_eip(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    region: str,
) -> list[AttributedResource]:
    ec2 = session.client("ec2", region_name=region)
    try:
        addrs = ec2.describe_addresses().get("Addresses", [])
    except ClientError:
        return []

    idle_rate = pricing.eip_idle_rate()
    effective_end = min(datetime.utcnow(), window_end)
    window_hours = hours_between(window_start, effective_end)

    rows: list[AttributedResource] = []
    for a in addrs:
        alloc_id = a.get("AllocationId", a.get("PublicIp", ""))
        attached = bool(a.get("AssociationId"))
        state = "associated" if attached else "unassociated"
        tags = tags_to_dict(a.get("Tags"))
        name = tag_name(a.get("Tags"), fallback=a.get("PublicIp") or alloc_id)
        cost = window_hours * idle_rate

        rows.append(AttributedResource(
            service="EIP",
            resource_id=alloc_id,
            name=name,
            resource_type="elastic-ip",
            state=state,
            cost_usd=cost,
            hours=window_hours,
            region=region,
            tags=tags,
            waste_reason="unattached" if not attached else None,
            attributes={
                "public_ip": a.get("PublicIp", ""),
                "attached_instance_id": a.get("InstanceId"),
                "association_id": a.get("AssociationId"),
                "rate_usd_hr": idle_rate,
            },
        ))
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows
