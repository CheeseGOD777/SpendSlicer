"""PDF exporter using Puppeteer for professional HTML-to-PDF output."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Union

from .base import ExportResult

log = logging.getLogger(__name__)


def _paths() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[2]
    frontend_dir = root / "frontend"
    renderer = frontend_dir / "scripts" / "render-report-pdf.mjs"
    return frontend_dir, renderer


def export_pdf(
    report: dict,
    path: Union[str, Path],
) -> ExportResult:
    """Generate branded PDF by rendering report HTML with Puppeteer."""
    dest = Path(path).resolve()
    frontend_dir, renderer = _paths()
    node_bin = shutil.which("node")

    if not node_bin:
        return ExportResult(
            format="pdf",
            destination=str(dest),
            success=False,
            error="node runtime not found. Install Node.js to use Puppeteer PDF export.",
        )
    if not renderer.exists():
        return ExportResult(
            format="pdf",
            destination=str(dest),
            success=False,
            error=f"Puppeteer renderer script not found at {renderer}",
        )

    tmp_input_path = None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            json.dump(report, tmp)
            tmp_input_path = Path(tmp.name)

        try:
            proc = subprocess.run(
                [node_bin, str(renderer), str(tmp_input_path), str(dest)],
                cwd=str(frontend_dir),
                capture_output=True,
                text=True,
                timeout=120,
            )
        finally:
            # Always remove the temp file holding the full report JSON — on
            # TimeoutExpired/OSError the old code skipped this, leaking the
            # account's cost data into the shared temp dir on every failed render.
            try:
                tmp_input_path.unlink(missing_ok=True)
            except Exception as exc:
                log.warning("pdf_export: failed to remove temp input file %s: %s", tmp_input_path, type(exc).__name__, exc_info=True)

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip() or "Puppeteer PDF render failed"
            return ExportResult(format="pdf", destination=str(dest), success=False, error=err[:500])

        if not dest.exists():
            return ExportResult(format="pdf", destination=str(dest), success=False, error="PDF file was not created.")

        size = dest.stat().st_size
        return ExportResult(format="pdf", destination=str(dest), success=True, bytes_written=size)
    except Exception as exc:
        return ExportResult(format="pdf", destination=str(path), success=False, error=str(exc))
