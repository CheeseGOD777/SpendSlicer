"""EC2 instance enumerator."""

from __future__ import annotations

from datetime import datetime

import boto3

import pricing

from .base import REGION, Resource, ResourceCost, clamp_window, hours_between, tag_name, tags_to_dict


def enumerate_ec2(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
) -> list[ResourceCost]:
    ec2 = session.client("ec2", region_name=REGION)
    paginator = ec2.get_paginator("describe_instances")

    rows: list[ResourceCost] = []
    for page in paginator.paginate():
        for res in page.get("Reservations", []):
            for inst in res.get("Instances", []):
                state = inst["State"]["Name"]
                instance_type = inst["InstanceType"]
                launch_time = inst.get("LaunchTime")
                tags = tags_to_dict(inst.get("Tags"))
                name = tag_name(inst.get("Tags"), fallback=inst["InstanceId"])

                # Hours counted only when currently running.
                if state == "running":
                    eff_start, eff_end = clamp_window(launch_time, window_start, window_end)
                    hours = hours_between(eff_start, eff_end)
                else:
                    hours = 0.0

                rate = pricing.ec2_on_demand_rate(session, instance_type, REGION)
                raw = hours * rate

                resource = Resource(
                    arn=f"arn:aws:ec2:{REGION}:{inst.get('OwnerId', '')}:instance/{inst['InstanceId']}",
                    service="EC2",
                    resource_id=inst["InstanceId"],
                    name=name,
                    type=instance_type,
                    state=state,
                    attributes={
                        "az": inst.get("Placement", {}).get("AvailabilityZone", ""),
                        "launch_time": launch_time.isoformat() if launch_time else None,
                        "private_ip": inst.get("PrivateIpAddress", ""),
                        "public_ip": inst.get("PublicIpAddress", ""),
                    },
                    tags=tags,
                )
                rows.append(
                    ResourceCost(
                        resource=resource,
                        cost=raw,
                        raw_cost=raw,
                        usage={"hours": round(hours, 2), "rate_usd_hr": rate},
                    )
                )
    return rows
