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
from botocore.exceptions import ClientError

from .base import AttributedResource, tag_name, tags_to_dict


def attribute_s3(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    region: str,
    ce_service_total_usd: float = 0.0,
) -> list[AttributedResource]:
    s3 = session.client("s3", region_name=region)
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
        cw = session.client("cloudwatch", region_name=region)
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
