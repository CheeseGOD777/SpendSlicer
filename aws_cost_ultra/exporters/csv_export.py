"""CSV exporter — flat-table serialisation for cost/audit data."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Union

from .base import ExportResult

# Leading characters a spreadsheet treats as the start of a formula. Cell
# values are sourced from resource names, tag keys/values, budget names, etc.
# — all settable by AWS principals with far weaker privilege than the finance
# user who opens the export — so a value like `=HYPERLINK(...)` or
# `=cmd|'/C calc'!A0` would execute on open. Per OWASP, neutralise by prefixing
# a single quote. CR/LF/tab are included because Excel also acts on them.
_CSV_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def _sanitize_cell(value):
    """Defuse CSV/formula injection for string cells; pass others through."""
    if isinstance(value, str) and value and value[0] in _CSV_INJECTION_PREFIXES:
        return "'" + value
    return value


def _flatten(row: dict, prefix: str = "") -> dict:
    """Recursively flatten a nested dict into dot-separated keys."""
    out: dict = {}
    for k, v in row.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        elif isinstance(v, list):
            out[key] = _sanitize_cell(", ".join(str(i) for i in v))
        else:
            out[key] = _sanitize_cell(v)
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
        processed = [_prepare_row(r, flatten) for r in rows]
        if not processed:
            dest.write_text("", encoding="utf-8")
            return ExportResult(format="csv", destination=str(dest), success=True, bytes_written=0)

        fieldnames = list(dict.fromkeys(k for row in processed for k in row))
        # Stream rows straight to the file via DictWriter rather than building
        # the whole table in a StringIO and then re-encoding it — that held
        # ~3–4 copies of the dataset in memory at once (input, processed,
        # buffer, getvalue string, encoded bytes). Bytes are read back from the
        # file size instead of re-encoding.
        with dest.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(processed)
        return ExportResult(
            format="csv",
            destination=str(dest),
            success=True,
            bytes_written=dest.stat().st_size,
        )
    except Exception as exc:
        return ExportResult(format="csv", destination=str(path), success=False, error=str(exc))


def _prepare_row(row: dict, flatten: bool) -> dict:
    """Flatten (which also sanitizes) or, when not flattening, sanitize cells."""
    if flatten:
        return _flatten(row)
    return {k: _sanitize_cell(v) for k, v in row.items()}


def to_csv_string(rows: list[dict], flatten: bool = True) -> str:
    """Serialise rows to a CSV string (for in-memory use / testing)."""
    processed = [_prepare_row(r, flatten) for r in rows]
    if not processed:
        return ""
    fieldnames = list(dict.fromkeys(k for row in processed for k in row))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(processed)
    return buf.getvalue()
