"""Audit API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from aws_cost_ultra.audit.runner import run_audit
from aws_cost_ultra.aws.session import load_profile_bundle
from aws_cost_ultra.resources.runner import ALL_REGIONS
from aws_cost_ultra.web.context import friendly_error
from aws_cost_ultra.web.deps import cache_get_swr, cache_set, get_session, schedule_refresh

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/audit")

import re as _re

# Validate region before it lands in a cache key (FINDING 20): AWS region code
# shape, or the ALL_REGIONS sentinel; anything else clamps to ALL_REGIONS.
_REGION_RE = _re.compile(r"^[a-z]{2}-[a-z]+-\d{1,2}$")


def _safe_region(region: str) -> str:
    return region if (region == ALL_REGIONS or _REGION_RE.match(region or "")) else ALL_REGIONS


def build_audit_ctx(profile: str, region: str, include_snapshots: int) -> dict:
    region = _safe_region(region)  # clamp here too, so a bad region can't poison the clamped cache key
    ctx: dict = {
        "error": None,
        "idle": [],
        "untagged": [],
        "estimated_waste": 0.0,
        "region": region,
        "region_label": "All opted-in regions" if region == ALL_REGIONS else region,
    }
    try:
        bundle = load_profile_bundle(profile)
        regions = bundle.regions if region == ALL_REGIONS else [region]
        idle_checks = None
        if not include_snapshots:
            idle_checks = [
                "stopped_ec2", "unattached_ebs", "unused_eips",
                "stopped_rds", "idle_elb",
            ]
        result = run_audit(
            bundle.session,
            profile=bundle.profile,
            account_id=bundle.account_id,
            regions=regions,
            required_tags=["Name", "Environment"],
            idle_checks=idle_checks,
        )
        ctx["idle"] = [r.to_dict() for r in result.idle]
        ctx["untagged"] = [r.to_dict() for r in result.untagged]
        ctx["estimated_waste"] = result.total_estimated_waste_usd
        if result.errors:
            # FINDING 16: per-check runner errors are raw boto3/botocore messages
            # that commonly embed ARNs, account ids, role names, and request
            # context. Don't return them verbatim — log server-side and surface
            # only a generic count to the client.
            log.warning("audit checks reported %d error(s): %s", len(result.errors), "; ".join(result.errors[:5]))
            ctx["error"] = f"{len(result.errors)} audit check(s) failed (see server logs)."
    except Exception as exc:
        ctx["error"] = friendly_error(exc)
    return ctx


@router.get("/summary/data")
def api_audit_summary_data(
    profile: str = Query("default"),
    region: str = Query(ALL_REGIONS),
    include_snapshots: int = Query(0),
):
    ckey = f"audit:{profile}:{_safe_region(region)}:{include_snapshots}"
    cached, should_refresh = cache_get_swr(ckey)
    if cached is None:
        cached = build_audit_ctx(profile, region, include_snapshots)
        if cached.get("error") is None:
            cache_set(ckey, cached)
    elif should_refresh:
        schedule_refresh(
            ckey, lambda: build_audit_ctx(profile, region, include_snapshots),
            heavy=True,
        )
    return JSONResponse(cached)
