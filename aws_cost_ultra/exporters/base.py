"""Shared types for the exporter layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class ExportResult:
    """Outcome of a single export operation."""

    format: str                     # "csv" | "json" | "pdf" | "slack" | "s3" | "email"
    destination: str                # path, URL, channel name, email address, etc.
    success: bool
    error: Optional[str] = None
    bytes_written: Optional[int] = None
    exported_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))

    def to_dict(self) -> dict:
        return {
            "format": self.format,
            "destination": self.destination,
            "success": self.success,
            "error": self.error,
            "bytes_written": self.bytes_written,
            "exported_at": self.exported_at.isoformat(),
        }
