"""EFS attribution — Standard storage x GB-month rate.

describe_file_systems reports SizeInBytes directly, so the storage figure is
measured rather than estimated. Infrequent-Access and One Zone tiers price
differently and are reported separately by AWS; this uses the Standard rate
against the Standard size, and names the tier split in the attributes so a
mismatch against the Cost Explorer total is explainable rather than mysterious.
"""

from __future__ import annotations

from datetime import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from spendslicer.core import pricing

from .base import AttributedResource, clamp_window, hours_between

_ADAPTIVE_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})

_HOURS_PER_MONTH = 730.0
_BYTES_PER_GB = 1024 ** 3


def _row_for_fs(
    fs: dict,
    region: str,
    window_start: datetime,
    window_end: datetime,
    gb_month_rate: float,
) -> AttributedResource:
    """Price one file system. Pure math — testable without boto3."""
    fs_id = fs.get("FileSystemId", "")
    size = fs.get("SizeInBytes") or {}
    standard_b = size.get("ValueInStandard", size.get("Value", 0)) or 0
    ia_b = size.get("ValueInIA", 0) or 0
    gb = standard_b / _BYTES_PER_GB

    eff_s, eff_e = clamp_window(fs.get("CreationTime"), window_start, window_end)
    hrs = hours_between(eff_s, eff_e)

    return AttributedResource(
        service="EFS",
        resource_id=fs_id,
        name=fs.get("Name") or fs_id,
        resource_type=fs.get("PerformanceMode", "generalPurpose"),
        state=fs.get("LifeCycleState", "unknown"),
        cost_usd=gb * gb_month_rate * (hrs / _HOURS_PER_MONTH),
        hours=hrs,
        region=region,
        tags={t["Key"]: t.get("Value", "") for t in fs.get("Tags", []) if "Key" in t},
        attributes={
            "size_gb_standard": round(gb, 3),
            "size_gb_infrequent_access": round(ia_b / _BYTES_PER_GB, 3),
            "throughput_mode": fs.get("ThroughputMode", ""),
            "encrypted": fs.get("Encrypted", False),
            "gb_month_rate_usd": gb_month_rate,
            "cost_basis": "Standard-tier storage only; IA tier priced separately by AWS",
        },
    )


def attribute_efs(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    region: str,
) -> list[AttributedResource]:
    efs = session.client("efs", region_name=region, config=_ADAPTIVE_RETRY_CONFIG)
    rows: list[AttributedResource] = []
    try:
        for page in efs.get_paginator("describe_file_systems").paginate():
            for fs in page.get("FileSystems", []):
                rows.append(_row_for_fs(
                    fs, region, window_start, window_end, pricing.efs_gb_month_rate(),
                ))
    except ClientError:
        return rows
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows
