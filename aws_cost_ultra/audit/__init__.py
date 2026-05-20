"""FinOps audit engine.

Modules:
    untagged  — resources missing required cost-allocation tags
    idle      — stopped/detached/unused resources still incurring charges
    budgets   — AWS Budgets breach and near-breach detection
    runner    — parallel multi-region audit coordinator
"""

from .budgets import BudgetFinding, BudgetStatus, get_budget_findings
from .idle import IdleResource, find_idle_resources
from .runner import AuditResult, run_audit
from .untagged import UntaggedResource, scan_untagged

__all__ = [
    "AuditResult",
    "BudgetFinding",
    "BudgetStatus",
    "IdleResource",
    "UntaggedResource",
    "find_idle_resources",
    "get_budget_findings",
    "run_audit",
    "scan_untagged",
]
