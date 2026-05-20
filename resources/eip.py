"""Elastic IP enumerator — focused on idle-EIP waste."""

from __future__ import annotations

from datetime import datetime

import boto3

import pricing

from .base import REGION, Resource, ResourceCost, hours_between, tag_name, tags_to_dict


def enumerate_eip(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
) -> list[ResourceCost]:
    ec2 = session.client("ec2", region_name=REGION)
    resp = ec2.describe_addresses()
    idle_rate = pricing.eip_idle_rate()

    rows: list[ResourceCost] = []
    for addr in resp.get("Addresses", []):
        alloc_id = addr.get("AllocationId", addr.get("PublicIp", ""))
        instance_id = addr.get("InstanceId")
        association_id = addr.get("AssociationId")
        public_ip = addr.get("PublicIp", "")
        tags = tags_to_dict(addr.get("Tags"))
        name = tag_name(addr.get("Tags"), fallback=public_ip or alloc_id)

        attached = bool(association_id)
        state = "associated" if attached else "unassociated"

        # Since Feb 2024 AWS bills $0.005/hr for ALL public IPv4, attached or not.
        # Idle EIPs are still the main "waste" target, but cost applies either way.
        window_hours = hours_between(window_start, min(datetime.utcnow(), window_end))
        raw = window_hours * idle_rate
        hours = window_hours

        resource = Resource(
            arn=f"arn:aws:ec2:{REGION}::elastic-ip/{alloc_id}",
            service="EIP",
            resource_id=alloc_id,
            name=name,
            type="elastic-ip",
            state=state,
            attributes={
                "public_ip": public_ip,
                "attached_instance_id": instance_id,
                "association_id": association_id,
            },
            tags=tags,
        )
        rows.append(
            ResourceCost(
                resource=resource,
                cost=raw,
                raw_cost=raw,
                usage={"idle_hours": round(hours, 2), "rate_usd_hr": idle_rate},
                waste_reason="unattached" if not attached else None,
            )
        )
    return rows
