"""RDS instance enumerator."""

from __future__ import annotations

from datetime import datetime

import boto3

import pricing

from .base import REGION, Resource, ResourceCost, clamp_window, hours_between, tag_name, tags_to_dict


def enumerate_rds(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
) -> list[ResourceCost]:
    rds = session.client("rds", region_name=REGION)
    paginator = rds.get_paginator("describe_db_instances")

    rows: list[ResourceCost] = []
    for page in paginator.paginate():
        for db in page.get("DBInstances", []):
            db_id = db["DBInstanceIdentifier"]
            db_class = db.get("DBInstanceClass", "")
            engine = db.get("Engine", "")
            state = db.get("DBInstanceStatus", "unknown")
            create_time = db.get("InstanceCreateTime")
            storage_gb = db.get("AllocatedStorage", 0)
            storage_type = db.get("StorageType", "gp2")
            tag_list = db.get("TagList", [])
            tags = tags_to_dict(tag_list)
            name = tag_name(tag_list, fallback=db_id)

            eff_start, eff_end = clamp_window(create_time, window_start, window_end)
            hours = hours_between(eff_start, eff_end) if state == "available" else 0.0

            instance_rate = pricing.rds_instance_rate(session, db_class, engine, REGION)
            storage_rate = pricing.rds_storage_rate(session, storage_type, REGION)

            instance_cost = hours * instance_rate
            storage_cost = storage_gb * storage_rate * (hours_between(eff_start, eff_end) / 730.0)
            raw = instance_cost + storage_cost

            resource = Resource(
                arn=db.get("DBInstanceArn", f"arn:aws:rds:{REGION}::db/{db_id}"),
                service="RDS",
                resource_id=db_id,
                name=name,
                type=db_class,
                state=state,
                attributes={
                    "engine": engine,
                    "storage_gb": storage_gb,
                    "storage_type": storage_type,
                    "multi_az": db.get("MultiAZ", False),
                    "az": db.get("AvailabilityZone", ""),
                },
                tags=tags,
            )
            rows.append(
                ResourceCost(
                    resource=resource,
                    cost=raw,
                    raw_cost=raw,
                    usage={
                        "hours": round(hours, 2),
                        "instance_rate_usd_hr": instance_rate,
                        "storage_gb": storage_gb,
                        "storage_rate_usd_gb_month": storage_rate,
                    },
                )
            )
    return rows
