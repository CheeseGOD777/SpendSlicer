"""EC2 attribution — USAGE_TYPE buckets split by running hours.

CE-RESOURCE_ID attribution was removed (UsageRecord surcharge). Plan 2
(CUR + DuckDB) supersedes both paths with free per-resource named cost.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Callable, Optional

import boto3
from botocore.config import Config

from aws_cost_ultra.core.filters import CostFilterSpec, build_ce_filter, pre_credit_gross

from .base import AttributedResource, clamp_window, hours_between, tag_name, tags_to_dict

# FINDING 24: enable botocore adaptive retries so CE/EC2 throttling self-heals
# (retried at the client layer) before it surfaces to the fan-out handlers.
_ADAPTIVE_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})

_FALLBACK_SOURCE = "cost_explorer_usage_type"


def describe_instances_raw(session: boto3.Session, region: str) -> list[dict]:
    """One ``describe_instances`` scan for a region → flat list of instance dicts.

    FINDING 21: EC2 attribution and EBS's id→name lookup both need the region's
    instances. Centralizing the scan here lets the runner fetch it once per
    region and feed both, instead of paginating ``describe_instances`` twice.
    """
    ec2 = session.client("ec2", region_name=region, config=_ADAPTIVE_RETRY_CONFIG)
    out: list[dict] = []
    for page in ec2.get_paginator("describe_instances").paginate():
        for res in page.get("Reservations", []):
            for inst in res.get("Instances", []):
                # FINDING 38: keep only the fields the two consumers actually
                # read (attribution + EBS id→name), not the full raw payload
                # (NetworkInterfaces, BlockDeviceMappings, SecurityGroups, all
                # metadata — KBs/instance held for every region for the run).
                out.append({
                    "InstanceId": inst.get("InstanceId"),
                    "InstanceType": inst.get("InstanceType"),
                    "InstanceLifecycle": inst.get("InstanceLifecycle"),
                    "LaunchTime": inst.get("LaunchTime"),
                    "State": {"Name": inst.get("State", {}).get("Name")},
                    "Placement": {"AvailabilityZone": inst.get("Placement", {}).get("AvailabilityZone", "")},
                    "PrivateIpAddress": inst.get("PrivateIpAddress", ""),
                    "PublicIpAddress": inst.get("PublicIpAddress", ""),
                    "Tags": inst.get("Tags"),
                })
    return out


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
    instances_provider: Optional[Callable[[str], list[dict]]] = None,
) -> list[AttributedResource]:
    """Attribute EC2 across all regions via USAGE_TYPE fallback (no CE RESOURCE_ID).

    ``instances_provider`` (optional, FINDING 21): ``fn(region) -> [instance, ...]``
    returning the region's already-fetched ``describe_instances`` result, so EC2
    and EBS share a single scan per region.
    """
    spec = spec or pre_credit_gross()
    rows: list[AttributedResource] = []
    for region in regions:
        instances = instances_provider(region) if instances_provider else None
        rows.extend(_attribute_from_usage_type(
            session, ce_client, window_start, window_end, region, spec=spec,
            instances=instances,
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
    instances: Optional[list[dict]] = None,
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
    # FINDING 1: scope the per-region CE query to THIS region. Without it,
    # every region iteration fetched the identical account-wide EC2 usage-type
    # totals and re-attributed them, counting the same cost once per region.
    filt_parts.append({
        "Dimensions": {"Key": "REGION", "Values": [region]}
    })
    # Combine base_filter + SERVICE + REGION under a single And so all parts apply.
    combined = {"And": filt_parts} if len(filt_parts) > 1 else filt_parts[0]

    start_s = window_start.strftime("%Y-%m-%d")
    end_s = window_end.strftime("%Y-%m-%d")

    ce_by_key: dict = defaultdict(lambda: {"cost": 0.0, "hours": 0.0})
    # Usage types under EC2-Compute that aren't per-instance box usage
    # (CPUCredits, data transfer, …) — surfaced as one aggregate row instead
    # of silently widening drift.
    non_instance_cost = 0.0
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
        # Count this paid CE page against the per-request counter (this raw
        # client bypasses CostExplorerClient's own instrumentation).
        try:
            from aws_cost_ultra.web.middleware import get_current_counter
            _results = resp.get("ResultsByTime", [])
            get_current_counter().add(
                pages=1,
                records=sum(len(p.get("Groups", []) or []) for p in _results),
            )
        except Exception:
            pass
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
                    if cost > 0:
                        non_instance_cost += cost
                    continue
                if cost > 0:
                    ce_by_key[key]["cost"] += cost
                    ce_by_key[key]["hours"] += hrs
        token = resp.get("NextPageToken")
        if not token:
            break

    if not ce_by_key and non_instance_cost <= 0.001:
        return []

    # FINDING 21: reuse a shared per-region scan when provided; otherwise do our own.
    if instances is None:
        instances = describe_instances_raw(session, region)
    inst_by_key: dict = defaultdict(list)
    for inst in instances:
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
        attributed_any = False

        if insts and total_running_hours > 0:
            attributed_any = True
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
                attributed_any = True
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
        if not attributed_any:
            # No live/stopped instance matches this CE bucket — the instances
            # were terminated or replaced after the window (e.g. Elastic
            # Beanstalk churn viewed on a closed month). Emit a labelled
            # aggregate row so the spend stays visible in the Resources view
            # instead of silently widening drift.
            rows.append(AttributedResource(
                service="EC2",
                resource_id=f"ce-usage:{region}:{lifecycle}:{itype}",
                name=f"{display_type} — terminated/replaced instances",
                resource_type=display_type,
                state="unmatched",
                cost_usd=ce_cost,
                hours=ce_data["hours"],
                region=region,
                attributes={
                    "aggregate": True,
                    "lifecycle": lifecycle,
                    "attribution_source": _FALLBACK_SOURCE,
                    "note": ("Cost Explorer bills this usage type in the window, "
                             "but no current instance matches — the instances were "
                             "likely terminated or replaced after the period."),
                },
            ))

    if non_instance_cost > 0.001:
        rows.append(AttributedResource(
            service="EC2",
            resource_id=f"ce-usage:{region}:non-instance",
            name="EC2 — non-instance usage (CPU credits, data transfer, …)",
            resource_type="usage aggregate",
            state="active",
            cost_usd=non_instance_cost,
            hours=0.0,
            region=region,
            attributes={
                "aggregate": True,
                "attribution_source": _FALLBACK_SOURCE,
                "note": "EC2-Compute usage types not tied to a single instance",
            },
        ))

    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows


def live_instance_names(
    session: boto3.Session,
    region: str,
    instances: Optional[list[dict]] = None,
) -> dict[str, str]:
    """Fast id→name lookup for EBS attached-instance labels.

    FINDING 21: pass ``instances`` (a shared ``describe_instances_raw`` result)
    to avoid a second ``describe_instances`` scan for a region EC2 already read.
    """
    if instances is None:
        instances = describe_instances_raw(session, region)
    out: dict[str, str] = {}
    for inst in instances:
        if inst["State"]["Name"] == "terminated":
            continue
        out[inst["InstanceId"]] = tag_name(
            inst.get("Tags"), fallback=inst["InstanceId"],
        )
    return out
