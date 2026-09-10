"""AWS Budgets breach and near-breach detector.

Reads the account's configured AWS Budgets and flags any that are:
  - already breached (actual/forecasted spend > budget amount)
  - approaching breach (configurable threshold, default 80%)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)


class BudgetStatus(str, Enum):
    OK = "ok"
    WARNING = "warning"         # approaching threshold
    BREACHED = "breached"       # actual or forecasted > limit
    UNKNOWN = "unknown"         # insufficient data from CE


@dataclass
class BudgetFinding:
    budget_name: str
    budget_type: str            # COST | USAGE | RI_UTILIZATION | etc.
    time_unit: str              # MONTHLY | QUARTERLY | ANNUALLY
    limit_amount: float
    limit_unit: str             # USD or usage unit
    actual_spend: float | None
    forecasted_spend: float | None
    status: BudgetStatus
    breach_reason: str | None = None
    account_id: str | None = None

    @property
    def utilization_pct(self) -> float | None:
        if self.limit_amount and self.actual_spend is not None:
            return round((self.actual_spend / self.limit_amount) * 100, 1)
        return None

    def to_dict(self) -> dict:
        return {
            "budget_name": self.budget_name,
            "budget_type": self.budget_type,
            "time_unit": self.time_unit,
            "limit_amount": self.limit_amount,
            "limit_unit": self.limit_unit,
            "actual_spend": self.actual_spend,
            "forecasted_spend": self.forecasted_spend,
            "status": self.status.value,
            "breach_reason": self.breach_reason,
            "account_id": self.account_id,
            "utilization_pct": self.utilization_pct,
        }


def _safe_float(s: str | None) -> float | None:
    try:
        return float(s) if s else None
    except (TypeError, ValueError):
        return None


def _budget_limit(b: dict, now_epoch: float | None = None) -> tuple[float | None, str]:
    """(limit, unit) for a budget — fixed or planned.

    ``PlannedBudgetLimits`` is keyed by period-START-time epoch-second
    strings (per the AWS Budgets API), never by literal "MONTHLY" — the old
    lookup silently dropped every planned/auto-adjusting budget, breached
    ones included. Pick the plan period covering ``now`` (largest start
    <= now), or the earliest period when now precedes the plan.
    """
    fixed = b.get("BudgetLimit") or {}
    amount = _safe_float(fixed.get("Amount"))
    if amount is not None:
        return amount, fixed.get("Unit") or "USD"

    planned = b.get("PlannedBudgetLimits") or {}
    entries = []
    for key, entry in planned.items():
        try:
            entries.append((float(key), entry))
        except (TypeError, ValueError):
            continue
    if not entries:
        return None, "USD"
    entries.sort(key=lambda kv: kv[0])
    if now_epoch is None:
        from datetime import datetime, timezone
        now_epoch = datetime.now(timezone.utc).timestamp()
    current = entries[0][1]
    for start, entry in entries:
        if start <= now_epoch:
            current = entry
        else:
            break
    return _safe_float(current.get("Amount")), current.get("Unit") or "USD"


def get_budget_findings(
    session: boto3.Session,
    warn_at_pct: float = 80.0,
) -> list[BudgetFinding]:
    """Return all budget findings for the account (all budgets, all statuses).

    AWS Budgets is a global service accessed via us-east-1.
    ``warn_at_pct`` controls when a budget transitions from OK → WARNING
    (default 80% of limit).
    """
    try:
        sts = session.client("sts")
        account_id = sts.get_caller_identity().get("Account")
    except Exception as exc:
        log.warning("budget fetch: STS get_caller_identity failed: %s", type(exc).__name__)
        log.debug("budget fetch traceback", exc_info=True)
        account_id = None

    if not account_id:
        return []

    findings: list[BudgetFinding] = []
    try:
        budgets_client = session.client("budgets", region_name="us-east-1")
        paginator = budgets_client.get_paginator("describe_budgets")
        for page in paginator.paginate(AccountId=account_id):
            for b in page.get("Budgets", []):
                limit, limit_unit = _budget_limit(b)
                if limit is None:
                    continue

                calc_spent = b.get("CalculatedSpend", {})
                actual = _safe_float(
                    calc_spent.get("ActualSpend", {}).get("Amount")
                )
                forecasted = _safe_float(
                    calc_spent.get("ForecastedSpend", {}).get("Amount")
                )

                # Determine status
                status = BudgetStatus.OK
                breach_reason: str | None = None

                if actual is not None and actual > limit:
                    status = BudgetStatus.BREACHED
                    breach_reason = (
                        f"Actual spend ${actual:.2f} exceeds budget limit ${limit:.2f}"
                    )
                elif forecasted is not None and forecasted > limit:
                    status = BudgetStatus.BREACHED
                    breach_reason = (
                        f"Forecasted spend ${forecasted:.2f} exceeds budget limit ${limit:.2f}"
                    )
                elif actual is not None and limit > 0 and (actual / limit * 100) >= warn_at_pct:
                    status = BudgetStatus.WARNING
                    breach_reason = (
                        f"Actual spend ${actual:.2f} is {actual/limit*100:.1f}% of "
                        f"budget limit ${limit:.2f}"
                    )
                elif actual is None and forecasted is None:
                    status = BudgetStatus.UNKNOWN

                findings.append(BudgetFinding(
                    budget_name=b.get("BudgetName", ""),
                    budget_type=b.get("BudgetType", "COST"),
                    time_unit=b.get("TimeUnit", "MONTHLY"),
                    limit_amount=limit,
                    limit_unit=limit_unit,
                    actual_spend=actual,
                    forecasted_spend=forecasted,
                    status=status,
                    breach_reason=breach_reason,
                    account_id=account_id,
                ))
    except ClientError:
        pass

    # Sort: BREACHED first, then WARNING, then OK
    order = {BudgetStatus.BREACHED: 0, BudgetStatus.WARNING: 1, BudgetStatus.OK: 2, BudgetStatus.UNKNOWN: 3}
    findings.sort(key=lambda f: order[f.status])
    return findings
