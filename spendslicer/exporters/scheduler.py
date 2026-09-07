"""Scheduled export runner.

Provides a simple run-once entry point (``run_scheduled_export``) that
callers invoke from cron, AWS EventBridge, or any scheduler.

This module intentionally has no scheduler dependency itself — the caller
sets up the schedule. The function is idempotent: repeated calls on the
same day produce a new export with a timestamped filename, never overwriting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .base import ExportResult
from .csv_export import export_csv
from .json_export import export_json


@dataclass
class ScheduledExportConfig:
    """What and where to export on each scheduled run."""

    output_dir: str = "./exports"
    formats: list[str] = field(default_factory=lambda: ["json", "csv"])
    # Optional S3 upload after local write
    s3_bucket: str | None = None
    s3_prefix: str = "aws-cost-exports/"
    # Optional Slack notification
    slack_token: str | None = None
    slack_channel: str | None = None
    # Optional email
    ses_from: str | None = None
    ses_to: list[str] | None = None


def run_scheduled_export(
    report: dict,
    config: ScheduledExportConfig,
    session=None,
) -> list[ExportResult]:
    """Execute one scheduled export run.

    Writes local files, then optionally uploads to S3 / posts to Slack.
    Returns a list of ExportResult for every action taken.
    """
    results: list[ExportResult] = []
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written_files: list[Path] = []

    for fmt in config.formats:
        if fmt == "json":
            dest = out_dir / f"cost_report_{ts}.json"
            res = export_json(report, dest)
            results.append(res)
            if res.success:
                written_files.append(dest)

        elif fmt == "csv":
            rows = _report_to_csv_rows(report)
            dest = out_dir / f"cost_report_{ts}.csv"
            res = export_csv(rows, dest)
            results.append(res)
            if res.success:
                written_files.append(dest)

        elif fmt == "pdf":
            try:
                from .pdf_export import export_pdf
                dest = out_dir / f"cost_report_{ts}.pdf"
                res = export_pdf(report, dest)
                results.append(res)
                if res.success:
                    written_files.append(dest)
            except ImportError as exc:
                results.append(ExportResult(format="pdf", destination="", success=False, error=str(exc)))

    # Optional S3 upload
    if config.s3_bucket:
        from .s3_export import upload_file
        for fp in written_files:
            key = config.s3_prefix + fp.name
            res = upload_file(fp, config.s3_bucket, key, session=session)
            results.append(res)

    # Optional Slack notification
    if config.slack_token and config.slack_channel:
        from .slack_export import export_slack
        res = export_slack(report, config.slack_channel, config.slack_token)
        results.append(res)

    # Optional SES email
    if config.ses_from and config.ses_to:
        from .email_export import send_via_ses
        pdf_path = next((f for f in written_files if f.suffix == ".pdf"), None)
        res = send_via_ses(
            report,
            to_addresses=config.ses_to,
            from_address=config.ses_from,
            attachment_path=pdf_path,
            session=session,
        )
        results.append(res)

    return results


def _tags_to_str(tags) -> str:
    """Collapse a tag dict to ``k=v; k=v``.

    Not left as a dict: export_csv flattens nested dicts into dot-notation
    columns, so arbitrary customer tag keys would each become their own
    column and the header would grow with every distinct tag in the account.
    """
    if isinstance(tags, dict):
        return "; ".join(f"{k}={v}" for k, v in sorted(tags.items()) if v not in (None, ""))
    if isinstance(tags, (list, tuple)):
        return "; ".join(str(t) for t in tags)
    return str(tags or "")


def _report_to_csv_rows(report: dict) -> list[dict]:
    """Flatten every section of a report for CSV output.

    This used to emit ``top_services`` and a TOTAL only, silently dropping
    the resources, trend and budget sections that JSON and PDF both carry —
    so the CSV of a 91-resource account contained 21 rows and none of the
    per-resource attribution the tool exists to produce.

    One flat table with a ``section`` column rather than several files: the
    download endpoint serves a single file per format, and a spreadsheet can
    filter on one column. Rows carry different fields; export_csv unions the
    keys and leaves the rest blank.
    """
    account = report.get("account", "")
    period = report.get("period", "")

    def base(section: str) -> dict:
        return {"section": section, "account": account, "period": period}

    rows: list[dict] = []

    top = report.get("top_services") or []
    for svc in top:
        rows.append({**base("service"),
                     "service": svc.get("service", ""),
                     "cost_usd": svc.get("cost_usd", 0)})

    # top_services is capped, so without the tail + TOTAL rows a spreadsheet
    # SUM over the CSV disagrees with the PDF/JSON total from the same run.
    total = report.get("total_cost_usd")
    if total is not None:
        top_sum = sum(float(s.get("cost_usd", 0) or 0) for s in top)
        tail = total - top_sum
        services_count = report.get("services_count", len(top))
        if services_count > len(top) and tail > 0.005:
            rows.append({**base("service"),
                         "service": f"(other {services_count - len(top)} services)",
                         "cost_usd": round(tail, 4)})

    for r in report.get("top_resources") or []:
        rows.append({**base("resource"),
                     "service": r.get("service", ""),
                     "resource_id": r.get("resource_id", ""),
                     "name": r.get("name", ""),
                     "region": r.get("region", ""),
                     # Resource rows call it "cost"; keep one cost column so a
                     # single SUM works across sections.
                     "cost_usd": r.get("cost", r.get("cost_usd", 0)),
                     "usage_amount": r.get("usage_amount", ""),
                     "tags": _tags_to_str(r.get("tags"))})

    for pt in report.get("trend_points") or []:
        # The bucket label goes in `name`, not `period` — `period` already
        # holds the report-wide selection and would be overwritten.
        rows.append({**base("trend"),
                     "name": pt.get("period", ""),
                     "cost_usd": pt.get("cost_usd", 0)})

    for b in report.get("budget_findings") or []:
        rows.append({**base("budget"),
                     "name": b.get("budget_name", ""),
                     "cost_usd": b.get("actual_spend", ""),
                     "limit_usd": b.get("limit_amount", ""),
                     "forecasted_usd": b.get("forecasted_spend", ""),
                     "utilization_pct": b.get("utilization_pct", ""),
                     "status": b.get("status", ""),
                     "detail": b.get("breach_reason", "")})

    if total is not None:
        rows.append({**base("total"), "service": "TOTAL", "cost_usd": total})

    return rows
