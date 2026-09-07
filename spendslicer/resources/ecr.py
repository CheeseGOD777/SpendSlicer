"""ECR attribution — CE service total split by measured repository size.

ECR bills storage per GB-month, so repository size is the right weight and
it is measurable: describe_images reports imageSizeInBytes for every image.
That makes the split proportional to what is actually being billed rather
than an equal division.

Sizes are summed from the image list rather than priced directly, because a
repository's billable size depends on layer sharing that the API does not
expose. Weighting a known-correct Cost Explorer total by relative size is
accurate where multiplying a rate by a summed size would not be.
"""

from __future__ import annotations

from datetime import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .base import AttributedResource

_ADAPTIVE_RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 6})

_BYTES_PER_GB = 1024 ** 3
# Listing images costs one paginated call per repository. Past this many
# repositories the fan-out is not worth it — fall back to an equal split.
_MAX_REPOS_FOR_SIZING = 60


def _repo_size_bytes(ecr, repo_name: str) -> float:
    total = 0.0
    try:
        for page in ecr.get_paginator("describe_images").paginate(repositoryName=repo_name):
            for img in page.get("imageDetails", []):
                total += float(img.get("imageSizeInBytes", 0) or 0)
    except ClientError:
        return 0.0
    return total


def attribute_ecr(
    session: boto3.Session,
    window_start: datetime,
    window_end: datetime,
    region: str,
    ce_service_total_usd: float = 0.0,
) -> list[AttributedResource]:
    ecr = session.client("ecr", region_name=region, config=_ADAPTIVE_RETRY_CONFIG)
    try:
        repos: list[dict] = []
        for page in ecr.get_paginator("describe_repositories").paginate():
            repos.extend(page.get("repositories", []))
    except ClientError:
        return []
    if not repos:
        return []

    sizes: dict[str, float] = {}
    if len(repos) <= _MAX_REPOS_FOR_SIZING:
        for repo in repos:
            sizes[repo["repositoryName"]] = _repo_size_bytes(ecr, repo["repositoryName"])

    total_size = sum(sizes.values())
    rows: list[AttributedResource] = []
    for repo in repos:
        name = repo["repositoryName"]
        size_b = sizes.get(name, 0.0)
        if total_size > 0:
            share = size_b / total_size
            basis = "CE service total split by repository size"
        else:
            share = 1.0 / len(repos)
            basis = "CE service total split equally (sizes unavailable)"
        rows.append(AttributedResource(
            service="ECR",
            resource_id=repo.get("repositoryArn", name),
            name=name,
            resource_type="repository",
            state="available",
            cost_usd=ce_service_total_usd * share,
            hours=0.0,
            region=region,
            tags={},
            attributes={
                "size_gb": round(size_b / _BYTES_PER_GB, 3),
                "tag_mutability": repo.get("imageTagMutability", ""),
                "scan_on_push": (repo.get("imageScanningConfiguration") or {}).get(
                    "scanOnPush", False
                ),
                "share_of_service_pct": round(share * 100, 2),
                "cost_basis": basis,
            },
        ))
    rows.sort(key=lambda r: r.cost_usd, reverse=True)
    return rows
