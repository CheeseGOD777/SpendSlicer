"""Cost Explorer queries for per-resource (RESOURCE_ID) attribution."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Optional

from aws_cost_ultra.core.filters import CostFilterSpec, build_ce_filter, pre_credit_gross

# CE SERVICE dimension value for running EC2 instances.
_EC2_COMPUTE_SERVICE = "Amazon Elastic Compute Cloud - Compute"

# CE returns these when resource-level data is unavailable.
_SKIP_RESOURCE_IDS = frozenset({"", "NoResourceId", "NoResourceID"})


def ce_cost_by_resource_id(
    ce_client,
    window_start: datetime,
    window_end: datetime,
    service: str,
    spec: Optional[CostFilterSpec] = None,
) -> dict[str, dict[str, float]]:
    """Return ``{resource_id: {"cost": float, "hours": float}}`` from CE.

    Uses the RESOURCE_ID dimension — the same ground truth AWS bills against
    when resource-level cost allocation is active. Returns an empty dict if CE
    declines the query (permissions, opt-in, or no data).
    """
    spec = spec or pre_credit_gross()
    filt_parts: list[dict] = []
    base_filter = build_ce_filter(spec)
    if base_filter:
        filt_parts.append(base_filter)
    filt_parts.append({"Dimensions": {"Key": "SERVICE", "Values": [service]}})
    combined = {"And": filt_parts} if len(filt_parts) > 1 else filt_parts[0]

    start_s = window_start.strftime("%Y-%m-%d")
    end_s = window_end.strftime("%Y-%m-%d")

    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"cost": 0.0, "hours": 0.0})
    token: str | None = None

    try:
        while True:
            kwargs: dict = {
                "TimePeriod": {"Start": start_s, "End": end_s},
                "Granularity": "MONTHLY",
                "Metrics": ["UnblendedCost", "UsageQuantity"],
                "GroupBy": [{"Type": "DIMENSION", "Key": "RESOURCE_ID"}],
                "Filter": combined,
            }
            if token:
                kwargs["NextPageToken"] = token
            resp = ce_client.get_cost_and_usage(**kwargs)
            for period in resp.get("ResultsByTime", []):
                for g in period.get("Groups", []):
                    rid = g["Keys"][0]
                    if rid in _SKIP_RESOURCE_IDS:
                        continue
                    cost = float(g["Metrics"]["UnblendedCost"]["Amount"])
                    hrs = float(g["Metrics"]["UsageQuantity"]["Amount"])
                    if cost > 0:
                        totals[rid]["cost"] += cost
                        totals[rid]["hours"] += hrs
            token = resp.get("NextPageToken")
            if not token:
                break
    except Exception:
        return {}

    return {k: dict(v) for k, v in totals.items() if v["cost"] > 0.001}


def ce_ec2_cost_by_instance_id(
    ce_client,
    window_start: datetime,
    window_end: datetime,
    spec: Optional[CostFilterSpec] = None,
) -> dict[str, dict[str, float]]:
    """EC2 Compute costs keyed by instance id (``i-…``)."""
    raw = ce_cost_by_resource_id(
        ce_client, window_start, window_end, _EC2_COMPUTE_SERVICE, spec=spec,
    )
    return {rid: data for rid, data in raw.items() if rid.startswith("i-")}
