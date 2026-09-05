"""EBS volume attribution — pricing formula (size × hours × $/GB-month)."""

from __future__ import annotations

from datetime import datetime

import boto3
from botocore.config import Config

from spendslicer.core import pricing

from .base import AttributedResource, clamp_window, hours_between, tag_name, tags_to_dict

# Adaptive retries so throttling self-heals at the client layer.
_ADAPTIVE_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})


def attribute_ebs(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    region: str,
    ec2_name_by_id: dict[str, str] | None = None,
) -> list[AttributedResource]:
    ec2 = session.client("ec2", region_name=region, config=_ADAPTIVE_RETRY_CONFIG)
    names = ec2_name_by_id or {}

    rows: list[AttributedResource] = []
    for page in ec2.get_paginator("describe_volumes").paginate():
        for vol in page.get("Volumes", []):
            vol_id = vol["VolumeId"]
            vol_type = vol.get("VolumeType", "gp3")
            size_gb = vol.get("Size", 0)
            state = vol.get("State", "unknown")
            created = vol.get("CreateTime")
            tags = tags_to_dict(vol.get("Tags"))

            attach = vol.get("Attachments") or []
            attached_inst = attach[0]["InstanceId"] if attach else None
            attached_name = names.get(attached_inst) if attached_inst else None

            name = tag_name(vol.get("Tags"), fallback=attached_name or vol_id)

            eff_s, eff_e = clamp_window(created, window_start, window_end)
            hrs = hours_between(eff_s, eff_e)
            rate = pricing.ebs_rate(session, vol_type, region)
            cost = size_gb * rate * (hrs / 730.0)

            rows.append(AttributedResource(
                service="EBS",
                resource_id=vol_id,
                name=name,
                resource_type=vol_type,
                state=state,
                cost_usd=cost,
                hours=hrs,
                region=region,
                tags=tags,
                waste_reason="unattached" if state == "available" else None,
                attributes={
                    "size_gb": size_gb,
                    "attached_instance_id": attached_inst,
                    "attached_instance_name": attached_name,
                    "az": vol.get("AvailabilityZone", ""),
                    "iops": vol.get("Iops"),
                    "rate_usd_gb_month": rate,
                },
            ))
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows
