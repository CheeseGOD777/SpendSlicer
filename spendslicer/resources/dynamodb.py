"""DynamoDB table attribution — conservative, activity-weighted.

We only attribute CE DynamoDB spend to tables with observed usage over
the selected window (ConsumedRead/WriteCapacityUnits). If no activity
signal is available, we return no per-resource rows and leave that
spend in service-level aggregate drift to avoid false positives.
"""

from __future__ import annotations

import logging
from datetime import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .base import AttributedResource, tags_to_dict

log = logging.getLogger(__name__)

# Adaptive retries so throttling self-heals at the client layer.
_ADAPTIVE_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})

# Bound the describe_table fan-out on large accounts.
_MAX_DESCRIBE_TABLES = 200


def attribute_dynamodb(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    region: str,
    ce_service_total_usd: float = 0.0,
) -> list[AttributedResource]:
    ddb = session.client("dynamodb", region_name=region, config=_ADAPTIVE_RETRY_CONFIG)
    try:
        tables: list[str] = []
        for page in ddb.get_paginator("list_tables").paginate():
            tables.extend(page.get("TableNames", []))
    except ClientError:
        return []
    if not tables:
        return []

    # Cap the describe_table loop so an account with thousands of
    # tables doesn't trigger an unbounded serial N+1 fan-out.
    total_table_count = len(tables)
    if len(tables) > _MAX_DESCRIBE_TABLES:
        log.warning(
            "DynamoDB region=%s has %d tables; describing only first %d",
            region, len(tables), _MAX_DESCRIBE_TABLES,
        )
        tables = tables[:_MAX_DESCRIBE_TABLES]

    # Describe each table for metadata + size.
    descs: list[dict] = []
    for name in tables:
        try:
            d = ddb.describe_table(TableName=name).get("Table", {})
            descs.append(d)
        except ClientError:
            pass

    # Usage weights from CloudWatch consumed capacity units.
    # For long windows / many tables, skip CW fan-out for responsiveness.
    usage_weights: dict[str, float] = {}
    window_days = max((window_end - window_start).days, 1)
    should_collect_cw = window_days <= 45 and len(descs) <= 50
    if should_collect_cw:
        try:
            cw = session.client("cloudwatch", region_name=region, config=_ADAPTIVE_RETRY_CONFIG)
            for d in descs:
                name = d.get("TableName", "")
                if not name:
                    continue
                total = 0.0
                for metric_name in ("ConsumedReadCapacityUnits", "ConsumedWriteCapacityUnits"):
                    try:
                        resp = cw.get_metric_statistics(
                            Namespace="AWS/DynamoDB",
                            MetricName=metric_name,
                            Dimensions=[{"Name": "TableName", "Value": name}],
                            StartTime=window_start,
                            EndTime=window_end,
                            Period=86400,
                            Statistics=["Sum"],
                        )
                        total += sum(p.get("Sum", 0.0) for p in resp.get("Datapoints", []))
                    except ClientError:
                        continue
                usage_weights[name] = float(total)
        except ClientError:
            usage_weights = {}

    weight_sum = sum(usage_weights.values()) or 0.0
    if ce_service_total_usd > 0 and weight_sum <= 0 and should_collect_cw:
        # Accuracy-first: if we attempted activity weighting and got no signal,
        # avoid inventing per-table cost splits.
        return []

    # When tables were truncated to the describe cap, the
    # described tables must only absorb their *coverage* fraction of the CE
    # total — otherwise the dropped tables' cost (which list_tables ordered
    # lexicographically, not by spend) silently lands on the survivors. Assign
    # described tables `coverage` of the pool and emit one synthetic row for the
    # undescribed remainder so the total still reconciles to CE.
    coverage = (len(descs) / total_table_count) if total_table_count else 1.0
    rows: list[AttributedResource] = []
    for d in descs:
        name = d.get("TableName", "?")
        size_bytes = d.get("TableSizeBytes", 0)
        item_count = d.get("ItemCount", 0)
        billing_mode = d.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED")
        state = d.get("TableStatus", "ACTIVE").lower()

        if weight_sum > 0:
            share = usage_weights.get(name, 0.0) / weight_sum
        elif not should_collect_cw and ce_service_total_usd > 0:
            # Fast mode fallback: proportion by current table size.
            size_sum = sum(dd.get("TableSizeBytes", 0) for dd in descs) or 0.0
            share = (size_bytes / size_sum) if size_sum > 0 else (1.0 / len(descs))
        elif ce_service_total_usd > 0:
            share = 1.0 / len(descs)
        else:
            share = 0.0
        cost = ce_service_total_usd * share * coverage

        # Only fetch tags for tables we actually attribute cost to,
        # and only when we're already doing the CW-weighted (non-fast) path —
        # mirrors the Lambda gating to bound list_tags_of_resource fan-out.
        tags: dict = {}
        if should_collect_cw and cost > 0.001:
            try:
                tag_resp = ddb.list_tags_of_resource(ResourceArn=d.get("TableArn", "")).get("Tags", [])
                tags = tags_to_dict(tag_resp)
            except ClientError:
                pass

        rows.append(AttributedResource(
            service="DynamoDB",
            resource_id=name,
            name=tags.get("Name", name),
            resource_type=billing_mode.lower(),
            state=state,
            cost_usd=cost,
            hours=0.0,
            region=region,
            tags=tags,
            attributes={
                "size_gb": round(size_bytes / (1024 ** 3), 3),
                "item_count": item_count,
                "arn": d.get("TableArn"),
            },
        ))

    # Remainder row for the undescribed tables, so their cost is represented
    # (and not dumped onto the described ones) and the total reconciles to CE.
    if coverage < 1.0 and ce_service_total_usd > 0:
        undescribed = total_table_count - len(descs)
        rows.append(AttributedResource(
            service="DynamoDB",
            resource_id=f"ddb:undescribed:{region}",
            name=f"{undescribed} undescribed tables",
            resource_type="aggregate",
            state="active",
            cost_usd=ce_service_total_usd * (1.0 - coverage),
            hours=0.0,
            region=region,
            tags={},
            attributes={
                "aggregate": True,
                "undescribed_table_count": undescribed,
                "note": "DynamoDB tables beyond the describe cap — per-table breakdown unavailable",
            },
        ))
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows
