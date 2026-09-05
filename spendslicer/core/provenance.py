"""Provenance — the accuracy invariant.

Every cost number returned to the UI or exported to a report carries a
`Provenance` record describing exactly where it came from: metric, record
types included/excluded, time window, timezone, source (CE query vs.
pricing-API attribution). The UI surfaces this on hover; the CLI
prints it in verbose mode; PDFs print it in the footer.

Why: the #1 trust-breaker for a FinOps tool is numbers that don't match
the AWS Billing Console. Provenance makes every mismatch reproducible
and every toggle (metric, record type, etc.) visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from spendslicer.core.types import CostMetric, TimeWindow

# Record types present in AWS billing data.
# Mirror of CE's RECORD_TYPE dimension values we care about.
RecordType = Literal["Usage", "Credit", "Refund", "Tax", "Upfront", "Recurring", "Support"]


@dataclass(frozen=True)
class Provenance:
    """Describes how a cost figure was computed.

    Attach one to every `CostValue` returned from the engine.
    """

    source: Literal["cost_explorer", "pricing_api_attribution", "forecast"]
    metric: CostMetric
    window: TimeWindow
    timezone_str: str = "UTC"
    included_record_types: tuple[RecordType, ...] | None = None
    excluded_record_types: tuple[RecordType, ...] | None = None
    group_by: tuple[str, ...] = field(default_factory=tuple)
    filter_summary: str = ""
    ce_ground_truth_total: float | None = None  # For attribution variance checks
    variance_from_ground_truth_pct: float | None = None
    computed_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def label(self) -> str:
        """Short human-readable label for UI tooltips."""
        start_s, end_s = self.window.iso()
        base = f"{self.metric.value} · {start_s} → {end_s} · {self.timezone_str}"
        if self.excluded_record_types:
            base += f" · excludes {','.join(self.excluded_record_types)}"
        if self.variance_from_ground_truth_pct is not None:
            base += f" · Δ{self.variance_from_ground_truth_pct:+.2f}% vs CE"
        return base


@dataclass
class CostValue:
    """A cost amount with the provenance of how it was computed."""

    amount_usd: float
    provenance: Provenance

    def to_dict(self) -> dict:
        return {
            "amount_usd": round(self.amount_usd, 4),
            "provenance": {
                "source": self.provenance.source,
                "metric": self.provenance.metric.value,
                "window": list(self.provenance.window.iso()),
                "tz": self.provenance.timezone_str,
                "included_record_types": list(self.provenance.included_record_types or ()),
                "excluded_record_types": list(self.provenance.excluded_record_types or ()),
                "group_by": list(self.provenance.group_by),
                "filter": self.provenance.filter_summary,
                "ce_ground_truth": self.provenance.ce_ground_truth_total,
                "variance_pct": self.provenance.variance_from_ground_truth_pct,
                "computed_at": self.provenance.computed_at.isoformat(),
                "label": self.provenance.label(),
            },
        }


VARIANCE_WARN_THRESHOLD_PCT = 1.0


def variance_warning(provenance: Provenance) -> str | None:
    """Return a warning message if attribution drift exceeds threshold, else None.

    Surfaces accuracy issues in the UI before the user hits a mystery
    mismatch against the Billing console.
    """
    v = provenance.variance_from_ground_truth_pct
    if v is None:
        return None
    if abs(v) > VARIANCE_WARN_THRESHOLD_PCT:
        return (
            f"Attribution total differs from Cost Explorer by {v:+.2f}%. "
            f"Displayed numbers have been normalized to CE; see provenance for details."
        )
    return None
