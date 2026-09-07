"""CloudFront attribution — CE service total split by measured traffic.

CloudFront is global: list_distributions returns the same set from every
endpoint, so the runner submits this once per account rather than once per
region.

CloudFront's cost is requests plus data transfer out, and both are published
per distribution as CloudWatch metrics in us-east-1. Bytes carry most of the
bill on a typical distribution, so BytesDownloaded is the weight, with
Requests as a fallback when a distribution serves tiny objects. Neither
available means an equal split, and cost_basis records which was used.
"""

from __future__ import annotations

from datetime import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .base import AttributedResource

_ADAPTIVE_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})

# CloudFront metrics live in us-east-1 regardless of where the caller is.
_CF_METRIC_REGION = "us-east-1"
# One CloudWatch call per distribution per metric; cap the fan-out.
_MAX_DISTS_FOR_METRICS = 50


def _metric_sum(cw, dist_id: str, metric: str, start: datetime, end: datetime) -> float:
    try:
        resp = cw.get_metric_statistics(
            Namespace="AWS/CloudFront",
            MetricName=metric,
            Dimensions=[
                {"Name": "DistributionId", "Value": dist_id},
                {"Name": "Region", "Value": "Global"},
            ],
            StartTime=start,
            EndTime=end,
            Period=86400,
            Statistics=["Sum"],
        )
        return sum(float(p.get("Sum", 0) or 0) for p in resp.get("Datapoints", []))
    except ClientError:
        return 0.0


def attribute_cloudfront(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    ce_service_total_usd: float = 0.0,
) -> list[AttributedResource]:
    """Account-wide, not per region — CloudFront has no regional endpoint."""
    cf = session.client("cloudfront", config=_ADAPTIVE_RETRY_CONFIG)
    dists: list[dict] = []
    try:
        for page in cf.get_paginator("list_distributions").paginate():
            dists.extend((page.get("DistributionList") or {}).get("Items", []) or [])
    except ClientError:
        return []
    if not dists:
        return []

    bytes_w: dict[str, float] = {}
    reqs_w: dict[str, float] = {}
    if len(dists) <= _MAX_DISTS_FOR_METRICS:
        try:
            cw = session.client(
                "cloudwatch", region_name=_CF_METRIC_REGION, config=_ADAPTIVE_RETRY_CONFIG
            )
            for d in dists:
                did = d["Id"]
                bytes_w[did] = _metric_sum(cw, did, "BytesDownloaded", window_start, window_end)
                reqs_w[did] = _metric_sum(cw, did, "Requests", window_start, window_end)
        except ClientError:
            bytes_w, reqs_w = {}, {}

    if sum(bytes_w.values()) > 0:
        weights, basis = bytes_w, "CE service total split by bytes downloaded"
    elif sum(reqs_w.values()) > 0:
        weights, basis = reqs_w, "CE service total split by request count"
    else:
        weights, basis = {}, "CE service total split equally (no CloudWatch data)"
    total_w = sum(weights.values())

    rows: list[AttributedResource] = []
    for d in dists:
        did = d["Id"]
        share = (weights.get(did, 0.0) / total_w) if total_w > 0 else 1.0 / len(dists)
        aliases = (d.get("Aliases") or {}).get("Items") or []
        rows.append(AttributedResource(
            service="CloudFront",
            resource_id=did,
            name=aliases[0] if aliases else d.get("DomainName", did),
            resource_type="distribution",
            state="enabled" if d.get("Enabled") else "disabled",
            cost_usd=ce_service_total_usd * share,
            hours=0.0,
            region="global",
            tags={},
            attributes={
                "domain_name": d.get("DomainName", ""),
                "aliases": ", ".join(aliases),
                "price_class": d.get("PriceClass", ""),
                "gb_downloaded": round(bytes_w.get(did, 0.0) / (1024 ** 3), 3),
                "requests": int(reqs_w.get(did, 0.0)),
                "share_of_service_pct": round(share * 100, 2),
                "cost_basis": basis,
            },
        ))
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows
