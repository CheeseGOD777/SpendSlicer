"""EC2 attribution — USAGE_TYPE buckets split by running hours.

CE-RESOURCE_ID attribution was removed (UsageRecord surcharge). Plan 2
(CUR + DuckDB) supersedes both paths with free per-resource named cost.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Optional

import boto3

from aws_cost_ultra.core.filters import CostFilterSpec, build_ce_filter, pre_credit_gross

from .base import AttributedResource, clamp_window, hours_between, tag_name, tags_to_dict

_FALLBACK_SOURCE = "cost_explorer_usage_type"


def attribute_ec2(
    session: boto3.Session,
    ce_client,
    window_start: datetime,
    window_end: datetime,
    region: str,
    spec: Optional[CostFilterSpec] = None,
) -> list[AttributedResource]:
    """Attribute EC2 for one region via USAGE_TYPE buckets split by running hours.

    RESOURCE_ID-based attribution was removed because the CE
    GetCostAndUsageWithResources call bills $0.00001/UsageRecord on top of
    the $0.01/request and dominated the tool's running cost. Plan 2 (CUR)
    re-introduces named per-resource cost from a free local warehouse.
    """
    return _attribute_from_usage_type(
        session, ce_client, window_start, window_end, region, spec=spec,
    )


def attribute_ec2_account(
    session: boto3.Session,
    ce_client,
    window_start: datetime,
    window_end: datetime,
    regions: list[str],
    spec: Optional[CostFilterSpec] = None,
) -> list[AttributedResource]:
    """Attribute EC2 across all regions via USAGE_TYPE fallback (no CE RESOURCE_ID)."""
    spec = spec or pre_credit_gross()
    rows: list[AttributedResource] = []
    for region in regions:
        rows.extend(_attribute_from_usage_type(
            session, ce_client, window_start, window_end, region, spec=spec,
        ))
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows


def _attribute_from_usage_type(
    session: boto3.Session,
    ce_client,
    window_start: datetime,
    window_end: datetime,
    region: str,
    spec: Optional[CostFilterSpec] = None,
) -> list[AttributedResource]:
    """Legacy USAGE_TYPE + running-hours proportional split."""
    spec = spec or pre_credit_gross()

    filt_parts = []
    base_filter = build_ce_filter(spec)
    if base_filter:
        filt_parts.append(base_filter)
    filt_parts.append({
        "Dimensions": {"Key": "SERVICE", "Values": ["Amazon Elastic Compute Cloud - Compute"]}
    })
    combined = {"And": filt_parts} if len(filt_parts) > 1 else filt_parts[0]

    start_s = window_start.strftime("%Y-%m-%d")
    end_s = window_end.strftime("%Y-%m-%d")

    ce_by_key: dict = defaultdict(lambda: {"cost": 0.0, "hours": 0.0})
    token = None
    while True:
        kwargs = {
            "TimePeriod": {"Start": start_s, "End": end_s},
            "Granularity": "MONTHLY",
            "Metrics": ["UnblendedCost", "UsageQuantity"],
            "GroupBy": [{"Type": "DIMENSION", "Key": "USAGE_TYPE"}],
            "Filter": combined,
        }
        if token:
            kwargs["NextPageToken"] = token
        resp = ce_client.get_cost_and_usage(**kwargs)
        for period in resp.get("ResultsByTime", []):
            for g in period.get("Groups", []):
                raw = g["Keys"][0]
                cost = float(g["Metrics"]["UnblendedCost"]["Amount"])
                hrs = float(g["Metrics"]["UsageQuantity"]["Amount"])
                rest = raw.split("-", 1)[1] if "-" in raw else raw
                if rest.startswith("BoxUsage:"):
                    key = ("ondemand", rest[len("BoxUsage:"):])
                elif rest.startswith("SpotUsage:"):
                    key = ("spot", rest[len("SpotUsage:"):])
                elif rest.startswith("HeavyUsage:"):
                    key = ("reserved", rest[len("HeavyUsage:"):])
                else:
                    continue
                if cost > 0:
                    ce_by_key[key]["cost"] += cost
                    ce_by_key[key]["hours"] += hrs
        token = resp.get("NextPageToken")
        if not token:
            break

    if not ce_by_key:
        return []

    ec2 = session.client("ec2", region_name=region)
    inst_by_key: dict = defaultdict(list)
    for page in ec2.get_paginator("describe_instances").paginate():
        for res in page.get("Reservations", []):
            for inst in res.get("Instances", []):
                state = inst["State"]["Name"]
                if state == "terminated":
                    continue
                itype = inst["InstanceType"]
                lifecycle = "spot" if inst.get("InstanceLifecycle") == "spot" else "ondemand"
                launch = inst.get("LaunchTime")
                if state == "running" and launch:
                    eff_s, eff_e = clamp_window(launch, window_start, window_end)
                    run_hrs = hours_between(eff_s, eff_e)
                else:
                    run_hrs = 0.0
                inst_by_key[(lifecycle, itype)].append({
                    "id": inst["InstanceId"],
                    "name": tag_name(inst.get("Tags"), fallback=inst["InstanceId"]),
                    "tags": tags_to_dict(inst.get("Tags")),
                    "type": itype,
                    "state": state,
                    "hours": run_hrs,
                    "az": inst.get("Placement", {}).get("AvailabilityZone", ""),
                    "private_ip": inst.get("PrivateIpAddress", ""),
                    "public_ip": inst.get("PublicIpAddress", ""),
                })

    rows: list[AttributedResource] = []
    for (lifecycle, itype), ce_data in ce_by_key.items():
        ce_cost = ce_data["cost"]
        if ce_cost <= 0.001:
            continue
        display_type = itype + (
            " (spot)" if lifecycle == "spot" else
            " (reserved)" if lifecycle == "reserved" else ""
        )
        insts = inst_by_key.get((lifecycle, itype), [])
        total_running_hours = sum(i["hours"] for i in insts)

        if insts and total_running_hours > 0:
            for inst in insts:
                if inst["hours"] <= 0:
                    continue
                allocated = ce_cost * (inst["hours"] / total_running_hours)
                rows.append(AttributedResource(
                    service="EC2",
                    resource_id=inst["id"],
                    name=inst["name"],
                    resource_type=display_type,
                    state=inst["state"],
                    cost_usd=allocated,
                    hours=inst["hours"],
                    region=region,
                    tags=inst["tags"],
                    attributes={
                        "az": inst["az"],
                        "private_ip": inst["private_ip"],
                        "public_ip": inst["public_ip"],
                        "lifecycle": lifecycle,
                        "attribution_source": _FALLBACK_SOURCE,
                    },
                ))
        elif insts:
            # Only mark "stopped — still incurring EBS cost" when there are
            # explicit stopped instances for this CE usage bucket. If every
            # discovered instance is running but has zero in-window hours
            # (e.g. launched after the queried period), don't fabricate a
            # stopped finding; leave that CE cost as unattributed drift.
            stopped_insts = [i for i in insts if i["state"] == "stopped"]
            if stopped_insts:
                per = ce_cost / len(stopped_insts)
                for inst in stopped_insts:
                    rows.append(AttributedResource(
                        service="EC2",
                        resource_id=inst["id"],
                        name=inst["name"],
                        resource_type=display_type,
                        state=inst["state"],
                        cost_usd=per,
                        hours=0.0,
                        region=region,
                        tags=inst["tags"],
                        waste_reason="stopped — still incurring EBS cost",
                        attributes={"az": inst["az"], "lifecycle": lifecycle,
                                    "attribution_source": _FALLBACK_SOURCE},
                    ))
        # No matching live/stopped instances — leave cost in CE drift, no synthetic rows.

    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows


def live_instance_names(session: boto3.Session, region: str) -> dict[str, str]:
    """Fast id→name lookup for EBS attached-instance labels."""
    ec2 = session.client("ec2", region_name=region)
    out: dict[str, str] = {}
    for page in ec2.get_paginator("describe_instances").paginate():
        for res in page.get("Reservations", []):
            for inst in res.get("Instances", []):
                if inst["State"]["Name"] == "terminated":
                    continue
                out[inst["InstanceId"]] = tag_name(
                    inst.get("Tags"), fallback=inst["InstanceId"],
                )
    return out
