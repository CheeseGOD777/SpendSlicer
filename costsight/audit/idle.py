"""Idle / wasted resource finder.

Finds resources that are running but generating little or no value:
  - Stopped EC2 instances (still incur EBS and EIP charges)
  - Unattached EBS volumes
  - Unassociated Elastic IPs
  - Orphaned snapshots (owned by account, source volume deleted)
  - Idle RDS instances (stopped state)
  - Idle load balancers (no healthy targets)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)


@dataclass
class IdleResource:
    service: str
    resource_id: str
    resource_name: str
    region: str
    reason: str                         # human-readable waste reason
    estimated_monthly_cost_usd: float = 0.0
    attributes: dict = field(default_factory=dict)
    arn: str | None = None

    def to_dict(self) -> dict:
        return {
            "service": self.service,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "region": self.region,
            "reason": self.reason,
            "estimated_monthly_cost_usd": round(self.estimated_monthly_cost_usd, 4),
            "attributes": self.attributes,
            "arn": self.arn,
        }


def _tag_name(tags: list[dict] | None, fallback: str) -> str:
    for t in (tags or []):
        if t.get("Key") == "Name":
            return t.get("Value", fallback)
    return fallback


# $/GB-month by volume type (us-east-1 list; close enough for waste triage —
# the old flat $0.10 was 7x high for sc1 and ignored IOPS entirely).
_EBS_GB_MONTH = {
    "gp3": 0.08,
    "gp2": 0.10,
    "io1": 0.125,
    "io2": 0.125,
    "st1": 0.045,
    "sc1": 0.015,
    "standard": 0.05,
}
_IO_IOPS_MONTH = 0.065        # io1/io2 $/provisioned-IOPS-month (first tier)
_GP3_IOPS_MONTH = 0.005       # gp3 $/IOPS-month above the 3000 baseline
_GP3_BASELINE_IOPS = 3000
_EIP_MONTHLY_USD = round(730 * 0.005, 2)  # public-IPv4 rate x ~730 h/month


def _ebs_monthly_estimate(size_gb: float, vol_type: str, iops: float) -> float:
    """Type-aware monthly estimate: storage plus provisioned IOPS where billed."""
    vt = (vol_type or "").lower()
    rate = _EBS_GB_MONTH.get(vt, _EBS_GB_MONTH["gp2"])
    est = size_gb * rate
    if vt in ("io1", "io2"):
        est += max(iops or 0, 0) * _IO_IOPS_MONTH
    elif vt == "gp3" and (iops or 0) > _GP3_BASELINE_IOPS:
        est += (iops - _GP3_BASELINE_IOPS) * _GP3_IOPS_MONTH
    return est


def _rds_stopped_estimate(storage_gb: float, storage_rate: float, multi_az: bool) -> float:
    """A stopped RDS instance still bills allocated storage (x2 for Multi-AZ)."""
    return storage_gb * storage_rate * (2.0 if multi_az else 1.0)


# ---------------------------------------------------------------------------
# Per-resource-type finders
# ---------------------------------------------------------------------------

def _attached_volume_estimates(ec2, instance_ids: list[str]) -> dict[str, float]:
    """instance_id -> monthly $ of its attached EBS volumes (chunked filter)."""
    out: dict[str, float] = {}
    for i in range(0, len(instance_ids), 190):
        chunk = instance_ids[i:i + 190]
        for page in ec2.get_paginator("describe_volumes").paginate(
            Filters=[{"Name": "attachment.instance-id", "Values": chunk}]
        ):
            for vol in page.get("Volumes", []):
                est = _ebs_monthly_estimate(
                    vol.get("Size", 0), vol.get("VolumeType", "gp2"), vol.get("Iops", 0),
                )
                for att in vol.get("Attachments", []):
                    iid = att.get("InstanceId")
                    if iid in chunk:
                        out[iid] = out.get(iid, 0.0) + est
    return out


def find_stopped_ec2(session: boto3.Session, region: str) -> list[IdleResource]:
    """EC2 instances in stopped state — still charge for attached EBS / EIPs."""
    results: list[IdleResource] = []
    try:
        ec2 = session.client("ec2", region_name=region)
        stopped: list[dict] = []
        paginator = ec2.get_paginator("describe_instances")
        for page in paginator.paginate(
            Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]
        ):
            for res in page.get("Reservations", []):
                stopped.extend(res.get("Instances", []))

        # The finding text says "EBS volumes continue to accrue charges" —
        # price them instead of reporting $0.00 waste.
        vol_est: dict[str, float] = {}
        if stopped:
            try:
                vol_est = _attached_volume_estimates(
                    ec2, [i["InstanceId"] for i in stopped],
                )
            except ClientError:
                vol_est = {}

        for inst in stopped:
            name = _tag_name(inst.get("Tags"), inst["InstanceId"])
            results.append(IdleResource(
                service="EC2",
                resource_id=inst["InstanceId"],
                resource_name=name,
                region=region,
                reason="Instance is stopped — EBS volumes and EIPs continue to accrue charges",
                estimated_monthly_cost_usd=vol_est.get(inst["InstanceId"], 0.0),
                attributes={
                    "instance_type": inst.get("InstanceType", ""),
                    "az": inst.get("Placement", {}).get("AvailabilityZone", ""),
                    "stop_reason": inst.get("StateTransitionReason", ""),
                },
                arn=f"arn:aws:ec2:{region}:{inst.get('OwnerId', '')}:instance/{inst['InstanceId']}",
            ))
    except ClientError:
        pass
    return results


def find_unattached_ebs(session: boto3.Session, region: str) -> list[IdleResource]:
    """EBS volumes in 'available' state — not attached to any instance."""
    results: list[IdleResource] = []
    try:
        ec2 = session.client("ec2", region_name=region)
        paginator = ec2.get_paginator("describe_volumes")
        for page in paginator.paginate(
            Filters=[{"Name": "status", "Values": ["available"]}]
        ):
            for vol in page.get("Volumes", []):
                name = _tag_name(vol.get("Tags"), vol["VolumeId"])
                size_gb = vol.get("Size", 0)
                vol_type = vol.get("VolumeType", "gp2")
                estimated = _ebs_monthly_estimate(size_gb, vol_type, vol.get("Iops", 0))
                results.append(IdleResource(
                    service="EBS",
                    resource_id=vol["VolumeId"],
                    resource_name=name,
                    region=region,
                    reason=f"Volume not attached to any instance ({size_gb} GB {vol_type})",
                    estimated_monthly_cost_usd=estimated,
                    attributes={
                        "size_gb": size_gb,
                        "volume_type": vol_type,
                        "iops": vol.get("Iops", 0),
                        "create_time": vol.get("CreateTime", "").isoformat() if hasattr(vol.get("CreateTime", ""), "isoformat") else str(vol.get("CreateTime", "")),
                    },
                    arn=f"arn:aws:ec2:{region}::volume/{vol['VolumeId']}",
                ))
    except ClientError:
        pass
    return results


def find_unused_eips(session: boto3.Session, region: str) -> list[IdleResource]:
    """Elastic IPs not associated with any running instance or network interface."""
    results: list[IdleResource] = []
    try:
        ec2 = session.client("ec2", region_name=region)
        resp = ec2.describe_addresses()
        for addr in resp.get("Addresses", []):
            # If no association, it's idle — $0.005/hr = ~$3.60/month
            if not addr.get("AssociationId"):
                name = _tag_name(addr.get("Tags"), addr.get("PublicIp", ""))
                results.append(IdleResource(
                    service="EIP",
                    resource_id=addr.get("AllocationId", addr.get("PublicIp", "")),
                    resource_name=name,
                    region=region,
                    reason="Elastic IP not associated with any instance or network interface",
                    estimated_monthly_cost_usd=_EIP_MONTHLY_USD,
                    attributes={
                        "public_ip": addr.get("PublicIp", ""),
                        "allocation_id": addr.get("AllocationId", ""),
                        "domain": addr.get("Domain", "vpc"),
                    },
                ))
    except ClientError:
        pass
    return results


def find_orphaned_snapshots(session: boto3.Session, region: str) -> list[IdleResource]:
    """EBS snapshots whose source volume has been deleted."""
    results: list[IdleResource] = []
    try:
        ec2 = session.client("ec2", region_name=region)
        # Only snapshots owned by this account
        sts = session.client("sts")
        try:
            account_id = sts.get_caller_identity()["Account"]
        except Exception as exc:
            log.warning("orphaned snapshot check: STS get_caller_identity failed: %s", type(exc).__name__, exc_info=True)
            return results

        # Collect existing volume IDs
        existing_volumes: set[str] = set()
        vol_pager = ec2.get_paginator("describe_volumes")
        for page in vol_pager.paginate():
            for v in page.get("Volumes", []):
                existing_volumes.add(v["VolumeId"])

        snap_pager = ec2.get_paginator("describe_snapshots")
        for page in snap_pager.paginate(OwnerIds=[account_id]):
            for snap in page.get("Snapshots", []):
                vol_id = snap.get("VolumeId", "")
                # vol-ffffffff or a real ID not in the account's volume list
                is_orphan = (
                    not vol_id
                    or vol_id == "vol-ffffffff"
                    or (vol_id.startswith("vol-") and vol_id not in existing_volumes)
                )
                if not is_orphan:
                    continue
                name = _tag_name(snap.get("Tags"), snap["SnapshotId"])
                size_gb = snap.get("VolumeSize", 0)
                estimated = size_gb * 0.05  # $0.05/GB-month for snapshots
                results.append(IdleResource(
                    service="EBS Snapshot",
                    resource_id=snap["SnapshotId"],
                    resource_name=name,
                    region=region,
                    reason=f"Source volume {vol_id or 'unknown'} no longer exists",
                    estimated_monthly_cost_usd=estimated,
                    attributes={
                        "size_gb": size_gb,
                        "source_volume_id": vol_id,
                        "start_time": snap.get("StartTime", "").isoformat() if hasattr(snap.get("StartTime", ""), "isoformat") else str(snap.get("StartTime", "")),
                        "description": snap.get("Description", ""),
                    },
                    arn=f"arn:aws:ec2:{region}::snapshot/{snap['SnapshotId']}",
                ))
    except ClientError:
        pass
    return results


def find_stopped_rds(session: boto3.Session, region: str) -> list[IdleResource]:
    """RDS instances in 'stopped' state (AWS auto-starts after 7 days anyway)."""
    results: list[IdleResource] = []
    try:
        rds = session.client("rds", region_name=region)
        paginator = rds.get_paginator("describe_db_instances")
        for page in paginator.paginate():
            for db in page.get("DBInstances", []):
                if db.get("DBInstanceStatus") != "stopped":
                    continue
                from costsight.core import pricing
                storage_rate = pricing.rds_storage_rate(
                    session, db.get("StorageType", "gp2"), region,
                )
                results.append(IdleResource(
                    service="RDS",
                    resource_id=db["DBInstanceIdentifier"],
                    resource_name=db["DBInstanceIdentifier"],
                    region=region,
                    reason="RDS instance is stopped — storage charges still apply; AWS will auto-restart after 7 days",
                    estimated_monthly_cost_usd=_rds_stopped_estimate(
                        db.get("AllocatedStorage", 0), storage_rate,
                        db.get("MultiAZ", False),
                    ),
                    attributes={
                        "engine": db.get("Engine", ""),
                        "instance_class": db.get("DBInstanceClass", ""),
                        "multi_az": db.get("MultiAZ", False),
                        "storage_gb": db.get("AllocatedStorage", 0),
                    },
                    arn=db.get("DBInstanceArn"),
                ))
    except ClientError:
        pass
    return results


def find_idle_load_balancers(session: boto3.Session, region: str) -> list[IdleResource]:
    """ELBv2 load balancers with no registered (healthy) targets."""
    results: list[IdleResource] = []
    try:
        elbv2 = session.client("elbv2", region_name=region)
        paginator = elbv2.get_paginator("describe_load_balancers")
        for page in paginator.paginate():
            for lb in page.get("LoadBalancers", []):
                lb_arn = lb["LoadBalancerArn"]
                # Check target groups
                tg_resp = elbv2.describe_target_groups(LoadBalancerArn=lb_arn)
                healthy_total = 0
                for tg in tg_resp.get("TargetGroups", []):
                    try:
                        health_resp = elbv2.describe_target_health(TargetGroupArn=tg["TargetGroupArn"])
                        healthy_total += sum(
                            1 for t in health_resp.get("TargetHealthDescriptions", [])
                            if t.get("TargetHealth", {}).get("State") == "healthy"
                        )
                    except ClientError:
                        pass

                if healthy_total == 0:
                    # ~$16-18/month baseline for ALB/NLB even with zero traffic
                    results.append(IdleResource(
                        service="ELB",
                        resource_id=lb["LoadBalancerName"],
                        resource_name=lb["LoadBalancerName"],
                        region=region,
                        reason="Load balancer has no healthy registered targets",
                        estimated_monthly_cost_usd=16.0,
                        attributes={
                            "type": lb.get("Type", ""),
                            "scheme": lb.get("Scheme", ""),
                            "dns_name": lb.get("DNSName", ""),
                            "state": lb.get("State", {}).get("Code", ""),
                        },
                        arn=lb_arn,
                    ))
    except ClientError:
        pass
    return results


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

def find_idle_resources(
    session: boto3.Session,
    region: str,
    checks: list[str] | None = None,
) -> list[IdleResource]:
    """Run all idle-resource checks for one region.

    ``checks`` filters which checks to run. Defaults to all:
    ``["stopped_ec2", "unattached_ebs", "unused_eips", "orphaned_snapshots",
      "stopped_rds", "idle_elb"]``
    """
    active = set(checks or [
        "stopped_ec2", "unattached_ebs", "unused_eips",
        "orphaned_snapshots", "stopped_rds", "idle_elb",
    ])
    out: list[IdleResource] = []

    if "stopped_ec2" in active:
        out.extend(find_stopped_ec2(session, region))
    if "unattached_ebs" in active:
        out.extend(find_unattached_ebs(session, region))
    if "unused_eips" in active:
        out.extend(find_unused_eips(session, region))
    if "orphaned_snapshots" in active:
        out.extend(find_orphaned_snapshots(session, region))
    if "stopped_rds" in active:
        out.extend(find_stopped_rds(session, region))
    if "idle_elb" in active:
        out.extend(find_idle_load_balancers(session, region))

    return out
