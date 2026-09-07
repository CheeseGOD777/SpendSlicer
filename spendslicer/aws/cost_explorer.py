"""Cost Explorer wrapper — accuracy-first.

Every function in this module returns ``CostValue`` objects carrying a
``Provenance`` record. Callers never see a bare float. That way, a number
that reaches the UI, the CLI, or a PDF always answers the question
*"where did this come from?"* — which is the only way to stop trust-losing
"your number doesn't match the console" conversations.

Design rules
------------
1. Defaults match the AWS Billing Console: metric=UnblendedCost,
   record_types=ALL (no exclusion). Anything that diverges must be
   opt-in and must appear in the number's label.
2. Granularity is UTC. We never silently convert to local time.
3. CE pagination is handled internally; callers don't deal with
   ``NextPageToken``.
4. When attribution math rescales numbers to a CE ground-truth total
   (``base.normalize``), the attribution caller records the variance
   into the ``Provenance.variance_from_ground_truth_pct`` field so the
   UI can surface drift warnings.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

import boto3
from botocore.config import Config

from spendslicer.core.filters import (
    CostFilterSpec,
    build_ce_filter,
    console_default,
)
from spendslicer.core.provenance import CostValue, Provenance
from spendslicer.core.types import CostMetric, Granularity, TimeWindow

log = logging.getLogger(__name__)

# CE is a global service but requires a region; us-east-1 is canonical.
_CE_REGION = "us-east-1"

# The resource enumerators fan out one CE query per region, so ~17 land at once
# on a fully opted-in account. CE answers that with
# "LimitExceededException: Too many open requests", the enumeration fails, the
# result never reaches the cache, and the next request re-runs the whole scan —
# billing the user twice for one page view. botocore classifies that error as
# throttling, so adaptive mode both retries it and rate-limits the client to
# stay under the ceiling. Every other AWS client here already had this; the one
# that gets hammered did not.
_ADAPTIVE_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})


def make_ce_client(session: boto3.Session):
    """The only place a raw CE boto3 client is built.

    Two call sites needed one (this module and resources.runner, which hands a
    shared client to the per-region fan-out). When they each built their own,
    adding the retry config to one left the other — the hot one — unprotected.
    """
    return session.client("ce", region_name=_CE_REGION, config=_ADAPTIVE_RETRY_CONFIG)


@dataclass
class GroupedCost:
    """A single group's cost result within a larger CE response."""

    key: tuple[str, ...]        # e.g. ("Amazon EC2 - Other",) for single-dim group
    value: CostValue

    def primary_key(self) -> str:
        return self.key[0] if self.key else ""


@dataclass
class TimeSeriesPoint:
    """One time-bucket in a trend query."""

    period_start: str           # YYYY-MM-DD
    period_end: str             # YYYY-MM-DD, exclusive
    value: CostValue


class CostExplorerClient:
    """Thin wrapper over boto3 CE with provenance tracking baked in.

    Construction is cheap; instantiate per-session. Instances are not
    thread-safe (they reuse a single boto3 client); create one per
    worker thread when fanning out.
    """

    def __init__(self, session: boto3.Session, ce_client=None) -> None:
        self._session = session
        self._client = ce_client or make_ce_client(session)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_total_cost(
        self,
        window: TimeWindow,
        metric: CostMetric = CostMetric.UNBLENDED,
        spec: CostFilterSpec | None = None,
    ) -> CostValue:
        """Single scalar total for the window — e.g. "month-to-date spend"."""
        spec = spec or console_default()
        results = self._get_cost_and_usage(
            window=window,
            metric=metric,
            spec=spec,
            granularity=Granularity.MONTHLY,
            group_by=(),
        )
        total = 0.0
        for period in results:
            # Read EITHER the requested metric's Total OR the groups — never
            # both, and never sum across every metric. CE populates Total when
            # ungrouped and Groups when grouped; summing both (or all metric
            # entries) silently double-counts if either invariant is relaxed.
            # Mirror get_trend's if/else.
            total_dict = period.get("Total") or {}
            if metric.value in total_dict:
                total += float(total_dict[metric.value].get("Amount", 0.0))
            else:
                for g in period.get("Groups", []):
                    total += float(g["Metrics"][metric.value]["Amount"])
        return CostValue(
            amount_usd=total,
            provenance=self._build_provenance(
                source="cost_explorer",
                metric=metric,
                window=window,
                spec=spec,
                group_by=(),
            ),
        )

    def daily_service_matrix(self, window, spec) -> list[dict]:
        """One canonical CE call: DAILY granularity, grouped by SERVICE.

        Returns the raw CE ``ResultsByTime`` list (already concatenated
        across pagination). Callers slice with DailyServiceMatrix.from_ce.
        """
        return self._get_cost_and_usage(
            window=window,
            metric=CostMetric.UNBLENDED,
            spec=spec,
            granularity=Granularity.DAILY,
            group_by=(("DIMENSION", "SERVICE"),),
        )

    def get_cost_by_service(
        self,
        window: TimeWindow,
        metric: CostMetric = CostMetric.UNBLENDED,
        spec: CostFilterSpec | None = None,
        granularity: Granularity = Granularity.MONTHLY,
    ) -> list[GroupedCost]:
        """Service-level breakdown. One GroupedCost per service."""
        return self._grouped_query(
            window=window,
            metric=metric,
            spec=spec or console_default(),
            granularity=granularity,
            group_by=(("DIMENSION", "SERVICE"),),
        )

    def get_cost_by_usage_type(
        self,
        window: TimeWindow,
        metric: CostMetric = CostMetric.UNBLENDED,
        spec: CostFilterSpec | None = None,
        granularity: Granularity = Granularity.MONTHLY,
    ) -> list[GroupedCost]:
        """Usage-type granularity — one level deeper than service."""
        return self._grouped_query(
            window=window,
            metric=metric,
            spec=spec or console_default(),
            granularity=granularity,
            group_by=(("DIMENSION", "USAGE_TYPE"),),
        )

    def get_cost_by_service_and_usage_type(
        self,
        window: TimeWindow,
        metric: CostMetric = CostMetric.UNBLENDED,
        spec: CostFilterSpec | None = None,
        granularity: Granularity = Granularity.MONTHLY,
    ) -> list[GroupedCost]:
        """Two-dim grouping: SERVICE × USAGE_TYPE. One CE call covers
        composition for every service in the window — used by the
        Services page to show what's actually driving each service's bill.
        """
        return self._grouped_query(
            window=window,
            metric=metric,
            spec=spec or console_default(),
            granularity=granularity,
            group_by=(("DIMENSION", "SERVICE"), ("DIMENSION", "USAGE_TYPE")),
        )

    def get_cost_by_tag(
        self,
        window: TimeWindow,
        tag_key: str,
        metric: CostMetric = CostMetric.UNBLENDED,
        spec: CostFilterSpec | None = None,
        granularity: Granularity = Granularity.MONTHLY,
    ) -> list[GroupedCost]:
        """Group by a user-defined cost-allocation tag."""
        return self._grouped_query(
            window=window,
            metric=metric,
            spec=spec or console_default(),
            granularity=granularity,
            group_by=(("TAG", tag_key),),
        )

    def get_cost_by_linked_account(
        self,
        window: TimeWindow,
        metric: CostMetric = CostMetric.UNBLENDED,
        spec: CostFilterSpec | None = None,
        granularity: Granularity = Granularity.MONTHLY,
    ) -> list[GroupedCost]:
        """For management accounts: cost per linked (member) account."""
        return self._grouped_query(
            window=window,
            metric=metric,
            spec=spec or console_default(),
            granularity=granularity,
            group_by=(("DIMENSION", "LINKED_ACCOUNT"),),
        )

    def get_trend(
        self,
        window: TimeWindow,
        granularity: Granularity = Granularity.MONTHLY,
        metric: CostMetric = CostMetric.UNBLENDED,
        spec: CostFilterSpec | None = None,
    ) -> list[TimeSeriesPoint]:
        """Time-series totals across the window (one point per bucket)."""
        spec = spec or console_default()
        results = self._get_cost_and_usage(
            window=window,
            metric=metric,
            spec=spec,
            granularity=granularity,
            group_by=(),
        )
        points: list[TimeSeriesPoint] = []
        for period in results:
            start = period["TimePeriod"]["Start"]
            end = period["TimePeriod"]["End"]
            total = 0.0
            total_dict = period.get("Total") or {}
            if metric.value in total_dict:
                total = float(total_dict[metric.value].get("Amount", 0.0))
            else:
                for g in period.get("Groups", []):
                    total += float(g["Metrics"][metric.value]["Amount"])
            # Per-bucket window for precise provenance: parse this period's
            # own TimePeriod into UTC-midnight datetimes so each point cites
            # its own bucket rather than the whole query window.
            bucket_window = TimeWindow(
                start=datetime.fromisoformat(start).replace(tzinfo=timezone.utc),
                end=datetime.fromisoformat(end).replace(tzinfo=timezone.utc),
            )
            points.append(
                TimeSeriesPoint(
                    period_start=start,
                    period_end=end,
                    value=CostValue(
                        amount_usd=total,
                        provenance=self._build_provenance(
                            source="cost_explorer",
                            metric=metric,
                            window=bucket_window,
                            spec=spec,
                            group_by=(),
                        ),
                    ),
                )
            )
        return points

    def get_forecast(
        self,
        window: TimeWindow,
        metric: CostMetric = CostMetric.UNBLENDED,
        spec: CostFilterSpec | None = None,
    ) -> CostValue | None:
        """Forward-looking projection from CE's forecast endpoint.

        Returns None if the window is too short or CE declines to forecast.
        """
        spec = spec or console_default()
        start_s, end_s = window.iso()
        # Forecast expects METRIC in SNAKE_CASE (UNBLENDED_COST), whereas
        # get_cost_and_usage takes CamelCase (UnblendedCost). Translate.
        _FORECAST_METRICS = {
            "UnblendedCost":  "UNBLENDED_COST",
            "BlendedCost":    "BLENDED_COST",
            "AmortizedCost":  "AMORTIZED_COST",
            "NetUnblendedCost": "NET_UNBLENDED_COST",
            "NetAmortizedCost": "NET_AMORTIZED_COST",
        }
        # CE only forecasts dollar metrics. Usage metrics (UsageQuantity,
        # NormalizedUsageAmount) are not supported and would silently fall
        # through to an invalid CamelCase value that CE rejects. Fail loudly
        # since calling this with a usage metric is a programming error.
        if metric.value not in _FORECAST_METRICS:
            raise ValueError(
                f"get_cost_forecast does not support metric {metric.value}; "
                "only dollar metrics are forecastable"
            )
        forecast_metric = _FORECAST_METRICS[metric.value]
        kwargs: dict = {
            "TimePeriod": {"Start": start_s, "End": end_s},
            "Metric": forecast_metric,
            "Granularity": Granularity.MONTHLY.value,
        }
        built = build_ce_filter(spec)
        if built:
            kwargs["Filter"] = built
        try:
            resp = self._client.get_cost_forecast(**kwargs)
            total = float(resp["Total"]["Amount"])
            from spendslicer.web.middleware import get_current_counter  # local import avoids cycle
            get_current_counter().add(pages=1)
        except Exception as exc:
            # CE refuses to forecast on <~7 days of history. That's the common
            # case for fresh accounts — log quietly and return None (a
            # legitimately-unavailable forecast that callers may safely cache).
            if type(exc).__name__ == "DataUnavailableException":
                log.info("cost_forecast skipped: insufficient historical data for this window")
                return None
            # Anything else (throttling, timeout, transient API error) is NOT a
            # stable "no forecast" answer — re-raise so callers can avoid
            # caching a blank forecast that a retry would have filled.
            log.warning("cost_forecast failed: %s", type(exc).__name__, exc_info=True)
            raise
        return CostValue(
            amount_usd=total,
            provenance=self._build_provenance(
                source="forecast",
                metric=metric,
                window=window,
                spec=spec,
                group_by=(),
            ),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _grouped_query(
        self,
        window: TimeWindow,
        metric: CostMetric,
        spec: CostFilterSpec,
        granularity: Granularity,
        group_by: tuple[tuple[str, str], ...],
    ) -> list[GroupedCost]:
        results = self._get_cost_and_usage(
            window=window,
            metric=metric,
            spec=spec,
            granularity=granularity,
            group_by=group_by,
        )
        # Aggregate groups across time buckets
        totals: dict[tuple[str, ...], float] = {}
        for period in results:
            for g in period.get("Groups", []):
                key = tuple(g["Keys"])
                amount = float(g["Metrics"][metric.value]["Amount"])
                totals[key] = totals.get(key, 0.0) + amount

        out: list[GroupedCost] = []
        group_by_descriptor = tuple(f"{t}:{k}" for t, k in group_by)
        for key, total in sorted(totals.items(), key=lambda kv: -kv[1]):
            out.append(
                GroupedCost(
                    key=key,
                    value=CostValue(
                        amount_usd=total,
                        provenance=self._build_provenance(
                            source="cost_explorer",
                            metric=metric,
                            window=window,
                            spec=spec,
                            group_by=group_by_descriptor,
                        ),
                    ),
                )
            )
        return out

    def _get_cost_and_usage(
        self,
        window: TimeWindow,
        metric: CostMetric,
        spec: CostFilterSpec,
        granularity: Granularity,
        group_by: tuple[tuple[str, str], ...],
    ) -> list[dict]:
        start_s, end_s = window.iso()
        kwargs: dict = {
            "TimePeriod": {"Start": start_s, "End": end_s},
            "Granularity": granularity.value,
            "Metrics": [metric.value],
        }
        if group_by:
            kwargs["GroupBy"] = [{"Type": t, "Key": k} for t, k in group_by]
        built = build_ce_filter(spec)
        if built:
            kwargs["Filter"] = built

        all_periods: list[dict] = []
        token: str | None = None
        while True:
            call_kwargs = dict(kwargs)
            if token:
                call_kwargs["NextPageToken"] = token
            resp = self._client.get_cost_and_usage(**call_kwargs)
            results = resp.get("ResultsByTime", [])
            all_periods.extend(results)
            from spendslicer.web.middleware import get_current_counter  # local import avoids cycle
            counter = get_current_counter()
            record_count = sum(len(p.get("Groups", []) or []) for p in results)
            counter.add(pages=1, records=record_count)
            token = resp.get("NextPageToken")
            if not token:
                break
        return all_periods

    def _build_provenance(
        self,
        source: str,
        metric: CostMetric,
        window: TimeWindow,
        spec: CostFilterSpec,
        group_by: tuple[str, ...],
    ) -> Provenance:
        return Provenance(
            source=source,  # type: ignore[arg-type]
            metric=metric,
            window=window,
            timezone_str="UTC",
            excluded_record_types=spec.excluded_record_types,
            included_record_types=spec.included_record_types,
            group_by=group_by,
            filter_summary=spec.summary(),
        )


# Convenience top-level factories for callers that don't want to hold a client.

def client_for(session: boto3.Session) -> CostExplorerClient:
    return CostExplorerClient(session)


def group_keys(groups: Iterable[GroupedCost]) -> list[str]:
    """Shortcut: primary keys of a grouped result in CE-returned order."""
    return [g.primary_key() for g in groups]
