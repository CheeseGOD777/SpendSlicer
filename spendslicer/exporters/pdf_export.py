"""PDF exporter — pure Python, via fpdf2.

This used to shell out to Node and render the report in headless Chromium
through Puppeteer. That produced a prettier document and three problems: it
needed a Node toolchain plus an 87 MB Chromium download, so PDF silently did
not work in the desktop builds or a plain ``pip install`` at all; it took
~2.3 s per report against ~16 ms for CSV; and the Puppeteer tree was the
source of every high-severity npm advisory in the project.

fpdf2 is pure Python with no native dependencies, so it bundles into the
frozen builds and works everywhere the rest of the tool does. Same report
dict in, same ExportResult out.

The trade is that the layout is built here rather than in HTML/CSS, so this
is a typeset document rather than a pixel copy of the web dashboard.
"""

from __future__ import annotations

import logging
import unicodedata
from pathlib import Path

from .base import ExportResult

log = logging.getLogger(__name__)

# Points. A4 is 210mm wide; 15mm margins leave 180mm of content.
_CONTENT_W = 180.0

_INK = (17, 24, 39)
_MUTED = (107, 114, 128)
_RULE = (209, 213, 219)
_HOT = (180, 83, 9)  # over-budget / attention


def _usd(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "-"


def _latin1(text) -> str:
    """Coerce text into what fpdf2's built-in fonts can render.

    The core PDF fonts are latin-1 only, and fpdf2 raises rather than
    substituting. Resource names and tag values are user data: the first real
    report this hit died on an em-dash in an instance Name.

    Decompose accents to their base letters first, so "café" degrades to
    "cafe" rather than "caf?". Characters with no latin-1 form at all — CJK,
    Cyrillic, emoji — become "?"; CSV and JSON export the same rows as UTF-8
    if you need them intact.
    """
    s = str(text if text is not None else "")
    for a, b in (("—", "-"), ("–", "-"), ("‘", "'"), ("’", "'"),
                 ("“", '"'), ("”", '"'), ("…", "..."), (" ", " ")):
        s = s.replace(a, b)
    try:
        s.encode("latin-1")
        return s
    except UnicodeEncodeError:
        stripped = unicodedata.normalize("NFKD", s).encode("latin-1", "ignore").decode("latin-1")
        # NFKD drops CJK etc. entirely; keep a placeholder over an empty cell.
        return stripped if stripped.strip() else "?"


def _clip(pdf, text, width: float) -> str:
    """Sanitize, then truncate to ``width`` — fpdf2's cell() does not ellipsize.

    Resource IDs and Name tags are routinely longer than the column; without
    this they overflow into the next cell.
    """
    s = _latin1(text)
    if pdf.get_string_width(s) <= width:
        return s
    while s and pdf.get_string_width(s + "...") > width:
        s = s[:-1]
    return s + "..."


def _table(pdf, title: str, cols: list[tuple[str, str, float, bool]], rows: list[dict]) -> None:
    """One section: heading, header row, body. ``cols`` is (key, label, width, numeric)."""
    if not rows:
        return
    pdf.set_text_color(*_INK)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _latin1(title), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(*_MUTED)
    pdf.set_draw_color(*_RULE)
    for _key, label, w, numeric in cols:
        pdf.cell(w, 5, _latin1(label), border="B", align="R" if numeric else "L")
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*_INK)
    for row in rows:
        # Keep a row intact across the page break rather than splitting it.
        if pdf.will_page_break(5):
            pdf.add_page()
            pdf.set_font("Helvetica", "", 8)
        for key, _label, w, numeric in cols:
            raw = row.get(key)
            text = _usd(raw) if numeric else _clip(pdf, raw, w - 2)
            pdf.cell(w, 5, text, align="R" if numeric else "L")
        pdf.ln()
    pdf.ln(5)


def export_pdf(report: dict, path: str | Path) -> ExportResult:
    """Render ``report`` to a PDF at ``path``."""
    dest = Path(path).resolve()
    try:
        from fpdf import FPDF
    except ImportError:
        return ExportResult(
            format="pdf",
            destination=str(dest),
            success=False,
            error='PDF export needs fpdf2. Install it with: pip install "spendslicer[exporters]"',
        )

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)

        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.set_auto_page_break(True, margin=15)
        pdf.set_margins(15, 15, 15)
        pdf.set_title(_latin1(report.get("title") or "Cost Report"))
        pdf.add_page()

        # Masthead
        pdf.set_text_color(*_INK)
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(0, 9, _latin1(report.get("platform_name") or "SpendSlicer"),
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_MUTED)
        meta = " · ".join(
            str(x) for x in (
                report.get("account"),
                report.get("period"),
                str(report.get("generated_at") or "")[:19].replace("T", " ") + " UTC",
            ) if x
        )
        pdf.cell(0, 5, _latin1(meta), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        # Headline total
        pdf.set_text_color(*_INK)
        pdf.set_font("Helvetica", "B", 26)
        pdf.cell(0, 13, _usd(report.get("total_cost_usd")), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(*_MUTED)
        # The cost basis is not decoration: it is what makes the figure
        # reconcilable against the Billing console.
        pdf.cell(0, 4, _latin1(report.get("cost_basis")), new_x="LMARGIN", new_y="NEXT")
        counts = f"{report.get('services_count', 0)} services · {report.get('resources_count', 0)} resources"
        pdf.cell(0, 4, counts, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        _table(pdf, "Services", [
            ("service", "SERVICE", _CONTENT_W - 35, False),
            ("cost_usd", "COST", 35, True),
        ], report.get("top_services") or [])

        _table(pdf, "Resources", [
            ("name", "NAME", 55, False),
            ("resource_id", "RESOURCE ID", 50, False),
            ("service", "SERVICE", 25, False),
            ("cost", "COST", _CONTENT_W - 130, True),
        ], report.get("top_resources") or [])

        _table(pdf, "Trend", [
            ("period", "PERIOD", _CONTENT_W - 35, False),
            ("cost_usd", "COST", 35, True),
        ], report.get("trend_points") or [])

        budgets = report.get("budget_findings") or []
        if budgets:
            pdf.set_text_color(*_INK)
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 7, "Budgets", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 8)
            for b in budgets:
                if pdf.will_page_break(5):
                    pdf.add_page()
                    pdf.set_font("Helvetica", "", 8)
                breached = str(b.get("status", "")).lower() not in ("ok", "under", "")
                pdf.set_text_color(*(_HOT if breached else _INK))
                util = b.get("utilization_pct")
                util_s = f"{float(util):.0f}%" if isinstance(util, (int, float)) else "-"
                pdf.cell(70, 5, _clip(pdf, b.get("budget_name"), 68))
                pdf.cell(30, 5, _usd(b.get("actual_spend")), align="R")
                pdf.cell(30, 5, _usd(b.get("limit_amount")), align="R")
                pdf.cell(20, 5, util_s, align="R")
                pdf.cell(0, 5, "  " + _latin1(b.get("status")))
                pdf.ln()
            pdf.ln(4)

        pdf.set_text_color(*_MUTED)
        pdf.set_font("Helvetica", "", 6.5)
        pdf.multi_cell(
            0, 3.5,
            "Service totals come from AWS Cost Explorer. Per-resource figures are "
            "estimates split from usage-type buckets unless the CUR warehouse is "
            "enabled. Generated locally by SpendSlicer; no cost data left this machine. "
            "Names outside Latin-1 appear as '?' here; use the CSV or JSON export for those.",
        )

        pdf.output(str(dest))
        return ExportResult(
            format="pdf",
            destination=str(dest),
            success=True,
            bytes_written=dest.stat().st_size,
        )
    except Exception as exc:
        log.warning("pdf_export failed: %s", type(exc).__name__, exc_info=True)
        return ExportResult(format="pdf", destination=str(dest), success=False, error=str(exc))
