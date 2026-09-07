"""ElastiCache attribution — node hours x on-demand rate.

Same shape as RDS: a cluster's cost is (nodes x hours x node rate). Unlike
RDS there is no stopped state to special-case — an ElastiCache cluster that
exists is billing.
"""

from __future__ import annotations

from datetime import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from spendslicer.core import pricing

from .base import AttributedResource, clamp_window, hours_between, tags_to_dict

_ADAPTIVE_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})

# Statuses where the nodes are not running and therefore not billing.
_NON_BILLING_STATES = {"deleting", "deleted", "create-failed"}


def _row_for_cluster(
    cluster: dict,
    region: str,
    window_start: datetime,
    window_end: datetime,
    node_rate: float,
) -> AttributedResource:
    """Price one cache cluster. Pure math — testable without boto3."""
    cluster_id = cluster.get("CacheClusterId", "")
    node_type = cluster.get("CacheNodeType", "")
    nodes = int(cluster.get("NumCacheNodes", 1) or 1)
    status = cluster.get("CacheClusterStatus", "unknown")
    created = cluster.get("CacheClusterCreateTime")

    eff_s, eff_e = clamp_window(created, window_start, window_end)
    window_hrs = hours_between(eff_s, eff_e)
    billable_hrs = 0.0 if status in _NON_BILLING_STATES else window_hrs

    return AttributedResource(
        service="ElastiCache",
        resource_id=cluster_id,
        name=cluster_id,
        resource_type=node_type,
        state=status,
        cost_usd=billable_hrs * node_rate * nodes,
        hours=billable_hrs,
        region=region,
        tags=tags_to_dict(cluster.get("Tags")),
        attributes={
            "engine": cluster.get("Engine", ""),
            "engine_version": cluster.get("EngineVersion", ""),
            "nodes": nodes,
            "node_rate_usd_hr": node_rate,
            "az": cluster.get("PreferredAvailabilityZone", ""),
            "cost_basis": f"{nodes} node(s) x hours x on-demand rate",
        },
    )


def attribute_elasticache(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    region: str,
) -> list[AttributedResource]:
    ec = session.client("elasticache", region_name=region, config=_ADAPTIVE_RETRY_CONFIG)
    rows: list[AttributedResource] = []
    try:
        # Guard the iteration, not just the paginator: paginate() is lazy, so
        # an AccessDenied surfaces on the first `for`, not at construction.
        for page in ec.get_paginator("describe_cache_clusters").paginate():
            for cluster in page.get("CacheClusters", []):
                rate = pricing.elasticache_node_rate(
                    session, cluster.get("CacheNodeType", ""), region
                )
                rows.append(
                    _row_for_cluster(cluster, region, window_start, window_end, rate)
                )
    except ClientError:
        return rows
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows
