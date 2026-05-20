"""Parallel audit runner — coordinates multi-region scans for one profile.

Runs untagged + idle checks concurrently across all regions in a
ProfileBundle, then appends account-level budget findings.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

import boto3

from .budgets import BudgetFinding, get_budget_findings
from .idle import IdleResource, find_idle_resources
from .untagged import UntaggedResource, scan_untagged


@dataclass
class AuditResult:
    """Aggregated findings for one profile across all scanned regions."""

    profile: str
    account_id: Optional[str]
    regions_scanned: list[str]
    untagged: list[UntaggedResource] = field(default_factory=list)
    idle: list[IdleResource] = field(default_factory=list)
    budgets: list[BudgetFinding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total_estimated_waste_usd(self) -> float:
        return sum(r.estimated_monthly_cost_usd for r in self.idle)

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "account_id": self.account_id,
            "regions_scanned": self.regions_scanned,
            "summary": {
                "untagged_count": len(self.untagged),
                "idle_count": len(self.idle),
                "budget_findings": len(self.budgets),
                "estimated_waste_usd_monthly": round(self.total_estimated_waste_usd, 2),
            },
            "untagged": [u.to_dict() for u in self.untagged],
            "idle": [i.to_dict() for i in self.idle],
            "budgets": [b.to_dict() for b in self.budgets],
            "errors": self.errors,
        }


def _scan_region(
    session: boto3.Session,
    region: str,
    required_tags: list[str],
    idle_checks: list[str] | None,
) -> tuple[list[UntaggedResource], list[IdleResource]]:
    untagged = scan_untagged(session, region, required_tags) if required_tags else []
    idle = find_idle_resources(session, region, idle_checks)
    return untagged, idle


def run_audit(
    session: boto3.Session,
    profile: str,
    account_id: Optional[str],
    regions: list[str],
    required_tags: list[str] | None = None,
    idle_checks: list[str] | None = None,
    budget_warn_at_pct: float = 80.0,
    max_workers: int = 8,
) -> AuditResult:
    """Run a full audit: untagged + idle (parallel across regions) + budgets.

    Parameters
    ----------
    required_tags:
        Tag keys every resource should have. Empty list skips the untagged check.
    idle_checks:
        Which idle sub-checks to run. None = all checks.
    budget_warn_at_pct:
        Utilization % at which a budget transitions to WARNING status.
    """
    required_tags = required_tags or []
    result = AuditResult(
        profile=profile,
        account_id=account_id,
        regions_scanned=list(regions),
    )

    # Parallel per-region scans
    with ThreadPoolExecutor(max_workers=min(max_workers, max(len(regions), 1))) as pool:
        future_to_region = {
            pool.submit(_scan_region, session, region, required_tags, idle_checks): region
            for region in regions
        }
        for fut in as_completed(future_to_region):
            region = future_to_region[fut]
            try:
                untagged, idle = fut.result()
                result.untagged.extend(untagged)
                result.idle.extend(idle)
            except Exception as exc:
                result.errors.append(f"{region}: {exc}")

    # Budget check is account-level (not per-region)
    try:
        result.budgets = get_budget_findings(session, warn_at_pct=budget_warn_at_pct)
    except Exception as exc:
        result.errors.append(f"budgets: {exc}")

    return result
