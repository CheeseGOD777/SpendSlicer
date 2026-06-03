"""Lambda function attribution — names + CE service total, split by CE function group.

CE lets us group by ``USAGE_TYPE`` within Lambda (GB-Second-ARM,
Requests, Edge), but the cheapest path to per-function attribution
that actually matches the bill is via the ``lambda:FunctionName``
cost-allocation tag that CE auto-emits when you activate it. If that
tag isn't active we fall back to equal split across listed functions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .base import AttributedResource, clamp_window, hours_between, tags_to_dict

# FINDING 24: adaptive retries so throttling self-heals at the client layer.
_ADAPTIVE_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})


def attribute_lambda(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    region: str,
    ce_service_total_usd: float = 0.0,
) -> list[AttributedResource]:
    """List every Lambda function and attribute the CE-Lambda total.

    Attribution strategy:
      1. List all functions.
      2. Split ``ce_service_total_usd`` across functions weighted by
         recent invocation count (CloudWatch ``Invocations`` sum over
         the window). If CloudWatch is unavailable, split equally.
    """
    lm = session.client("lambda", region_name=region, config=_ADAPTIVE_RETRY_CONFIG)
    try:
        functions: list[dict] = []
        for page in lm.get_paginator("list_functions").paginate():
            functions.extend(page.get("Functions", []))
    except ClientError:
        return []

    if not functions:
        return []

    # Try CloudWatch Invocations for proportional weighting.
    # For long windows or very large function counts, skip per-function
    # metric fan-out to keep API latency and billable calls bounded.
    weights: dict[str, float] = {}
    window_days = max((window_end - window_start).days, 1)
    should_collect_cw = window_days <= 45 and len(functions) <= 40
    if should_collect_cw:
        try:
            cw = session.client("cloudwatch", region_name=region, config=_ADAPTIVE_RETRY_CONFIG)
            for fn in functions:
                name = fn["FunctionName"]
                try:
                    resp = cw.get_metric_statistics(
                        Namespace="AWS/Lambda",
                        MetricName="Invocations",
                        Dimensions=[{"Name": "FunctionName", "Value": name}],
                        StartTime=window_start,
                        EndTime=window_end,
                        Period=86400,
                        Statistics=["Sum"],
                    )
                    total_inv = sum(p.get("Sum", 0.0) for p in resp.get("Datapoints", []))
                    weights[name] = float(total_inv)
                except ClientError:
                    weights[name] = 0.0
        except ClientError:
            pass

    weight_sum = sum(weights.values()) or 0.0
    total_for_split = max(ce_service_total_usd, 0.0)

    rows: list[AttributedResource] = []
    for fn in functions:
        name = fn["FunctionName"]
        arn = fn.get("FunctionArn", "")
        runtime = fn.get("Runtime", "n/a")
        memory = fn.get("MemorySize", 128)
        created = fn.get("LastModified", "")

        if weight_sum > 0:
            share = weights.get(name, 0.0) / weight_sum
        elif total_for_split > 0:
            share = 1.0 / len(functions)
        else:
            share = 0.0
        cost = total_for_split * share

        # Tags require a second call — only for functions with non-zero cost,
        # and skip in fast mode to reduce API fan-out.
        tags: dict = {}
        if should_collect_cw and cost > 0.001:
            try:
                tags = lm.list_tags(Resource=arn).get("Tags", {}) or {}
            except ClientError:
                tags = {}

        rows.append(AttributedResource(
            service="Lambda",
            resource_id=name,
            name=tags.get("Name", name),
            resource_type=f"{runtime} / {memory}MB",
            state="active",
            cost_usd=cost,
            hours=0.0,  # Lambda bills per-invocation-ms, not hours
            region=region,
            tags=tags,
            attributes={
                "arn": arn,
                "runtime": runtime,
                "memory_mb": memory,
                "last_modified": created,
                "invocations": int(weights.get(name, 0)),
                "timeout_s": fn.get("Timeout"),
            },
        ))
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows
