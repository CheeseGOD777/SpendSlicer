"""S3 exporter — uploads export files (CSV, JSON, PDF) to an S3 bucket."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import boto3
from botocore.exceptions import ClientError

from .base import ExportResult


def upload_file(
    local_path: Union[str, Path],
    bucket: str,
    key: str,
    session: Optional[boto3.Session] = None,
    content_type: Optional[str] = None,
    extra_args: Optional[dict] = None,
) -> ExportResult:
    """Upload a local file to S3.

    ``content_type`` is inferred from the file extension if not provided.
    ``extra_args`` is passed directly to ``upload_file`` (e.g. ServerSideEncryption).
    """
    src = Path(local_path)
    dest = f"s3://{bucket}/{key}"
    _content_types = {
        ".csv": "text/csv",
        ".json": "application/json",
        ".pdf": "application/pdf",
    }
    ct = content_type or _content_types.get(src.suffix.lower(), "application/octet-stream")

    boto_extra = dict(extra_args or {})
    boto_extra.setdefault("ContentType", ct)

    s3 = (session or boto3.Session()).client("s3")
    try:
        s3.upload_file(str(src), bucket, key, ExtraArgs=boto_extra)
        size = src.stat().st_size
        return ExportResult(format="s3", destination=dest, success=True, bytes_written=size)
    except (ClientError, FileNotFoundError) as exc:
        return ExportResult(format="s3", destination=dest, success=False, error=str(exc))


def upload_bytes(
    data: bytes,
    bucket: str,
    key: str,
    content_type: str = "application/octet-stream",
    session: Optional[boto3.Session] = None,
    extra_args: Optional[dict] = None,
) -> ExportResult:
    """Upload raw bytes to S3 without a temp file."""
    dest = f"s3://{bucket}/{key}"
    boto_extra = dict(extra_args or {})
    boto_extra.setdefault("ContentType", content_type)

    s3 = (session or boto3.Session()).client("s3")
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=data, **boto_extra)
        return ExportResult(format="s3", destination=dest, success=True, bytes_written=len(data))
    except ClientError as exc:
        return ExportResult(format="s3", destination=dest, success=False, error=str(exc))
