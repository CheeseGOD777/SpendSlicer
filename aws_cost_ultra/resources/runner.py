"""Parallel enumerator — all CE services, all regions (account-wide accuracy)."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import boto3

log = logging.getLogger(__name__)

from aws_cost_ultra.aws.cost_explorer import CostExplorerClient
from aws_cost_ultra.aws.session import accessible_regions
from aws_cost_ultra.core.filters import CostFilterSpec, pre_credit_gross
from aws_cost_ultra.core.types import TimeWindow

from .base import AttributedResource
from .dynamodb import attribute_dynamodb
from .ebs import attribute_ebs
from .ec2 import attribute_ec2_account, live_instance_names
from .eip import attribute_eip
from .elb import attribute_elb
from .lambda_fn import attribute_lambda
from .rds import attribute_rds
from .s3 import attribute_s3

SERVICE_TO_CE: dict[str, str] = {
    "EC2": "Amazon Elastic Compute Cloud - Compute",
    "EBS": "EC2 - Other",
    "EIP": "EC2 - Other",
    "RDS": "Amazon Relational Database Service",
    "ELB": "Amazon Elastic Load Balancing",
    "Lambda": "AWS Lambda",
    "S3": "Amazon Simple Storage Service",
    "DynamoDB": "Amazon DynamoDB",
}

ENUMERATED_CE_SERVICES: set[str] = set(SERVICE_TO_CE.values())

ALL_REGIONS = "all"


def _resolve_regions(session: boto3.Session, region: str) -> list[str]:
    if region == ALL_REGIONS:
        return accessible_regions(session)
    return [region]


def _frozen_session(base: boto3.Session, region: str) -> boto3.Session:
    """Return a new Session with frozen credentials safe to use in a thread."""
    creds = base.get_credentials()
    if creds is not None:
        c = creds.get_frozen_credentials()
        return boto3.Session(
            aws_access_key_id=c.access_key,
            aws_secret_access_key=c.secret_key,
            aws_session_token=c.token,
            region_name=region,
        )
    return boto3.Session(region_name=region)


def enumerate_all(
    session: boto3.Session,
    window: TimeWindow,
    region: str = ALL_REGIONS,
    spec: Optional[CostFilterSpec] = None,
    services: Optional[list[str]] = None,
) -> list[AttributedResource]:
    """Per-resource rows + CE aggregate rows for every active service.

    ``region`` may be a single region code or ``"all"`` (default) to scan
    every opted-in region — required for account-wide CE totals to match
    attributed resource sums.
    """
    spec = spec or pre_credit_gross()
    regions = _resolve_regions(session, region)
    display_region = region if region != ALL_REGIONS else ALL_REGIONS

    ws = window.start.replace(tzinfo=None) if window.start.tzinfo else window.start
    we = window.end.replace(tzinfo=None) if window.end.tzinfo else window.end

    ce_raw = session.client("ce", region_name="us-east-1")
    ce_hl = CostExplorerClient(session=session, ce_client=ce_raw)

    try:
        ce_groups = ce_hl.get_cost_by_service(window, spec=spec)
        ce_total_by_service = {g.primary_key(): g.value.amount_usd for g in ce_groups}
    except Exception as exc:
        log.warning("enumerate_all: CE get_cost_by_service failed, continuing without CE totals: %s", type(exc).__name__, exc_info=True)
        ce_total_by_service = {}

    def ce_total(label: str) -> float:
        return ce_total_by_service.get(SERVICE_TO_CE.get(label, ""), 0.0)

    want = set(services) if services else None

    def want_it(label: str) -> bool:
        return want is None or label in want

    buckets: dict[str, list[AttributedResource]] = {}

    with ThreadPoolExecutor(max_workers=min(16, max(len(regions) * 2, 4))) as pool:
        jobs: dict = {}

        if want_it("EC2"):
            jobs["ec2"] = pool.submit(
                attribute_ec2_account, session, ce_raw, ws, we, regions, spec,
            )

        def _fanout_regions(fn, *extra_args):
            out: list[AttributedResource] = []
            with ThreadPoolExecutor(max_workers=min(12, len(regions))) as reg_pool:
                futs = {
                    reg_pool.submit(fn, _frozen_session(session, reg), ws, we, reg, *extra_args): reg
                    for reg in regions
                }
                for fut in as_completed(futs):
                    try:
                        out.extend(fut.result())
                    except Exception as exc:
                        log.warning("resource fanout failed for region=%s: %s", futs[fut], type(exc).__name__, exc_info=True)
            return out

        if want_it("RDS"):
            jobs["rds"] = pool.submit(_fanout_regions, attribute_rds)
        if want_it("EIP"):
            jobs["eip"] = pool.submit(_fanout_regions, attribute_eip)
        if want_it("ELB"):
            jobs["elb"] = pool.submit(_fanout_regions, attribute_elb)
        if want_it("Lambda"):
            jobs["lambda"] = pool.submit(_fanout_regions, attribute_lambda, ce_total("Lambda"))
        if want_it("S3"):
            jobs["s3"] = pool.submit(_fanout_regions, attribute_s3, ce_total("S3"))
        if want_it("DynamoDB"):
            jobs["ddb"] = pool.submit(_fanout_regions, attribute_dynamodb, ce_total("DynamoDB"))

        if want_it("EBS"):
            def _ebs_all_regions():
                out: list[AttributedResource] = []
                for reg in regions:
                    ts = _frozen_session(session, reg)
                    names = live_instance_names(ts, reg)
                    try:
                        out.extend(attribute_ebs(ts, ws, we, reg, names))
                    except Exception as exc:
                        log.warning("EBS attribution failed for region=%s: %s", reg, type(exc).__name__, exc_info=True)
                return out
            jobs["ebs"] = pool.submit(_ebs_all_regions)

        label_for_key = {
            "ec2": "EC2", "ebs": "EBS", "rds": "RDS", "eip": "EIP",
            "elb": "ELB", "lambda": "Lambda", "s3": "S3", "ddb": "DynamoDB",
        }
        for key, label in label_for_key.items():
            if key in jobs:
                try:
                    buckets[label] = jobs[key].result()
                except Exception as exc:
                    log.warning("resource enumeration job failed for service=%s: %s", label, type(exc).__name__, exc_info=True)
                    buckets[label] = []

    other_pool = ce_total_by_service.get("EC2 - Other", 0.0)
    if other_pool > 0 and (buckets.get("EBS") or buckets.get("EIP")):
        raw_sum = (
            sum(r.cost_usd for r in buckets.get("EBS", []))
            + sum(r.cost_usd for r in buckets.get("EIP", []))
        )
        if raw_sum > 0:
            factor = other_pool / raw_sum
            for r in buckets.get("EBS", []):
                r.cost_usd *= factor
            for r in buckets.get("EIP", []):
                r.cost_usd *= factor

    for label, ce_name in [
        ("RDS", "Amazon Relational Database Service"),
        ("ELB", "Amazon Elastic Load Balancing"),
    ]:
        rows = buckets.get(label, [])
        ce_tot = ce_total_by_service.get(ce_name)
        if not rows or not ce_tot or ce_tot <= 0:
            continue
        raw_sum = sum(r.cost_usd for r in rows)
        if raw_sum > 0:
            factor = ce_tot / raw_sum
            for r in rows:
                r.cost_usd *= factor

    other_rows: list[AttributedResource] = []
    for ce_name, total in ce_total_by_service.items():
        if total <= 0.001:
            continue
        if ce_name in ENUMERATED_CE_SERVICES:
            continue
        label = _short_label(ce_name)
        if want is not None and label not in want:
            continue
        other_rows.append(AttributedResource(
            service=label,
            resource_id=f"ce:{ce_name}",
            name=ce_name,
            resource_type="service aggregate",
            state="active",
            cost_usd=total,
            hours=0.0,
            region=display_region,
            attributes={
                "aggregate": True,
                "ce_service_name": ce_name,
                "note": "CE total — per-resource breakdown not yet available",
            },
        ))

    flat: list[AttributedResource] = []
    for svc_rows in buckets.values():
        flat.extend(svc_rows)
    flat.extend(other_rows)
    flat.sort(key=lambda r: r.cost_usd, reverse=True)
    return flat


_SHORT_LABEL_MAP = {
    "Amazon Virtual Private Cloud": "VPC",
    "AmazonCloudWatch": "CloudWatch",
    "Amazon CloudWatch": "CloudWatch",
    "AWS Cost Explorer": "CostExplorer",
    "AWS CloudTrail": "CloudTrail",
    "AWS CloudFormation": "CloudFormation",
    "AWS CodePipeline": "CodePipeline",
    "CodeBuild": "CodeBuild",
    "AWS Step Functions": "StepFunctions",
    "AWS Key Management Service": "KMS",
    "AWS Secrets Manager": "SecretsMgr",
    "Amazon Simple Notification Service": "SNS",
    "Amazon Simple Queue Service": "SQS",
    "Amazon Route 53": "Route53",
    "Amazon API Gateway": "APIGateway",
    "Amazon ElastiCache": "ElastiCache",
    "Amazon Elasticsearch Service": "OpenSearch",
    "Amazon OpenSearch Service": "OpenSearch",
    "Amazon EC2 Container Registry (ECR)": "ECR",
    "Amazon Elastic Container Service": "ECS",
    "Amazon Elastic Container Service for Kubernetes": "EKS",
    "Amazon Elastic Kubernetes Service": "EKS",
    "Amazon CloudFront": "CloudFront",
    "Amazon Athena": "Athena",
    "Amazon Kinesis": "Kinesis",
    "AWS Glue": "Glue",
    "AWS Backup": "Backup",
    "AWS WAF": "WAF",
    "AWS Shield": "Shield",
    "AWS Lambda": "Lambda",
    "AWS Systems Manager": "SSM",
    "AWS CloudShell": "CloudShell",
    "AmazonS3 Glacier": "S3 Glacier",
}


def _short_label(ce_service_name: str) -> str:
    if ce_service_name in _SHORT_LABEL_MAP:
        return _SHORT_LABEL_MAP[ce_service_name]
    for prefix in ("Amazon ", "AWS "):
        if ce_service_name.startswith(prefix):
            return ce_service_name[len(prefix):]
    return ce_service_name
