"""Cost Explorer filter builders.

Centralizes every CE filter construction so the record-type / service /
tag / linked-account semantics are consistent across the tool, and so
provenance records can cite a single source of truth for "what was
filtered and why".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# CE hard-caps each Values array (and OR-clause fan-out) at 200 entries.
_CE_VALUES_LIMIT = 200

# Record types present in CE data.
# Source: https://docs.aws.amazon.com/cost-management/latest/userguide/ce-advanced.html#ce-filter-reference
ALL_RECORD_TYPES = (
    "Usage",      # regular consumption
    "Credit",     # promotional / activation / support credits applied
    "Refund",     # account-level refunds
    "Tax",        # applicable taxes
    "Upfront",    # upfront RI / Savings Plan payments
    "Recurring",  # recurring RI / SP fees
    "Support",    # AWS Support plan fees
)


@dataclass(frozen=True)
class CostFilterSpec:
    """User-facing description of the cost-filter applied to a CE query.

    An explicit filter spec is carried end-to-end so every number the
    tool renders can answer "what did this include?" — the core of the
    accuracy invariant.

    Fields
    ------
    service : optional service dimension filter (e.g. "Amazon EC2").
    tags : optional {Key: Value} pairs applied as CE tag filter.
    linked_accounts : optional list of 12-digit account IDs.
    excluded_record_types : record types omitted from the query.
    included_record_types : record types specifically included (overrides).
        If neither include nor exclude is provided, ALL_RECORD_TYPES are
        used — matching the AWS Billing Console default.
    usage_type_substrings : optional substring match list on USAGE_TYPE.
    """

    service: str | None = None
    tags: tuple[tuple[str, str], ...] | None = None
    linked_accounts: tuple[str, ...] | None = None
    excluded_record_types: tuple[str, ...] | None = None
    included_record_types: tuple[str, ...] | None = None
    usage_type_substrings: tuple[str, ...] | None = None
    region: str | None = None

    def effective_record_types(self) -> tuple[str, ...]:
        """What we actually kept — the positive set used in provenance."""
        if self.included_record_types is not None:
            return self.included_record_types
        excluded = set(self.excluded_record_types or ())
        return tuple(rt for rt in ALL_RECORD_TYPES if rt not in excluded)

    def summary(self) -> str:
        """Short human summary for logs and provenance filter_summary."""
        parts = []
        if self.service:
            parts.append(f"service={self.service}")
        if self.tags:
            parts.append("tags=" + ",".join(f"{k}:{v}" for k, v in self.tags))
        if self.linked_accounts:
            parts.append(f"linked_accounts={len(self.linked_accounts)}")
        excluded = set(self.excluded_record_types or ())
        if excluded:
            parts.append("exclude=" + ",".join(sorted(excluded)))
        elif self.included_record_types:
            parts.append("include=" + ",".join(self.included_record_types))
        if self.usage_type_substrings:
            parts.append(f"usage_like={len(self.usage_type_substrings)} patterns")
        if self.region:
            parts.append(f"region={self.region}")
        return "; ".join(parts) if parts else "no filters"


def build_ce_filter(spec: CostFilterSpec) -> dict | None:
    """Compose a boto3-compatible CE Filter from a CostFilterSpec.

    Returns ``None`` if no filter should be applied. An Empty return
    value matters: CE treats an absent Filter as "include everything"
    which is the Console default.
    """
    parts: list[dict] = []

    if spec.service:
        parts.append({"Dimensions": {"Key": "SERVICE", "Values": [spec.service]}})

    if spec.region:
        parts.append({"Dimensions": {"Key": "REGION", "Values": [spec.region]}})

    if spec.linked_accounts:
        accounts = list(spec.linked_accounts)
        if len(accounts) > _CE_VALUES_LIMIT:
            log.warning(
                "linked_accounts has %d values; CE caps Values at %d — truncating",
                len(accounts), _CE_VALUES_LIMIT,
            )
            accounts = accounts[:_CE_VALUES_LIMIT]
        parts.append(
            {
                "Dimensions": {
                    "Key": "LINKED_ACCOUNT",
                    "Values": accounts,
                }
            }
        )

    if spec.tags:
        tag_parts = [
            {"Tags": {"Key": k, "Values": [v]}} for k, v in spec.tags
        ]
        if len(tag_parts) == 1:
            parts.append(tag_parts[0])
        else:
            parts.append({"And": tag_parts})

    # Record-type filter: either explicit exclude or explicit include.
    if spec.excluded_record_types:
        parts.append(
            {
                "Not": {
                    "Dimensions": {
                        "Key": "RECORD_TYPE",
                        "Values": list(spec.excluded_record_types),
                    }
                }
            }
        )
    elif spec.included_record_types is not None:
        parts.append(
            {
                "Dimensions": {
                    "Key": "RECORD_TYPE",
                    "Values": list(spec.included_record_types),
                }
            }
        )

    if spec.usage_type_substrings:
        usage_substrings = list(spec.usage_type_substrings)
        if len(usage_substrings) > _CE_VALUES_LIMIT:
            log.warning(
                "usage_type_substrings has %d OR-clauses; CE caps fan-out at %d — truncating",
                len(usage_substrings), _CE_VALUES_LIMIT,
            )
            usage_substrings = usage_substrings[:_CE_VALUES_LIMIT]
        substrings = [
            {"Dimensions": {"Key": "USAGE_TYPE", "MatchOptions": ["CONTAINS"], "Values": [s]}}
            for s in usage_substrings
        ]
        parts.append({"Or": substrings} if len(substrings) > 1 else substrings[0])

    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return {"And": parts}


# --------------------------------------------------------------------------
# Convenience presets
# --------------------------------------------------------------------------

def console_default() -> CostFilterSpec:
    """Matches AWS Billing Console — all record types, no CE filter.

    CE treats an absent Filter as "include everything" (net after credits).
    """
    return CostFilterSpec()


def pre_credit_gross() -> CostFilterSpec:
    """Pre-credit gross usage — excludes Credit, Refund, and Upfront.

    Default for dashboards and resource attribution so totals reflect
    actual consumption before promotional credits and upfront RI/SP
    payments. Label in the UI cites this basis explicitly.
    """
    return CostFilterSpec(
        excluded_record_types=("Credit", "Refund", "Upfront"),
    )

