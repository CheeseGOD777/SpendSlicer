"""Phase 5 — exporters: CSV, JSON, scheduler (no heavy deps required)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from spendslicer.exporters.base import ExportResult
from spendslicer.exporters.csv_export import export_csv, to_csv_string
from spendslicer.exporters.json_export import export_json, to_json_string
from spendslicer.exporters.scheduler import (
    ScheduledExportConfig,
    _report_to_csv_rows,
    run_scheduled_export,
)

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_REPORT = {
    "title": "Test Report",
    "account": "test-account",
    "period": "2026-03",
    "generated_at": "2026-03-31T00:00:00Z",
    "total_cost_usd": 250.75,
    "top_services": [
        {"service": "Amazon EC2", "cost_usd": 150.00},
        {"service": "Amazon S3", "cost_usd": 25.50},
        {"service": "Amazon RDS", "cost_usd": 75.25},
    ],
    "audit_summary": {"untagged": 5, "idle": 3, "waste_usd": 48.60},
    "budget_findings": [],
}

_ROWS = [
    {"service": "EC2", "cost": 100.0, "region": "us-east-1"},
    {"service": "S3", "cost": 20.0, "region": "eu-west-1"},
]


# ---------------------------------------------------------------------------
# JSON exporter
# ---------------------------------------------------------------------------

def test_export_json_writes_valid_json():
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "report.json"
        result = export_json(_REPORT, dest)
        assert result.success
        assert result.format == "json"
        loaded = json.loads(dest.read_text())
        assert loaded["account"] == "test-account"
        assert loaded["total_cost_usd"] == pytest.approx(250.75)


def test_export_json_creates_parent_directories():
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "deep" / "nested" / "out.json"
        result = export_json({"x": 1}, dest)
        assert result.success
        assert dest.exists()


def test_to_json_string_serialises_cleanly():
    s = to_json_string({"a": 1})
    assert json.loads(s) == {"a": 1}


def test_export_json_reports_bytes_written():
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "x.json"
        result = export_json({"k": "v"}, dest)
        assert result.bytes_written is not None
        assert result.bytes_written > 0


# ---------------------------------------------------------------------------
# CSV exporter
# ---------------------------------------------------------------------------

def test_export_csv_writes_valid_csv():
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "out.csv"
        result = export_csv(_ROWS, dest)
        assert result.success
        lines = dest.read_text().splitlines()
        assert "service" in lines[0]
        assert "EC2" in lines[1] or "EC2" in lines[2]


def test_export_csv_empty_rows_creates_empty_file():
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "empty.csv"
        result = export_csv([], dest)
        assert result.success
        assert result.bytes_written == 0


def test_to_csv_string_has_header_and_data_rows():
    s = to_csv_string(_ROWS)
    lines = s.strip().splitlines()
    assert len(lines) == 3  # header + 2 data rows
    assert "service" in lines[0]


def test_csv_flatten_expands_nested_dict():
    nested = [{"service": "EC2", "meta": {"region": "us-east-1", "az": "a"}}]
    s = to_csv_string(nested, flatten=True)
    assert "meta.region" in s
    assert "meta.az" in s


def test_csv_no_flatten_keeps_nested_as_is():
    nested = [{"service": "EC2", "meta": {"region": "us-east-1"}}]
    s = to_csv_string(nested, flatten=False)
    assert "meta" in s
    # Dict repr present, not expanded
    assert "meta.region" not in s


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

def test_run_scheduled_export_json_creates_file():
    with tempfile.TemporaryDirectory() as td:
        config = ScheduledExportConfig(output_dir=td, formats=["json"])
        results = run_scheduled_export(_REPORT, config)
        assert len(results) == 1
        assert results[0].success
        assert results[0].format == "json"
        files = list(Path(td).glob("*.json"))
        assert len(files) == 1


def test_run_scheduled_export_csv_creates_file():
    with tempfile.TemporaryDirectory() as td:
        config = ScheduledExportConfig(output_dir=td, formats=["csv"])
        results = run_scheduled_export(_REPORT, config)
        assert results[0].success
        files = list(Path(td).glob("*.csv"))
        assert len(files) == 1


def test_run_scheduled_export_both_formats():
    with tempfile.TemporaryDirectory() as td:
        config = ScheduledExportConfig(output_dir=td, formats=["json", "csv"])
        results = run_scheduled_export(_REPORT, config)
        assert all(r.success for r in results)
        assert len(results) == 2


def test_report_to_csv_rows_flattens_services():
    rows = _report_to_csv_rows(_REPORT)
    # services + a TOTAL row so a spreadsheet SUM reconciles with the
    # report's total even though top_services is capped.
    assert rows[0]["service"] == "Amazon EC2"
    assert rows[0]["cost_usd"] == pytest.approx(150.0)
    assert rows[0]["account"] == "test-account"
    assert rows[-1]["service"] == "TOTAL"
    assert rows[-1]["cost_usd"] == pytest.approx(_REPORT["total_cost_usd"])


def test_export_result_to_dict_has_required_keys():
    r = ExportResult(format="json", destination="/tmp/x.json", success=True, bytes_written=100)
    d = r.to_dict()
    assert "format" in d
    assert "success" in d
    assert "exported_at" in d


# ---------------------------------------------------------------------------
# CSV must carry every section the report has
# ---------------------------------------------------------------------------

_FULL_REPORT = {
    "account": "acct", "period": "last_month", "total_cost_usd": 100.0,
    "services_count": 2, "resources_count": 2,
    "top_services": [
        {"service": "Amazon EC2", "cost_usd": 60.0},
        {"service": "Amazon S3", "cost_usd": 40.0},
    ],
    "top_resources": [
        {"resource_id": "i-1", "name": "web-1", "service": "EC2", "region": "us-east-1",
         "cost": 35.0, "usage_amount": 720.0, "tags": {"Name": "web-1", "Env": "prod"}},
        {"resource_id": "vol-1", "name": "data", "service": "EBS", "region": "us-east-1",
         "cost": 25.0, "usage_amount": 100.0, "tags": {}},
    ],
    "trend_points": [{"period": "2026-08", "cost_usd": 100.0}],
    "budget_findings": [{"budget_name": "monthly", "actual_spend": 100.0,
                         "limit_amount": 80.0, "forecasted_spend": 120.0,
                         "utilization_pct": 125.0, "status": "breached",
                         "breach_reason": "over"}],
}


def test_csv_includes_every_report_section():
    """CSV shipped only top_services + TOTAL, dropping resources/trend/budgets.

    JSON and PDF carried all four, so a 91-resource account exported a
    21-row CSV with none of the per-resource attribution.
    """
    from spendslicer.exporters.scheduler import _report_to_csv_rows

    rows = _report_to_csv_rows(_FULL_REPORT)
    got = {}
    for r in rows:
        got[r["section"]] = got.get(r["section"], 0) + 1

    assert got.get("service") == 2, got
    assert got.get("resource") == 2, got
    assert got.get("trend") == 1, got
    assert got.get("budget") == 1, got
    assert got.get("total") == 1, got


def test_csv_resource_rows_keep_their_identity():
    from spendslicer.exporters.scheduler import _report_to_csv_rows

    res = [r for r in _report_to_csv_rows(_FULL_REPORT) if r["section"] == "resource"]
    ids = {r["resource_id"] for r in res}
    assert ids == {"i-1", "vol-1"}
    first = next(r for r in res if r["resource_id"] == "i-1")
    assert first["name"] == "web-1"
    assert first["cost_usd"] == 35.0          # sourced from "cost", not "cost_usd"
    assert first["tags"] == "Env=prod; Name=web-1"   # flattened, not a dict


def test_csv_tags_do_not_explode_the_header():
    """Tag dicts must be stringified: export_csv expands nested dicts into
    dot-notation columns, so raw tags would add a column per customer tag key."""
    from spendslicer.exporters.csv_export import to_csv_string
    from spendslicer.exporters.scheduler import _report_to_csv_rows

    report = dict(_FULL_REPORT)
    report["top_resources"] = [
        {"resource_id": f"i-{i}", "name": f"n{i}", "service": "EC2", "cost": 1.0,
         "tags": {f"tag{i}": "v"}}
        for i in range(20)
    ]
    header = to_csv_string(_report_to_csv_rows(report)).splitlines()[0]
    assert "tags" in header
    assert "tags.tag0" not in header
    assert len(header.split(",")) < 20, header


def test_csv_trend_bucket_does_not_overwrite_report_period():
    from spendslicer.exporters.scheduler import _report_to_csv_rows

    trend = next(r for r in _report_to_csv_rows(_FULL_REPORT) if r["section"] == "trend")
    assert trend["period"] == "last_month"   # the report-wide selection
    assert trend["name"] == "2026-08"        # the bucket label
