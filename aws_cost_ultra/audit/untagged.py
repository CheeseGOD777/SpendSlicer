"""Untagged resource finder.

Scans EC2, RDS, Lambda, and ELBv2 for resources missing one or more
required cost-allocation tags. Results are used by the audit runner to
build "you're flying blind on attribution" findings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import boto3
from botocore.exceptions import ClientError


@dataclass
class UntaggedResource:
    service: str           # "EC2" | "RDS" | "Lambda" | "ELB"
    resource_id: str
    resource_name: str
    region: str
    missing_tags: list[str]
    existing_tags: dict = field(default_factory=dict)
    arn: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "service": self.service,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "region": self.region,
            "missing_tags": self.missing_tags,
            "existing_tags": self.existing_tags,
            "arn": self.arn,
        }


def _missing(tags: dict, required: list[str]) -> list[str]:
    return [k for k in required if k not in tags or not tags[k]]


def _tags_dict(tag_list: list[dict] | None) -> dict:
    if not tag_list:
        return {}
    return {t.get("Key", ""): t.get("Value", "") for t in tag_list if t.get("Key")}


# ---------------------------------------------------------------------------
# Per-service scanners
# ---------------------------------------------------------------------------

def scan_ec2(
    session: boto3.Session,
    region: str,
    required_tags: list[str],
) -> list[UntaggedResource]:
    results: list[UntaggedResource] = []
    try:
        ec2 = session.client("ec2", region_name=region)
        paginator = ec2.get_paginator("describe_instances")
        for page in paginator.paginate():
            for res in page.get("Reservations", []):
                for inst in res.get("Instances", []):
                    if inst["State"]["Name"] == "terminated":
                        continue
                    tags = _tags_dict(inst.get("Tags"))
                    missing = _missing(tags, required_tags)
                    if not missing:
                        continue
                    name = tags.get("Name") or inst["InstanceId"]
                    results.append(UntaggedResource(
                        service="EC2",
                        resource_id=inst["InstanceId"],
                        resource_name=name,
                        region=region,
                        missing_tags=missing,
                        existing_tags=tags,
                        arn=f"arn:aws:ec2:{region}:{inst.get('OwnerId', '')}:instance/{inst['InstanceId']}",
                    ))
    except ClientError:
        pass
    return results


def scan_rds(
    session: boto3.Session,
    region: str,
    required_tags: list[str],
) -> list[UntaggedResource]:
    results: list[UntaggedResource] = []
    try:
        rds = session.client("rds", region_name=region)
        paginator = rds.get_paginator("describe_db_instances")
        for page in paginator.paginate():
            for db in page.get("DBInstances", []):
                tags = _tags_dict(db.get("TagList"))
                missing = _missing(tags, required_tags)
                if not missing:
                    continue
                results.append(UntaggedResource(
                    service="RDS",
                    resource_id=db["DBInstanceIdentifier"],
                    resource_name=db["DBInstanceIdentifier"],
                    region=region,
                    missing_tags=missing,
                    existing_tags=tags,
                    arn=db.get("DBInstanceArn"),
                ))
    except ClientError:
        pass
    return results


def scan_lambda(
    session: boto3.Session,
    region: str,
    required_tags: list[str],
) -> list[UntaggedResource]:
    results: list[UntaggedResource] = []
    try:
        lm = session.client("lambda", region_name=region)
        paginator = lm.get_paginator("list_functions")
        for page in paginator.paginate():
            for fn in page.get("Functions", []):
                fn_arn = fn["FunctionArn"]
                # Tags aren't in list_functions; need a separate call
                try:
                    tag_resp = lm.list_tags(Resource=fn_arn)
                    tags = tag_resp.get("Tags", {})
                except ClientError:
                    tags = {}
                missing = _missing(tags, required_tags)
                if not missing:
                    continue
                results.append(UntaggedResource(
                    service="Lambda",
                    resource_id=fn["FunctionName"],
                    resource_name=fn["FunctionName"],
                    region=region,
                    missing_tags=missing,
                    existing_tags=tags,
                    arn=fn_arn,
                ))
    except ClientError:
        pass
    return results


def scan_elb(
    session: boto3.Session,
    region: str,
    required_tags: list[str],
) -> list[UntaggedResource]:
    results: list[UntaggedResource] = []
    try:
        elbv2 = session.client("elbv2", region_name=region)
        paginator = elbv2.get_paginator("describe_load_balancers")
        for page in paginator.paginate():
            for lb in page.get("LoadBalancers", []):
                lb_arn = lb["LoadBalancerArn"]
                try:
                    tag_resp = elbv2.describe_tags(ResourceArns=[lb_arn])
                    tag_list = tag_resp.get("TagDescriptions", [{}])[0].get("Tags", [])
                    tags = _tags_dict(tag_list)
                except ClientError:
                    tags = {}
                missing = _missing(tags, required_tags)
                if not missing:
                    continue
                results.append(UntaggedResource(
                    service="ELB",
                    resource_id=lb["LoadBalancerName"],
                    resource_name=lb["LoadBalancerName"],
                    region=region,
                    missing_tags=missing,
                    existing_tags=tags,
                    arn=lb_arn,
                ))
    except ClientError:
        pass
    return results


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

def scan_untagged(
    session: boto3.Session,
    region: str,
    required_tags: list[str],
    services: list[str] | None = None,
) -> list[UntaggedResource]:
    """Scan one region for resources missing required cost-allocation tags.

    ``services`` defaults to all four: EC2, RDS, Lambda, ELB.
    """
    if not required_tags:
        return []

    active = set(services or ["EC2", "RDS", "Lambda", "ELB"])
    out: list[UntaggedResource] = []

    if "EC2" in active:
        out.extend(scan_ec2(session, region, required_tags))
    if "RDS" in active:
        out.extend(scan_rds(session, region, required_tags))
    if "Lambda" in active:
        out.extend(scan_lambda(session, region, required_tags))
    if "ELB" in active:
        out.extend(scan_elb(session, region, required_tags))

    return out
