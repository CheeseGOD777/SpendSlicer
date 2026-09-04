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


def _report_to_csv_rows(report: dict) -> list[dict]:
    """Flatten the top-services section of a report for CSV output.

    ``top_services`` is capped (25); without the tail + TOTAL rows a
    spreadsheet SUM over the CSV silently disagreed with the PDF/JSON total
    from the same run.
    """
    rows = []
    top = report.get("top_services", [])
    for svc in top:
        rows.append({
            "account": report.get("account", ""),
            "period": report.get("period", ""),
            "service": svc.get("service", ""),
            "cost_usd": svc.get("cost_usd", 0),
        })
    total = report.get("total_cost_usd")
    if total is not None:
        top_sum = sum(float(s.get("cost_usd", 0) or 0) for s in top)
        tail = total - top_sum
        services_count = report.get("services_count", len(top))
        if services_count > len(top) and tail > 0.005:
            rows.append({
                "account": report.get("account", ""),
                "period": report.get("period", ""),
                "service": f"(other {services_count - len(top)} services)",
                "cost_usd": round(tail, 4),
            })
        rows.append({
            "account": report.get("account", ""),
            "period": report.get("period", ""),
            "service": "TOTAL",
            "cost_usd": total,
        })
    return rows
