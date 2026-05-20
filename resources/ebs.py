"""EBS volume enumerator."""

from __future__ import annotations

from datetime import datetime

import boto3

import pricing

from .base import REGION, Resource, ResourceCost, clamp_window, hours_between, tag_name, tags_to_dict


def enumerate_ebs(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    ec2_name_by_id: dict | None = None,
) -> list[ResourceCost]:
    ec2 = session.client("ec2", region_name=REGION)
    paginator = ec2.get_paginator("describe_volumes")
    ec2_name_by_id = ec2_name_by_id or {}

    rows: list[ResourceCost] = []
    for page in paginator.paginate():
        for vol in page.get("Volumes", []):
            vol_id = vol["VolumeId"]
            vol_type = vol.get("VolumeType", "gp3")
            size_gb = vol.get("Size", 0)
            state = vol.get("State", "unknown")
            create_time = vol.get("CreateTime")
            tags = tags_to_dict(vol.get("Tags"))

            attachments = vol.get("Attachments", [])
            attached_instance_id = attachments[0]["InstanceId"] if attachments else None
            attached_name = ec2_name_by_id.get(attached_instance_id) if attached_instance_id else None

            name = tag_name(vol.get("Tags"),
                            fallback=attached_name or vol_id)

            eff_start, eff_end = clamp_window(create_time, window_start, window_end)
            hours = hours_between(eff_start, eff_end)
            rate_gb_month = pricing.ebs_rate(session, vol_type, REGION)
            # $/GB-month × GB × (hours / 730)
            raw = size_gb * rate_gb_month * (hours / 730.0)

            resource = Resource(
                arn=f"arn:aws:ec2:{REGION}::volume/{vol_id}",
                service="EBS",
                resource_id=vol_id,
                name=name,
                type=vol_type,
                state=state,
                attributes={
                    "size_gb": size_gb,
                    "attached_instance_id": attached_instance_id,
                    "attached_instance_name": attached_name,
                    "az": vol.get("AvailabilityZone", ""),
                    "iops": vol.get("Iops"),
                },
                tags=tags,
            )
            rows.append(
                ResourceCost(
                    resource=resource,
                    cost=raw,
                    raw_cost=raw,
                    usage={"gb_hours": round(size_gb * hours, 2),
                           "rate_usd_gb_month": rate_gb_month},
                    waste_reason="unattached" if state == "available" else None,
                )
            )
    return rows
