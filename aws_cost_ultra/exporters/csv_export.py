"""CSV exporter — flat-table serialisation for cost/audit data."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Union

from .base import ExportResult


def _flatten(row: dict, prefix: str = "") -> dict:
    """Recursively flatten a nested dict into dot-separated keys."""
    out: dict = {}
    for k, v in row.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        elif isinstance(v, list):
            out[key] = ", ".join(str(i) for i in v)
        else:
            out[key] = v
    return out


def export_csv(
    rows: list[dict],
    path: Union[str, Path],
    flatten: bool = True,
) -> ExportResult:
    """Write ``rows`` to a CSV file.

    If ``flatten=True`` (default), nested dicts are expanded to dot-notation
    columns so the output is always a clean flat table.
    """
    dest = Path(path)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        processed = [_flatten(r) if flatten else r for r in rows]
        if not processed:
            dest.write_text("", encoding="utf-8")
            return ExportResult(format="csv", destination=str(dest), success=True, bytes_written=0)

        fieldnames = list(dict.fromkeys(k for row in processed for k in row))
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(processed)
        content = buf.getvalue()
        dest.write_text(content, encoding="utf-8")
        return ExportResult(
            format="csv",
            destination=str(dest),
            success=True,
            bytes_written=len(content.encode("utf-8")),
        )
    except Exception as exc:
        return ExportResult(format="csv", destination=str(path), success=False, error=str(exc))


def to_csv_string(rows: list[dict], flatten: bool = True) -> str:
    """Serialise rows to a CSV string (for in-memory use / testing)."""
    processed = [_flatten(r) if flatten else r for r in rows]
    if not processed:
        return ""
    fieldnames = list(dict.fromkeys(k for row in processed for k in row))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(processed)
    return buf.getvalue()
