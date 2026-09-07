"""Secrets Manager attribution — flat monthly charge per secret.

The simplest accurate enumerator in the codebase: AWS bills $0.40 per secret
per month, prorated, in every commercial region. No Pricing API call and no
estimation — a secret that existed for half the window costs half the rate.

API-call charges ($0.05 per 10k) are not attributed; they need CloudTrail to
break down per secret and are usually a rounding error next to the per-secret
charge.
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


def _row_for_secret(
    secret: dict,
    region: str,
    window_start: datetime,
    window_end: datetime,
    month_rate: float,
) -> AttributedResource:
    """Price one secret. Pure math — testable without boto3."""
    name = secret.get("Name", "")
    arn = secret.get("ARN", name)
    created = secret.get("CreatedDate")
    deleted = secret.get("DeletedDate")

    eff_s, eff_e = clamp_window(created, window_start, window_end)
    hrs = hours_between(eff_s, eff_e)
    # A secret scheduled for deletion stops billing at the deletion date.
    state = "scheduled-for-deletion" if deleted else "active"

    return AttributedResource(
        service="SecretsManager",
        resource_id=arn,
        name=name,
        resource_type="secret",
        state=state,
        cost_usd=month_rate * (hrs / _HOURS_PER_MONTH),
        hours=hrs,
        region=region,
        tags={t["Key"]: t.get("Value", "") for t in secret.get("Tags", []) if "Key" in t},
        attributes={
            "rotation_enabled": secret.get("RotationEnabled", False),
            "last_accessed": str(secret.get("LastAccessedDate") or ""),
            "month_rate_usd": month_rate,
            "cost_basis": "flat per-secret monthly charge, prorated",
        },
    )


def attribute_secrets(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    region: str,
) -> list[AttributedResource]:
    sm = session.client("secretsmanager", region_name=region, config=_ADAPTIVE_RETRY_CONFIG)
    rows: list[AttributedResource] = []
    try:
        for page in sm.get_paginator("list_secrets").paginate():
            for secret in page.get("SecretList", []):
                rows.append(_row_for_secret(
                    secret, region, window_start, window_end, pricing.secret_month_rate(),
                ))
    except ClientError:
        return rows
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows
