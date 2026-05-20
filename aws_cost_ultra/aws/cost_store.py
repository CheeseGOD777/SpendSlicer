"""Single canonical (DAILY × SERVICE) CE call per (profile, account, window).

All higher-level views (total, by-service, trend) are derived in-memory
from the resulting matrix. Replaces the previous pattern of one CE
call per view, which sent 7+ calls to render one page.
"""

from __future__ import annotations

import datetime as dt
import logging
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
        labels = list(self.days)
        values = [
            sum(v for (d, _s), v in self.cells.items() if d == day)
            for day in labels
        ]
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

    @staticmethod
    def _key(profile: str, account_id: str, window: _Window, spec_summary: str) -> str:
        s, e = window.iso()
        return f"matrix:{profile}:{account_id}:{s}:{e}:{spec_summary}"

    @staticmethod
    def _is_closed_window(window: _Window) -> bool:
        """True when the window's end date is in the past (no more updates expected)."""
        _s, e = window.iso()
        end = dt.date.fromisoformat(e)
        return end <= dt.date.today()

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
        if not force:
            cached = self._cache_get(key)
            if cached is not None:
                return DailyServiceMatrix(
                    cells={tuple(k.split("\x1f")): v for k, v in cached["cells"].items()},
                    days=list(cached["days"]),
                )

        raw = self._ce.daily_service_matrix(window, spec=spec)
        m = DailyServiceMatrix.from_ce(raw)

        # Closed windows cache effectively forever; open (today) cache 15 min.
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
