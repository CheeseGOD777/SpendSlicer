"""Single canonical (DAILY × SERVICE) CE call per (profile, account, window).

All higher-level views (total, by-service, trend) are derived in-memory
from the resulting matrix. Replaces the previous pattern of one CE
call per view, which sent 7+ calls to render one page.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

log = logging.getLogger("aws_cost_ultra.cost_store")


class _Window(Protocol):
    def iso(self) -> tuple[str, str]: ...


@dataclass
class DailyServiceMatrix:
    """Sparse daily × service cost matrix.

    Keys: (date_str, service_name) → unblended_usd.
    """
    cells: dict[tuple[str, str], float] = field(default_factory=dict)
    days: list[str] = field(default_factory=list)

    @classmethod
    def from_ce(cls, results_by_time: list[dict]) -> "DailyServiceMatrix":
        m = cls()
        seen_days: set[str] = set()
        for period in results_by_time:
            day = period["TimePeriod"]["Start"]
            seen_days.add(day)
            for grp in period.get("Groups", []) or []:
                svc = grp["Keys"][0] if grp.get("Keys") else "Unknown"
                amt = float(grp["Metrics"]["UnblendedCost"]["Amount"])
                m.cells[(day, svc)] = m.cells.get((day, svc), 0.0) + amt
        m.days = sorted(seen_days)
        return m

    def total(self) -> float:
        return sum(self.cells.values())

    def by_service(self) -> list[tuple[str, float]]:
        agg: dict[str, float] = {}
        for (_d, svc), v in self.cells.items():
            agg[svc] = agg.get(svc, 0.0) + v
        return sorted(agg.items(), key=lambda kv: -kv[1])

    def trend(self) -> tuple[list[str], list[float]]:
        # Single pass over cells (O(D*S)) rather than re-scanning every cell
        # once per day (O(D^2 * S)) — the latter cost seconds of CPU on a
        # cache HIT for a 12-month / high-cardinality matrix.
        per_day: dict[str, float] = {}
        for (d, _s), v in self.cells.items():
            per_day[d] = per_day.get(d, 0.0) + v
        labels = list(self.days)
        values = [per_day.get(day, 0.0) for day in labels]
        return labels, values

    def to_grouped_cost_list(self, provenance: Any) -> list:
        """Convert matrix's service totals into GroupedCost list for existing helpers."""
        from aws_cost_ultra.aws.cost_explorer import GroupedCost  # local to dodge any cycle
        from aws_cost_ultra.core.provenance import CostValue
        return [
            GroupedCost(
                key=(svc,),
                value=CostValue(amount_usd=cost, provenance=provenance),
            )
            for svc, cost in self.by_service()
        ]


def _spec_summary(spec: Any) -> str:
    summarizer = getattr(spec, "summary", None)
    if callable(summarizer):
        return str(summarizer())
    return str(spec)


class CostStore:
    """Fetches and caches the canonical daily×service matrix per window."""

    def __init__(
        self,
        ce_client: Any,
        cache_get: Callable[[str], Optional[Any]],
        cache_set: Callable[..., None],
    ) -> None:
        self._ce = ce_client
        self._cache_get = cache_get
        self._cache_set = cache_set
        # Per-key single-flight (FINDINGS 2 & 21): serialize concurrent COLD
        # fetches for the same key so N simultaneous missers trigger ONE
        # paginated CE call instead of N (each is billed per page).
        self._inflight_lock = threading.Lock()
        self._inflight: dict[str, threading.Lock] = {}

    @staticmethod
    def _from_cached(cached: dict) -> "DailyServiceMatrix":
        return DailyServiceMatrix(
            cells={tuple(k.split("\x1f")): v for k, v in cached["cells"].items()},
            days=list(cached["days"]),
        )

    @staticmethod
    def _key(profile: str, account_id: str, window: _Window, spec_summary: str) -> str:
        s, e = window.iso()
        return f"matrix:{profile}:{account_id}:{s}:{e}:{spec_summary}"

    @staticmethod
    def _is_closed_window(window: _Window) -> bool:
        """True when the window's end is safely finalized (no more updates expected).

        Uses UTC (CE is UTC-native). AWS keeps restating recent data well
        beyond a few days: monthly invoices finalize ~the 3rd–7th of the next
        month, and tax / support / RI-SP reallocations and usage true-ups can
        adjust prior-month numbers a week or more after month end. A 3-day
        margin therefore froze pre-finalization numbers and served them for 30
        days. Treat a window as closed only once its end is at least 10 days
        past AND in a month earlier than the current one — i.e. the prior
        month's invoice has had time to settle.
        """
        _s, e = window.iso()
        end = dt.date.fromisoformat(e)
        today = dt.datetime.now(dt.timezone.utc).date()
        first_of_this_month = today.replace(day=1)
        return end <= today - dt.timedelta(days=10) and end <= first_of_this_month

    def get_matrix(
        self,
        profile: str,
        account_id: str,
        window: _Window,
        spec: Any,
        force: bool = False,
    ) -> DailyServiceMatrix:
        spec_summary = _spec_summary(spec)
        key = self._key(profile, account_id, window, spec_summary)

        # Fast path: serve a warm cache hit without taking any per-key lock.
        if not force:
            cached = self._cache_get(key)
            if cached is not None:
                return self._from_cached(cached)

        # Cold path: single-flight per key. Concurrent missers queue on the same
        # per-key lock; the first fetches and populates the cache, the rest then
        # re-check and return the cached result instead of re-paying the CE call.
        with self._inflight_lock:
            key_lock = self._inflight.setdefault(key, threading.Lock())

        with key_lock:
            if not force:
                cached = self._cache_get(key)
                if cached is not None:
                    return self._from_cached(cached)

            try:
                raw = self._ce.daily_service_matrix(window, spec=spec)
                m = DailyServiceMatrix.from_ce(raw)

                # Closed windows cache effectively forever; open (today) 15 min.
                if self._is_closed_window(window):
                    ttl, swr = 30 * 24 * 3600.0, 0.0      # 30 days, no SWR
                else:
                    ttl, swr = 900.0, 6 * 3600.0          # 15 min fresh, 6h stale

                self._cache_set(
                    key,
                    {
                        "cells": {f"{d}\x1f{s}": v for (d, s), v in m.cells.items()},
                        "days": list(m.days),
                    },
                    ttl_seconds=ttl,
                    swr_seconds=swr,
                )
                return m
            finally:
                # Drop the per-key lock so the dict can't grow unbounded. A late
                # arrival just creates a fresh lock and hits the now-warm cache.
                with self._inflight_lock:
                    self._inflight.pop(key, None)

    def attribute_resources_via_describe(
        self, account_id, window, *, session, spec, errors=None, region="all",
    ) -> list[dict]:
        """Fallback when CUR is not available: describe + USAGE_TYPE attribution.

        ``errors`` (optional list): populated with per-service failure dicts when
        a region/work unit fails after retries (FINDING 24).
        """
        from aws_cost_ultra.resources.runner import enumerate_all
        resources = enumerate_all(
            session=session, window=window, spec=spec, errors=errors, region=region,
        )
        return [
            {
                "resource_id": r.resource_id,
                "name": r.name or r.resource_id,
                "service": r.service,
                "tags": r.tags or {},
                "cost": round(r.cost_usd, 4),
                "usage_amount": None,
            }
            for r in resources
        ]
