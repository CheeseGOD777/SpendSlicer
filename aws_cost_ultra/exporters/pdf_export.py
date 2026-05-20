"""PDF exporter using Puppeteer for professional HTML-to-PDF output."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Union

from .base import ExportResult


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

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            json.dump(report, tmp)
            tmp_input_path = Path(tmp.name)

        proc = subprocess.run(
            [node_bin, str(renderer), str(tmp_input_path), str(dest)],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
            timeout=120,
        )
        try:
            tmp_input_path.unlink(missing_ok=True)
        except Exception:
            pass

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip() or "Puppeteer PDF render failed"
            return ExportResult(format="pdf", destination=str(dest), success=False, error=err[:500])

        if not dest.exists():
            return ExportResult(format="pdf", destination=str(dest), success=False, error="PDF file was not created.")

        size = dest.stat().st_size
        return ExportResult(format="pdf", destination=str(dest), success=True, bytes_written=size)
    except Exception as exc:
        return ExportResult(format="pdf", destination=str(path), success=False, error=str(exc))
