"""Strategy: prefer the local CUR warehouse over Cost Explorer.

Route handlers depend on this abstraction. When CUR is configured and
has data for the window, queries are local DuckDB (free). When CUR
doesn't cover the window (e.g., today's intraday, or before CUR was
enabled), fall back to the cached CE matrix.
"""

from __future__ import annotations

from typing import Optional, Protocol

from costsight.aws.cost_store import CostStore, DailyServiceMatrix


class _Window(Protocol):
    def iso(self) -> tuple[str, str]: ...


class CostSource:
    def __init__(self, *, cur_store, cost_store: CostStore) -> None:
        self._cur = cur_store      # CurStore or None
        self._ce = cost_store

    def _use_cur(self, account_id: str, window: _Window) -> bool:
        return self._cur is not None and self._cur.has_data(account_id, window)

    def get_matrix(self, profile: str, account_id: str, window: _Window, spec) -> DailyServiceMatrix:
        if self._use_cur(account_id, window):
            raw = self._cur.daily_service_matrix(account_id, window)
            return DailyServiceMatrix.from_ce(raw)
        return self._ce.get_matrix(profile, account_id, window, spec)

    def attribute_resources(
        self, account_id: str, window: _Window, *, session, spec, errors=None,
        region: str = "all",
    ) -> list[dict]:
        # CUR rows carry no region column, so a region-scoped request must use
        # the describe path — serving account-wide CUR data labelled as one
        # region silently ignored the filter (and poisoned the region cache key).
        if region == "all" and self._use_cur(account_id, window):
            return self._cur.attribute_resources(account_id, window)
        return self._ce.attribute_resources_via_describe(
            account_id, window, session=session, spec=spec, errors=errors,
            region=region,
        )
