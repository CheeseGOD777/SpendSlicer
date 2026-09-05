"""Presentation-layer grouping for Cost Explorer service rows.

CE splits EC2 into two SERVICE dimension values; the AWS Billing console
shows one line. Merge here so UI totals match the bill.
"""

from __future__ import annotations

from spendslicer.aws.cost_explorer import GroupedCost
from spendslicer.core.provenance import CostValue

EC2_DISPLAY_NAME = "Amazon Elastic Compute Cloud"
EC2_MERGE_SOURCES = frozenset({
    "Amazon Elastic Compute Cloud - Compute",
    "EC2 - Other",
})


def merge_ec2_service_groups(groups: list[GroupedCost]) -> list[GroupedCost]:
    """Collapse CE's split EC2 rows into a single Elastic Compute Cloud line."""
    out: list[GroupedCost] = []
    merged_amount = 0.0
    merged_value: CostValue | None = None
    merged_pos: int | None = None

    for g in groups:
        name = g.primary_key()
        if name in EC2_MERGE_SOURCES:
            merged_amount += g.value.amount_usd
            if merged_value is None:
                merged_value = g.value
                merged_pos = len(out)
            continue
        out.append(g)

    if merged_value is None:
        return out

    merged = GroupedCost(
        key=(EC2_DISPLAY_NAME,),
        value=CostValue(amount_usd=merged_amount, provenance=merged_value.provenance),
    )
    out.insert(merged_pos, merged)
    out.sort(key=lambda x: -x.value.amount_usd)
    return out


def service_rows_from_groups(
    groups: list[GroupedCost],
    prev_map: dict[str, float],
    *,
    limit: int | None = None,
) -> tuple[list[dict], float]:
    """Build sorted service dicts for templates/API responses."""
    total = sum(g.value.amount_usd for g in groups)
    rows = []
    for g in groups:
        name = g.primary_key()
        cost = g.value.amount_usd
        prev = prev_map.get(name, 0.0)
        change_pct = None
        if prev >= 0.50:
            raw = (cost - prev) / prev * 100
            change_pct = max(-999.9, min(9999.9, raw))
        rows.append({
            "name": name,
            "cost": cost,
            "prev": prev,
            "change_pct": change_pct,
            "pct_of_total": cost / total * 100 if total > 0 else 0,
            "provenance_label": g.value.provenance.label(),
        })
    if limit is not None and limit > 0:
        rows = rows[:limit]
    return rows, total
