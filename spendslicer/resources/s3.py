"""S3 bucket attribution — list buckets and split the CE S3 total.

S3 billing is unusual: costs aren't per-bucket in the ListBuckets API
at all. We split by bucket storage size (CloudWatch
``BucketSizeBytes``) which correlates with the biggest S3 cost line
(storage). Request / data-transfer costs drift but usually don't
dominate.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .base import AttributedResource, tag_name, tags_to_dict

log = logging.getLogger(__name__)

# Adaptive retries so throttling self-heals at the client layer.
_ADAPTIVE_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})

# Bound the per-bucket API fan-out width. boto3 low-level clients are safe for
# concurrent calls once constructed; this caps in-flight requests so a
# bucket-heavy account doesn't open thousands of sockets at once.
_S3_FANOUT_WORKERS = 16
# Safety valve: on accounts with an extreme bucket count, attribute only the
# first N (ListBuckets order) and log what was dropped rather than stalling.
_MAX_S3_BUCKETS = 5000


# All S3 storage-class dimensions CloudWatch reports BucketSizeBytes for.
# Weighting on StandardStorage alone gave IA/Glacier/Intelligent-Tiering-heavy
# buckets ~0 weight (and thus ~$0 attribution, with their cost redistributed
# onto Standard buckets). Sum across every class instead.
_S3_STORAGE_TYPES = (
    "StandardStorage",
    "IntelligentTieringFAStorage",
    "IntelligentTieringIAStorage",
    "IntelligentTieringAAStorage",
    "IntelligentTieringAIAStorage",
    "IntelligentTieringDAAStorage",
    "StandardIAStorage",
    "StandardIASizeOverhead",
    "OneZoneIAStorage",
    "OneZoneIASizeOverhead",
    "ReducedRedundancyStorage",
    "GlacierInstantRetrievalStorage",
    "GlacierStorage",
    "GlacierStagingStorage",
    "DeepArchiveStorage",
    "DeepArchiveStagingStorage",
)


def _bucket_size_bytes(cw, name: str) -> float:
    """Total CloudWatch BucketSizeBytes across ALL storage classes, or 0.

    One GetMetricData call batches every storage-class query for the bucket.
    """
    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(days=2)
    queries = [
        {
            "Id": f"m{i}",
            "MetricStat": {
                "Metric": {
                    "Namespace": "AWS/S3",
                    "MetricName": "BucketSizeBytes",
                    "Dimensions": [
                        {"Name": "BucketName", "Value": name},
                        {"Name": "StorageType", "Value": st},
                    ],
                },
                "Period": 86400,
                "Stat": "Average",
            },
            "ReturnData": True,
        }
        for i, st in enumerate(_S3_STORAGE_TYPES)
    ]
    try:
        resp = cw.get_metric_data(MetricDataQueries=queries, StartTime=start, EndTime=end)
    except ClientError:
        return 0.0
    total = 0.0
    for r in resp.get("MetricDataResults", []):
        vals = r.get("Values", [])
        if vals:
            # Latest (results are time-ordered desc by default); use max to be safe.
            total += max(vals)
    return total


def attribute_s3_all(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    regions: list[str],
    ce_service_total_usd: float = 0.0,
) -> list[AttributedResource]:
    """Account-wide S3 attribution in ONE pass.

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

    if len(buckets) > _MAX_S3_BUCKETS:
        log.warning(
            "attribute_s3_all: %d buckets exceeds cap %d; attributing the first "
            "%d only (S3 cost for the remainder is not broken out per bucket)",
            len(buckets), _MAX_S3_BUCKETS, _MAX_S3_BUCKETS,
        )
        buckets = buckets[:_MAX_S3_BUCKETS]

    # AUDIT (scale): the three per-bucket round-trips below — get_bucket_location,
    # CloudWatch BucketSizeBytes, get_bucket_tagging — were each a sequential
    # loop over every bucket, so a bucket-heavy account stalled for minutes on
    # one single-threaded work unit. Fan them out across a bounded pool instead.
    pool = ThreadPoolExecutor(max_workers=min(_S3_FANOUT_WORKERS, len(buckets)))
    try:
        # Phase 1: resolve each bucket's region exactly once (concurrent).
        def _resolve(b):
            name = b["Name"]
            try:
                loc = s3.get_bucket_location(Bucket=name).get("LocationConstraint") or "us-east-1"
            except ClientError:
                return None
            if loc == "EU":
                loc = "eu-west-1"
            return (name, loc)

        bucket_region: dict[str, str] = {}
        for res in pool.map(_resolve, buckets):
            if res is None:
                continue
            name, loc = res
            if region_set is not None and loc not in region_set:
                continue
            bucket_region[name] = loc

        if not bucket_region:
            return []

        # Pre-build one CloudWatch + one S3 client per region up front. The lazy
        # dict caches used previously would race under concurrent access; boto3
        # client *construction* is not thread-safe, but constructed clients are
        # safe to call concurrently, so build them all before fanning out.
        needed_regions = set(bucket_region.values())
        cw_by_region = {r: session.client("cloudwatch", region_name=r, config=_ADAPTIVE_RETRY_CONFIG) for r in needed_regions}
        s3_by_region = {"us-east-1": s3}
        for r in needed_regions:
            if r not in s3_by_region:
                s3_by_region[r] = session.client("s3", region_name=r, config=_ADAPTIVE_RETRY_CONFIG)

        creation_by_name = {b["Name"]: b.get("CreationDate") for b in buckets}

        # Phase 2: per bucket, fetch size + tags concurrently.
        def _fetch(item):
            name, reg = item
            size_bytes = _bucket_size_bytes(cw_by_region[reg], name)
            tags: dict = {}
            tag_resp = None
            try:
                tag_resp = s3_by_region[reg].get_bucket_tagging(Bucket=name).get("TagSet", [])
                tags = tags_to_dict(tag_resp)
            except ClientError:
                tag_resp = None
            return name, reg, size_bytes, tags, tag_resp

        fetched = list(pool.map(_fetch, list(bucket_region.items())))
    finally:
        pool.shutdown(wait=True)

    weight_sum = sum(f[2] for f in fetched) or 0.0
    n_buckets = len(fetched)
    rows: list[AttributedResource] = []
    for name, reg, size_bytes, tags, tag_resp in fetched:
        if weight_sum > 0:
            share = size_bytes / weight_sum
        elif ce_service_total_usd > 0:
            share = 1.0 / n_buckets
        else:
            share = 0.0
        cost = ce_service_total_usd * share

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
    # ``attribute_s3_all`` once account-wide instead of fanning
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
