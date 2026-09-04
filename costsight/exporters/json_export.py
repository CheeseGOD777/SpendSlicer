"""JSON exporter — serialises any dict/list payload to a file or string."""

from __future__ import annotations

import json
from pathlib import Path

from .base import ExportResult


def export_json(
    data: dict | list,
    path: str | Path,
    indent: int = 2,
) -> ExportResult:
    """Write ``data`` as pretty-printed JSON to ``path``.

    Creates parent directories as needed.
    """
    dest = Path(path)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(data, indent=indent, default=str)
        dest.write_text(content, encoding="utf-8")
        return ExportResult(
            format="json",
            destination=str(dest),
            success=True,
            bytes_written=len(content.encode("utf-8")),
        )
    except Exception as exc:
        return ExportResult(format="json", destination=str(path), success=False, error=str(exc))


def to_json_string(data: dict | list, indent: int = 2) -> str:
    """Serialise to a JSON string (for API responses, Slack payloads, etc.)."""
    return json.dumps(data, indent=indent, default=str)
