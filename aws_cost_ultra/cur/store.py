"""SQL query layer over the local DuckDB CUR warehouse."""

from __future__ import annotations

import datetime as dt
from typing import Any, Protocol

import duckdb

from aws_cost_ultra.cur.schema import LINE_ITEMS_VIEW


class _Window(Protocol):
    def iso(self) -> tuple[str, str]: ...


class CurStore:
    def __init__(self, db: duckdb.DuckDBPyConnection) -> None:
        self._db = db

    def _has_view(self) -> bool:
        row = self._db.execute(
            "SELECT count(*) FROM information_schema.views WHERE table_name = ?",
            [LINE_ITEMS_VIEW],
        ).fetchone()
        return bool(row and row[0])

    def has_data(self, account_id: str, window: _Window) -> bool:
        if not self._has_view():
            return False
        s, e = window.iso()
        row = self._db.execute(
            f"SELECT count(*) FROM {LINE_ITEMS_VIEW} "
            "WHERE account_id = ? AND usage_date >= ? AND usage_date < ?",
            [account_id, s, e],
        ).fetchone()
        return bool(row and row[0] > 0)

    def total(self, account_id: str, window: _Window) -> float:
        s, e = window.iso()
        row = self._db.execute(
            f"SELECT COALESCE(SUM(unblended_cost), 0) FROM {LINE_ITEMS_VIEW} "
            "WHERE account_id = ? AND usage_date >= ? AND usage_date < ?",
            [account_id, s, e],
        ).fetchone()
        return float(row[0]) if row else 0.0

    def by_service(self, account_id: str, window: _Window) -> list[tuple[str, float]]:
        s, e = window.iso()
        rows = self._db.execute(
            f"""
            SELECT COALESCE(service_name, service_code) AS svc,
                   SUM(unblended_cost) AS cost
            FROM {LINE_ITEMS_VIEW}
            WHERE account_id = ? AND usage_date >= ? AND usage_date < ?
            GROUP BY svc
            ORDER BY cost DESC
            """,
            [account_id, s, e],
        ).fetchall()
        return [(r[0], float(r[1])) for r in rows]

    def daily_service_matrix(self, account_id: str, window: _Window):
        """Same shape as CostExplorerClient.daily_service_matrix output."""
        s, e = window.iso()
        rows = self._db.execute(
            f"""
            SELECT usage_date, COALESCE(service_name, service_code) AS svc,
                   SUM(unblended_cost) AS cost
            FROM {LINE_ITEMS_VIEW}
            WHERE account_id = ? AND usage_date >= ? AND usage_date < ?
            GROUP BY usage_date, svc
            ORDER BY usage_date
            """,
            [account_id, s, e],
        ).fetchall()
        by_day: dict[str, list] = {}
        for d, svc, cost in rows:
            day = d.isoformat() if hasattr(d, "isoformat") else str(d)
            by_day.setdefault(day, []).append({
                "Keys": [svc],
                "Metrics": {"UnblendedCost": {"Amount": f"{float(cost)}", "Unit": "USD"}},
            })
        out = []
        sorted_days = sorted(by_day.keys())
        for day in sorted_days:
            next_day = (dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat()
            out.append({
                "TimePeriod": {"Start": day, "End": next_day},
                "Groups": by_day[day],
            })
        return out

    def attribute_resources(self, account_id: str, window: _Window) -> list[dict]:
        """Per-resource cost with name + tags. The thing CE can't give us."""
        s, e = window.iso()
        rows = self._db.execute(
            f"""
            SELECT
              resource_id,
              COALESCE(service_name, service_code) AS svc,
              ANY_VALUE(tags) AS tags,
              SUM(unblended_cost) AS cost,
              SUM(usage_amount) AS usage_amount
            FROM {LINE_ITEMS_VIEW}
            WHERE account_id = ?
              AND usage_date >= ? AND usage_date < ?
              AND resource_id IS NOT NULL AND resource_id <> ''
            GROUP BY resource_id, svc
            ORDER BY cost DESC
            """,
            [account_id, s, e],
        ).fetchall()
        out: list[dict] = []
        for resource_id, svc, tags, cost, usage in rows:
            if isinstance(tags, dict):
                tag_map = tags
            elif tags is not None:
                tag_map = dict(tags)
            else:
                tag_map = {}
            name = tag_map.get("Name") or tag_map.get("name") or resource_id
            out.append({
                "resource_id": resource_id,
                "name": name,
                "service": svc,
                "tags": tag_map,
                "cost": round(float(cost), 4),
                "usage_amount": float(usage) if usage is not None else None,
            })
        return out
