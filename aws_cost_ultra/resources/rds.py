"""RDS DB instance attribution — pricing formula (instance + storage)."""

from __future__ import annotations

from datetime import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from aws_cost_ultra.core import pricing
from .base import AttributedResource, clamp_window, hours_between, tag_name, tags_to_dict

# FINDING 24: adaptive retries so throttling self-heals at the client layer.
_ADAPTIVE_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})


def attribute_rds(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    region: str,
) -> list[AttributedResource]:
    rds = session.client("rds", region_name=region, config=_ADAPTIVE_RETRY_CONFIG)
    rows: list[AttributedResource] = []
    # paginate() is lazy — no API call happens until iteration, so the guard
    # must wrap the `for page in pages` loop, not just paginator construction
    # (the old guard was dead code; an AccessDenied/SCP/throttle ClientError
    # raised during iteration escaped and failed the whole RDS work unit).
    try:
        pages = rds.get_paginator("describe_db_instances").paginate()
        for page in pages:
            for db in page.get("DBInstances", []):
                db_id = db["DBInstanceIdentifier"]
                db_class = db.get("DBInstanceClass", "")
                engine = db.get("Engine", "")
                state = db.get("DBInstanceStatus", "unknown")
                created = db.get("InstanceCreateTime")
                storage_gb = db.get("AllocatedStorage", 0)
                storage_type = db.get("StorageType", "gp2")
                tag_list = db.get("TagList", [])
                tags = tags_to_dict(tag_list)
                name = tag_name(tag_list, fallback=db_id)

                eff_s, eff_e = clamp_window(created, window_start, window_end)
                hrs = hours_between(eff_s, eff_e) if state == "available" else 0.0

                inst_rate = pricing.rds_instance_rate(session, db_class, engine, region)
                storage_rate = pricing.rds_storage_rate(session, storage_type, region)

                inst_cost = hrs * inst_rate
                storage_cost = storage_gb * storage_rate * (hrs / 730.0)
                total = inst_cost + storage_cost

                rows.append(AttributedResource(
                    service="RDS",
                    resource_id=db_id,
                    name=name,
                    resource_type=db_class,
                    state=state,
                    cost_usd=total,
                    hours=hrs,
                    region=region,
                    tags=tags,
                    attributes={
                        "engine": engine,
                        "storage_gb": storage_gb,
                        "storage_type": storage_type,
                        "multi_az": db.get("MultiAZ", False),
                        "az": db.get("AvailabilityZone", ""),
                        "instance_rate_usd_hr": inst_rate,
                        "storage_rate_usd_gb_month": storage_rate,
                    },
                ))
    except ClientError:
        # Region/account where RDS is denied or throttled past retries — return
        # what we have for this region rather than failing the whole work unit.
        return rows
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows
