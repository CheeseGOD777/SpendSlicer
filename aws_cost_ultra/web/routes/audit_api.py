"""Audit API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from aws_cost_ultra.audit.runner import run_audit
from aws_cost_ultra.aws.session import load_profile_bundle
from aws_cost_ultra.resources.runner import ALL_REGIONS
from aws_cost_ultra.web.context import friendly_error
from aws_cost_ultra.web.deps import cache_get, cache_get_swr, cache_set, get_session, schedule_refresh
from aws_cost_ultra.web.render import render

router = APIRouter(prefix="/api/audit")


def build_audit_ctx(profile: str, region: str, include_snapshots: int) -> dict:
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
            ctx["error"] = "; ".join(result.errors[:3])
    except Exception as exc:
        ctx["error"] = friendly_error(exc)
    return ctx


@router.get("/summary", response_class=HTMLResponse)
def api_audit_summary(
    request: Request,
    profile: str = Query("default"),
    region: str = Query(ALL_REGIONS),
    include_snapshots: int = Query(0),
):
    ckey = f"audit:{profile}:{region}:{include_snapshots}"
    cached, should_refresh = cache_get_swr(ckey)
    if cached is None:
        cached = build_audit_ctx(profile, region, include_snapshots)
        cache_set(ckey, cached)
    elif should_refresh:
        schedule_refresh(
            ckey, lambda: build_audit_ctx(profile, region, include_snapshots),
        )
    return render(request, "partials/audit_findings.html", cached)


@router.get("/summary/data")
def api_audit_summary_data(
    profile: str = Query("default"),
    region: str = Query(ALL_REGIONS),
    include_snapshots: int = Query(0),
):
    ckey = f"audit:{profile}:{region}:{include_snapshots}"
    cached, should_refresh = cache_get_swr(ckey)
    if cached is None:
        cached = build_audit_ctx(profile, region, include_snapshots)
        cache_set(ckey, cached)
    elif should_refresh:
        schedule_refresh(
            ckey, lambda: build_audit_ctx(profile, region, include_snapshots),
        )
    return JSONResponse(cached)
