"""Elastic IP attribution — $0.005/hr for every public IPv4 since Feb 2024."""

from __future__ import annotations

from datetime import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from costsight.core import pricing
from costsight.core.time_windows import utcnow_naive

from .base import AttributedResource, clamp_window, hours_between, tag_name, tags_to_dict

# Adaptive retries so throttling self-heals at the client layer.
_ADAPTIVE_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})


def attribute_eip(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    region: str,
) -> list[AttributedResource]:
    ec2 = session.client("ec2", region_name=region, config=_ADAPTIVE_RETRY_CONFIG)
    try:
        addrs = ec2.describe_addresses().get("Addresses", [])
    except ClientError:
        return []

    idle_rate = pricing.eip_idle_rate()
    effective_end = min(utcnow_naive(), window_end)
    window_hours = hours_between(window_start, effective_end)

    rows: list[AttributedResource] = []
    for a in addrs:
        alloc_id = a.get("AllocationId", a.get("PublicIp", ""))
        attached = bool(a.get("AssociationId"))
        state = "associated" if attached else "unassociated"
        tags = tags_to_dict(a.get("Tags"))
        name = tag_name(a.get("Tags"), fallback=a.get("PublicIp") or alloc_id)

        # Since Feb 2024 AWS charges $0.005/hr for EVERY public IPv4 address,
        # including ones associated with a running instance — not only idle
        # ones. So apply the rate to associated addresses too; the unattached
        # flag remains purely a *waste* signal, not a billing gate. (Setting
        # associated cost to $0 also caused their dollars to be redistributed
        # onto EBS volumes via the shared EC2-Other rescale.)
        # Describe_addresses exposes no allocation timestamp, so the
        # billed window is a best-effort full-window estimate.
        cost = window_hours * idle_rate
        hours = window_hours
        cost_basis = (
            "full-window @ public-IPv4 rate (allocation time unavailable)"
            if not attached else
            "associated — public-IPv4 in-use rate (since Feb 2024)"
        )

        rows.append(AttributedResource(
            service="EIP",
            resource_id=alloc_id,
            name=name,
            resource_type="elastic-ip",
            state=state,
            cost_usd=cost,
            hours=hours,
            region=region,
            tags=tags,
            waste_reason="unattached" if not attached else None,
            attributes={
                "public_ip": a.get("PublicIp", ""),
                "attached_instance_id": a.get("InstanceId"),
                "association_id": a.get("AssociationId"),
                "rate_usd_hr": idle_rate,
                "cost_basis": cost_basis,
            },
        ))
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows


def auto_assigned_ip_rows(
    instances: list[dict],
    region: str,
    window_start: datetime,
    window_end: datetime,
    exclude_ips: frozenset = frozenset(),
) -> list[AttributedResource]:
    """Rows for instance auto-assigned public IPv4 addresses (not EIPs).

    These bill at the same $0.005/hr under VPC ``PublicIPv4:InUseAddress``
    since Feb 2024 but never appear in ``describe_addresses``, so without this
    the VPC service total dwarfs the visible per-address rows (e.g. Elastic
    Beanstalk instances all carry auto-assigned public IPs).

    ``exclude_ips``: public IPs already covered by EIP rows (an associated
    EIP shows up as the instance's PublicIpAddress too — don't double count).
    """
    rate = pricing.eip_idle_rate()
    rows: list[AttributedResource] = []
    for inst in instances:
        ip = inst.get("PublicIpAddress") or ""
        if not ip or ip in exclude_ips:
            continue
        if (inst.get("State") or {}).get("Name") != "running":
            continue
        eff_s, eff_e = clamp_window(inst.get("LaunchTime"), window_start, window_end)
        hours = hours_between(eff_s, eff_e)
        if hours <= 0:
            continue
        rows.append(AttributedResource(
            service="EIP",
            resource_id=f"public-ip:{ip}",
            name=f"{ip} (auto-assigned)",
            resource_type="public-ipv4 (auto-assigned)",
            state="associated",
            cost_usd=hours * rate,
            hours=hours,
            region=region,
            attributes={
                "public_ip": ip,
                "attached_instance_id": inst.get("InstanceId"),
                "rate_usd_hr": rate,
                "cost_basis": "instance running hours @ public-IPv4 in-use rate",
            },
        ))
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows
