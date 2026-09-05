"""Slack exporter — posts cost summaries and audit findings to a channel.

Requires ``slack_sdk`` (``pip install spendslicer[exporters]``).
"""

from __future__ import annotations

from .base import ExportResult


def _check_slack_sdk() -> None:
    try:
        import slack_sdk  # noqa: F401
    except ImportError:
        raise ImportError(
            "slack_sdk is required for Slack export. "
            "Install it with: pip install spendslicer[exporters]"
        ) from None


def _fmt_currency(v: float | None) -> str:
    return f"${v:,.2f}" if v is not None else "N/A"


def _build_blocks(report: dict) -> list[dict]:
    """Construct Slack Block Kit blocks from a structured report dict."""
    account = report.get("account", "unknown")
    period = report.get("period", "")
    total = report.get("total_cost_usd", 0.0)
    top = report.get("top_services", [])
    audit = report.get("audit_summary", {})
    budgets = report.get("budget_findings", [])

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f":bar_chart: AWS Cost Report — {account}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Period:*\n{period}"},
                {"type": "mrkdwn", "text": f"*Total Cost:*\n{_fmt_currency(total)}"},
            ],
        },
        {"type": "divider"},
    ]

    # Top services
    if top:
        lines = "\n".join(
            f"• {s.get('service', '')}: {_fmt_currency(s.get('cost_usd'))}"
            for s in top[:10]
        )
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Top Services:*\n{lines}"},
        })

    # Audit summary
    if audit:
        waste = audit.get("waste_usd", 0)
        status_icon = ":warning:" if waste > 0 else ":white_check_mark:"
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{status_icon} *FinOps Audit*\n"
                    f"Untagged: {audit.get('untagged', 0)}  |  "
                    f"Idle: {audit.get('idle', 0)}  |  "
                    f"Est. waste: {_fmt_currency(waste)}/mo"
                ),
            },
        })

    # Budget breaches / warnings. Cap the list: Slack rejects a section whose
    # text exceeds 3000 chars (and messages over ~50 blocks) with invalid_blocks,
    # which would drop the ENTIRE notification exactly when many budgets are
    # breached — i.e. when the alert matters most. Show the worst N and
    # summarise the rest. Breached sort ahead of warnings.
    _BUDGET_ALERT_CAP = 10
    flagged = [b for b in budgets if b.get("status") in ("breached", "warning")]
    if flagged:
        flagged.sort(key=lambda b: 0 if b.get("status") == "breached" else 1)
        shown = flagged[:_BUDGET_ALERT_CAP]
        blocks.append({"type": "divider"})
        lines = "\n".join(
            f":{'red_circle' if b.get('status') == 'breached' else 'large_yellow_circle'}: "
            f"*{b.get('budget_name')}* — {b.get('breach_reason', b.get('status'))}"
            for b in shown
        )
        if len(flagged) > len(shown):
            lines += f"\n_+{len(flagged) - len(shown)} more budgets flagged_"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Budget Alerts:*\n{lines}"},
        })

    return blocks


def export_slack(
    report: dict,
    channel: str,
    token: str,
    username: str = "spendslicer",
    icon_emoji: str = ":money_with_wings:",
) -> ExportResult:
    """Post a cost/audit report to a Slack channel.

    Parameters
    ----------
    report:
        Structured report dict (same shape as ``export_pdf``).
    channel:
        Slack channel ID or name (e.g. ``#finops-alerts``).
    token:
        Slack Bot OAuth token (``xoxb-...``).
    """
    _check_slack_sdk()
    from slack_sdk import WebClient

    try:
        client = WebClient(token=token)
        blocks = _build_blocks(report)
        resp = client.chat_postMessage(
            channel=channel,
            username=username,
            icon_emoji=icon_emoji,
            blocks=blocks,
            text=f"AWS Cost Report — {report.get('account', '')} ({report.get('period', '')})",
        )
        ts = resp.get("ts", "")
        return ExportResult(
            format="slack",
            destination=f"{channel}#{ts}",
            success=True,
        )
    except Exception as exc:
        return ExportResult(format="slack", destination=channel, success=False, error=str(exc))
