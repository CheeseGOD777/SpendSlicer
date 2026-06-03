"""S3 bucket attribution — list buckets and split the CE S3 total.

S3 billing is unusual: costs aren't per-bucket in the ListBuckets API
at all. We split by bucket storage size (CloudWatch
``BucketSizeBytes``) which correlates with the biggest S3 cost line
(storage). Request / data-transfer costs drift but usually don't
dominate.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .base import AttributedResource, tag_name, tags_to_dict

# FINDING 24: adaptive retries so throttling self-heals at the client layer.
_ADAPTIVE_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})


def _bucket_size_bytes(cw, name: str) -> float:
    """Latest CloudWatch BucketSizeBytes (StandardStorage) for a bucket, or 0."""
    try:
        end = datetime.now(tz=timezone.utc)
        start = end - timedelta(days=2)
        resp = cw.get_metric_statistics(
            Namespace="AWS/S3",
            MetricName="BucketSizeBytes",
            Dimensions=[
                {"Name": "BucketName", "Value": name},
                {"Name": "StorageType", "Value": "StandardStorage"},
            ],
            StartTime=start,
            EndTime=end,
            Period=86400,
            Statistics=["Average"],
        )
        pts = resp.get("Datapoints", [])
        if pts:
            return max(p.get("Average", 0.0) for p in pts)
    except ClientError:
        pass
    return 0.0


def attribute_s3_all(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    regions: list[str],
    ce_service_total_usd: float = 0.0,
) -> list[AttributedResource]:
    """Account-wide S3 attribution in ONE pass (FINDING 3).

    The S3 CE total is global, and bucket->region resolution is the same
    regardless of which region's client we use. Calling ``attribute_s3``
    once per region re-listed every bucket and re-resolved every bucket's
    location once per (bucket, region) — quadratic API fan-out.

    Here we: list buckets once, resolve each bucket's region exactly once,
    pull each bucket's CloudWatch size once, then split the global S3 CE
    total across ALL buckets account-wide by storage weight (equal split if
    no size signal). CloudWatch size and bucket tagging are read from a
    client in the bucket's own region.
    """
    s3 = session.client("s3", region_name="us-east-1", config=_ADAPTIVE_RETRY_CONFIG)
    try:
        buckets = s3.list_buckets().get("Buckets", [])
    except ClientError:
        return []
    if not buckets:
        return []

    region_set = set(regions) if regions else None

    # Resolve each bucket's region exactly once.
    bucket_region: dict[str, str] = {}
    for b in buckets:
        name = b["Name"]
        try:
            loc = s3.get_bucket_location(Bucket=name).get("LocationConstraint") or "us-east-1"
        except ClientError:
            continue
        if loc == "EU":
            loc = "eu-west-1"
        # Skip buckets outside the regions we were asked to scan.
        if region_set is not None and loc not in region_set:
            continue
        bucket_region[name] = loc

    if not bucket_region:
        return []

    # Per-region CloudWatch client cache (size metric lives in bucket's region).
    cw_by_region: dict[str, object] = {}

    def _cw(region: str):
        if region not in cw_by_region:
            cw_by_region[region] = session.client(
                "cloudwatch", region_name=region, config=_ADAPTIVE_RETRY_CONFIG,
            )
        return cw_by_region[region]

    # Per-region S3 client cache for tagging (tagging works cross-region but
    # using the bucket's region avoids redirect round-trips).
    s3_by_region: dict[str, object] = {"us-east-1": s3}

    def _s3(region: str):
        if region not in s3_by_region:
            s3_by_region[region] = session.client(
                "s3", region_name=region, config=_ADAPTIVE_RETRY_CONFIG,
            )
        return s3_by_region[region]

    creation_by_name = {b["Name"]: b.get("CreationDate") for b in buckets}

    weights: dict[str, float] = {}
    for name, reg in bucket_region.items():
        weights[name] = _bucket_size_bytes(_cw(reg), name)

    weight_sum = sum(weights.values()) or 0.0
    n_buckets = len(bucket_region)
    rows: list[AttributedResource] = []
    for name, reg in bucket_region.items():
        size_bytes = weights.get(name, 0.0)
        if weight_sum > 0:
            share = size_bytes / weight_sum
        elif ce_service_total_usd > 0:
            share = 1.0 / n_buckets
        else:
            share = 0.0
        cost = ce_service_total_usd * share

        tags: dict = {}
        try:
            tag_resp = _s3(reg).get_bucket_tagging(Bucket=name).get("TagSet", [])
            tags = tags_to_dict(tag_resp)
        except ClientError:
            tag_resp = None

        created = creation_by_name.get(name)
        rows.append(AttributedResource(
            service="S3",
            resource_id=name,
            name=tag_name(tag_resp if tags else None, fallback=name) if tags else name,
            resource_type="bucket",
            state="active",
            cost_usd=cost,
            hours=0.0,
            region=reg,
            tags=tags,
            attributes={
                "size_gb": round(size_bytes / (1024 ** 3), 3),
                "created": created.isoformat() if created else None,
            },
        ))
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows


def attribute_s3(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    region: str,
    ce_service_total_usd: float = 0.0,
) -> list[AttributedResource]:
    # NOTE: retained for backward-compat. The runner now calls
    # ``attribute_s3_all`` once account-wide (FINDING 3) instead of fanning
    # this per region. Kept here for any direct/legacy callers.
    s3 = session.client("s3", region_name=region, config=_ADAPTIVE_RETRY_CONFIG)
    try:
        buckets = s3.list_buckets().get("Buckets", [])
    except ClientError:
        return []
    if not buckets:
        return []

    # Filter to buckets in this region only — list_buckets is global.
    buckets_here: list[dict] = []
    for b in buckets:
        try:
            loc = s3.get_bucket_location(Bucket=b["Name"]).get("LocationConstraint") or "us-east-1"
            if loc == "EU":
                loc = "eu-west-1"
            if loc == region:
                buckets_here.append(b)
        except ClientError:
            continue
    if not buckets_here:
        return []

    # CloudWatch BucketSizeBytes for storage-weighted split.
    weights: dict[str, float] = {}
    try:
        cw = session.client("cloudwatch", region_name=region, config=_ADAPTIVE_RETRY_CONFIG)
        # BucketSizeBytes is a daily metric — grab yesterday's point.
        end = datetime.now(tz=timezone.utc)
        start = end - timedelta(days=2)
        for b in buckets_here:
            name = b["Name"]
            try:
                resp = cw.get_metric_statistics(
                    Namespace="AWS/S3",
                    MetricName="BucketSizeBytes",
                    Dimensions=[
                        {"Name": "BucketName", "Value": name},
                        {"Name": "StorageType", "Value": "StandardStorage"},
                    ],
                    StartTime=start,
                    EndTime=end,
                    Period=86400,
                    Statistics=["Average"],
                )
                pts = resp.get("Datapoints", [])
                if pts:
                    weights[name] = max(p.get("Average", 0.0) for p in pts)
                else:
                    weights[name] = 0.0
            except ClientError:
                weights[name] = 0.0
    except ClientError:
        pass

    weight_sum = sum(weights.values()) or 0.0
    rows: list[AttributedResource] = []
    for b in buckets_here:
        name = b["Name"]
        size_bytes = weights.get(name, 0.0)
        if weight_sum > 0:
            share = size_bytes / weight_sum
        elif ce_service_total_usd > 0:
            share = 1.0 / len(buckets_here)
        else:
            share = 0.0
        cost = ce_service_total_usd * share

        tags: dict = {}
        try:
            tag_resp = s3.get_bucket_tagging(Bucket=name).get("TagSet", [])
            tags = tags_to_dict(tag_resp)
        except ClientError:
            pass

        rows.append(AttributedResource(
            service="S3",
            resource_id=name,
            name=tag_name(tag_resp if tags else None, fallback=name) if tags else name,
            resource_type="bucket",
            state="active",
            cost_usd=cost,
            hours=0.0,
            region=region,
            tags=tags,
            attributes={
                "size_gb": round(size_bytes / (1024 ** 3), 3),
                "created": b.get("CreationDate").isoformat() if b.get("CreationDate") else None,
            },
        ))
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows
