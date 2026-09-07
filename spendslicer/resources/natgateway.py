"""NAT gateway attribution — hourly charge per gateway.

NAT gateways bill under the "EC2 - Other" Cost Explorer service alongside
EBS and Elastic IPs, which is why they are easy to miss: the cost shows up
in a bucket most people read as "volumes". They are a routine top-five
surprise on a bill, so naming them matters.

Only the hourly charge is priced here. Data processing (~$0.045/GB) needs a
CloudWatch BytesOutToDestination lookup per gateway; without it the row
under-reports a busy gateway, so `cost_basis` says so rather than implying
the figure is complete. The rescale to the Cost Explorer total absorbs the
difference at the service level.
"""

from __future__ import annotations

from datetime import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from spendslicer.core import pricing

from .base import AttributedResource, clamp_window, hours_between, tag_name, tags_to_dict

_ADAPTIVE_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})

# A gateway bills from "pending" through "available". Deleted ones stop.
_NON_BILLING_STATES = {"deleted", "failed"}


def _row_for_nat(
    nat: dict,
    region: str,
    window_start: datetime,
    window_end: datetime,
    hour_rate: float,
) -> AttributedResource:
    """Price one NAT gateway. Pure math — testable without boto3."""
    nat_id = nat.get("NatGatewayId", "")
    state = nat.get("State", "unknown")
    created = nat.get("CreateTime")
    tag_list = nat.get("Tags", [])

    eff_s, eff_e = clamp_window(created, window_start, window_end)
    window_hrs = hours_between(eff_s, eff_e)
    billable_hrs = 0.0 if state in _NON_BILLING_STATES else window_hrs

    addrs = nat.get("NatGatewayAddresses") or [{}]
    return AttributedResource(
        service="NATGateway",
        resource_id=nat_id,
        name=tag_name(tag_list, fallback=nat_id),
        resource_type=nat.get("ConnectivityType", "public"),
        state=state,
        cost_usd=billable_hrs * hour_rate,
        hours=billable_hrs,
        region=region,
        tags=tags_to_dict(tag_list),
        attributes={
            "vpc_id": nat.get("VpcId", ""),
            "subnet_id": nat.get("SubnetId", ""),
            "public_ip": addrs[0].get("PublicIp", ""),
            "hour_rate_usd": hour_rate,
            "cost_basis": "gateway hours only — per-GB data processing not included",
        },
    )


def attribute_nat_gateways(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    region: str,
) -> list[AttributedResource]:
    ec2 = session.client("ec2", region_name=region, config=_ADAPTIVE_RETRY_CONFIG)
    rows: list[AttributedResource] = []
    try:
        for page in ec2.get_paginator("describe_nat_gateways").paginate():
            for nat in page.get("NatGateways", []):
                rows.append(_row_for_nat(
                    nat, region, window_start, window_end, pricing.nat_gateway_hour_rate(),
                ))
    except ClientError:
        return rows
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows
