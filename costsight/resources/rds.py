"""RDS DB instance attribution — pricing formula (instance + storage)."""

from __future__ import annotations

from datetime import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from costsight.core import pricing
from .base import AttributedResource, clamp_window, hours_between, tag_name, tags_to_dict

# FINDING 24: adaptive retries so throttling self-heals at the client layer.
_ADAPTIVE_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})


# DBInstanceStatus values during which the INSTANCE (compute) is not billed.
# Everything else — available, backing-up, modifying, storage-full,
# maintenance, rebooting, upgrading — bills full instance hours.
_NON_BILLING_STATES = {"stopped", "stopping"}


def _row_for_db(
    db: dict,
    region: str,
    window_start: datetime,
    window_end: datetime,
    inst_rate: float,
    storage_rate: float,
) -> AttributedResource:
    """Price one DB instance. Pure math — testable without boto3.

    Stopped instances earn no instance hours but STILL bill allocated
    storage (and Multi-AZ bills ~2x both) — the old code zeroed everything
    for any non-"available" state, hiding ~$69/mo for a stopped 500 GB gp2.
    """
    db_id = db["DBInstanceIdentifier"]
    db_class = db.get("DBInstanceClass", "")
    engine = db.get("Engine", "")
    state = db.get("DBInstanceStatus", "unknown")
    created = db.get("InstanceCreateTime")
    storage_gb = db.get("AllocatedStorage", 0)
    storage_type = db.get("StorageType", "gp2")
    tag_list = db.get("TagList", [])

    eff_s, eff_e = clamp_window(created, window_start, window_end)
    window_hrs = hours_between(eff_s, eff_e)
    inst_hrs = 0.0 if state in _NON_BILLING_STATES else window_hrs

    az_factor = 2.0 if db.get("MultiAZ", False) else 1.0
    inst_cost = inst_hrs * inst_rate * az_factor
    # Storage bills for the whole time the instance exists, stopped or not.
    storage_cost = storage_gb * storage_rate * (window_hrs / 730.0) * az_factor

    return AttributedResource(
        service="RDS",
        resource_id=db_id,
        name=tag_name(tag_list, fallback=db_id),
        resource_type=db_class,
        state=state,
        cost_usd=inst_cost + storage_cost,
        hours=inst_hrs,
        region=region,
        tags=tags_to_dict(tag_list),
        attributes={
            "engine": engine,
            "storage_gb": storage_gb,
            "storage_type": storage_type,
            "multi_az": db.get("MultiAZ", False),
            "az": db.get("AvailabilityZone", ""),
            "instance_rate_usd_hr": inst_rate,
            "storage_rate_usd_gb_month": storage_rate,
            "cost_basis": (
                "storage-only (instance stopped)" if inst_hrs == 0.0 and window_hrs > 0
                else "instance hours + allocated storage"
            ) + (" x2 Multi-AZ" if az_factor == 2.0 else ""),
        },
    )


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
                inst_rate = pricing.rds_instance_rate(
                    session, db.get("DBInstanceClass", ""), db.get("Engine", ""), region,
                )
                storage_rate = pricing.rds_storage_rate(
                    session, db.get("StorageType", "gp2"), region,
                )
                rows.append(_row_for_db(
                    db, region, window_start, window_end, inst_rate, storage_rate,
                ))
    except ClientError:
        # Region/account where RDS is denied or throttled past retries — return
        # what we have for this region rather than failing the whole work unit.
        return rows
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows
