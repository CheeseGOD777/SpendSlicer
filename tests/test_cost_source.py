# tests/test_cost_source.py
import datetime as dt
from dataclasses import dataclass
from unittest.mock import MagicMock

from costsight.aws.cost_source import CostSource


@dataclass
class W:
    start: dt.date
    end: dt.date
    def iso(self): return (self.start.isoformat(), self.end.isoformat())


def test_uses_cur_when_data_present():
    cur = MagicMock(); cur.has_data.return_value = True
    cur.daily_service_matrix.return_value = []
    cs = MagicMock()  # CostStore
    src = CostSource(cur_store=cur, cost_store=cs)
    src.get_matrix("p1", "acct1", W(dt.date(2026,5,1), dt.date(2026,5,2)), spec="x")
    cur.daily_service_matrix.assert_called_once()
    cs.get_matrix.assert_not_called()


def test_falls_back_to_ce_when_cur_empty():
    cur = MagicMock(); cur.has_data.return_value = False
    cs = MagicMock()
    src = CostSource(cur_store=cur, cost_store=cs)
    src.get_matrix("p1", "acct1", W(dt.date(2026,5,1), dt.date(2026,5,2)), spec="x")
    cs.get_matrix.assert_called_once()


def test_no_cur_configured_falls_back_to_ce():
    cs = MagicMock()
    src = CostSource(cur_store=None, cost_store=cs)
    src.get_matrix("p1", "acct1", W(dt.date(2026,5,1), dt.date(2026,5,2)), spec="x")
    cs.get_matrix.assert_called_once()


def test_attribute_resources_prefers_cur():
    cur = MagicMock(); cur.has_data.return_value = True
    cur.attribute_resources.return_value = [{"name": "web-1"}]
    cs = MagicMock()
    src = CostSource(cur_store=cur, cost_store=cs)
    out = src.attribute_resources("acct1", W(dt.date(2026,5,1), dt.date(2026,5,2)), session=None, spec="x")
    assert out == [{"name": "web-1"}]


def test_attribute_resources_falls_back_to_describe_path_when_no_cur():
    cs = MagicMock()
    cs.attribute_resources_via_describe.return_value = [{"name": "fallback"}]
    src = CostSource(cur_store=None, cost_store=cs)
    out = src.attribute_resources("acct1", W(dt.date(2026,5,1), dt.date(2026,5,2)), session="sess", spec="x")
    assert out == [{"name": "fallback"}]
