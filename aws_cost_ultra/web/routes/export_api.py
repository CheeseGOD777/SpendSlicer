"""Export and cache API routes."""

from __future__ import annotations

import datetime as _dt
import re
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from aws_cost_ultra.core.types import Granularity
from aws_cost_ultra.core.service_groups import merge_ec2_service_groups
from aws_cost_ultra.exporters import ScheduledExportConfig, run_scheduled_export
from aws_cost_ultra.web.context import friendly_error
from aws_cost_ultra.web.deps import cache_bust, get_ce_client, get_cost_source, get_session, period_to_window

router = APIRouter(prefix="/api")

_FMT_EXT = {"pdf": "pdf", "csv": "csv", "json": "json"}
_FMT_MEDIA = {
    "pdf": "application/pdf",
    "csv": "text/csv; charset=utf-8",
    "json": "application/json",
}


def _safe_filename(name: str | None, ext: str) -> str:
    if not name:
        return f"cloud_ledger_{_dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.{ext}"
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("._-")
    if not stem:
        stem = f"cloud_ledger_{_dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    if stem.lower().endswith(f".{ext}"):
        return stem
    return f"{stem}.{ext}"


def _build_report(profile: str, period: str) -> tuple[dict, object]:
    from concurrent.futures import ThreadPoolExecutor

    from aws_cost_ultra.core.filters import pre_credit_gross
    from aws_cost_ultra.core.provenance import Provenance
    from aws_cost_ultra.core.types import CostMetric
    from aws_cost_ultra.audit.budgets import get_budget_findings

    session = get_session(profile)
    ce = get_ce_client(session)
    window = period_to_window(period)
    spec = pre_credit_gross()

    account_id = session.client("sts").get_caller_identity()["Account"]
    src = get_cost_source(session)

    with ThreadPoolExecutor(max_workers=3) as pool:
        f_matrix = pool.submit(src.get_matrix, profile, account_id, window, spec)
        f_trend = pool.submit(ce.get_trend, window, Granularity.MONTHLY, spec=spec)
        f_resources = pool.submit(src.attribute_resources, account_id, window, session=session, spec=spec)

    m = f_matrix.result()
    trend_points = f_trend.result()
    raw_resources = f_resources.result()
    budget_findings = [b.to_dict() for b in get_budget_findings(session)]

    prov = Provenance(
        source="cost_explorer",
        metric=CostMetric.UNBLENDED,
        window=window,
        timezone_str="UTC",
        excluded_record_types=tuple(spec.excluded_record_types) if spec.excluded_record_types else None,
        included_record_types=tuple(spec.included_record_types) if spec.included_record_types else None,
        group_by=("SERVICE",),
        filter_summary=spec.summary(),
    )
    services = merge_ec2_service_groups(m.to_grouped_cost_list(prov))

    report = {
        "title": "Cloud Ledger Cost Report",
        "platform_name": "Cloud Ledger",
        "account": profile,
        "period": period,
        "generated_at": _dt.datetime.utcnow().isoformat() + "Z",
        "cost_basis": "Pre-credit gross (excludes Credit/Refund/Upfront)",
        "total_cost_usd": m.total(),
        "top_services": [
            {"service": g.primary_key(), "cost_usd": g.value.amount_usd}
            for g in services[:25]
        ],
        "top_resources": sorted(raw_resources, key=lambda r: r.get("cost", 0.0), reverse=True)[:50],
        "trend_points": [
            {"period": p.period_start[:7], "cost_usd": round(p.value.amount_usd, 3)}
            for p in trend_points
        ],
        "budget_findings": budget_findings,
    }
    return report, session


@router.post("/export/run")
def api_export_run(
    profile: str = Query("default"),
    period: str = Query("mtd"),
    fmt: str = Query("json"),
    output_dir: str = Query("./exports"),
):
    try:
        report, session = _build_report(profile, period)
        config = ScheduledExportConfig(output_dir=output_dir, formats=[fmt])
        results = run_scheduled_export(report, config, session=session)
        r = results[0] if results else None
        return JSONResponse({
            "success": r.success if r else False,
            "destination": r.destination if r else "",
            "error": r.error if r else "No output",
        })
    except Exception as exc:
        return JSONResponse({"success": False, "error": friendly_error(exc)})


@router.get("/export/download")
def api_export_download(
    profile: str = Query("default"),
    period: str = Query("mtd"),
    fmt: str = Query("pdf"),
    name: str = Query(""),
):
    fmt = (fmt or "pdf").lower()
    if fmt not in _FMT_EXT:
        return JSONResponse({"success": False, "error": f"Unsupported format: {fmt}"}, status_code=400)
    try:
        report, session = _build_report(profile, period)
        output_dir = Path(tempfile.gettempdir()) / "cloud-ledger-downloads"
        output_dir.mkdir(parents=True, exist_ok=True)
        config = ScheduledExportConfig(output_dir=str(output_dir), formats=[fmt])
        results = run_scheduled_export(report, config, session=session)
        r = results[0] if results else None
        if not r or not r.success or not r.destination:
            err = r.error if r else "No output"
            return JSONResponse({"success": False, "error": err}, status_code=500)

        src = Path(r.destination)
        if not src.exists():
            return JSONResponse({"success": False, "error": "Export file missing."}, status_code=500)

        filename = _safe_filename(name, _FMT_EXT[fmt])
        return FileResponse(
            path=src,
            media_type=_FMT_MEDIA[fmt],
            filename=filename,
        )
    except Exception as exc:
        return JSONResponse({"success": False, "error": friendly_error(exc)}, status_code=500)


@router.get("/budgets", response_class=HTMLResponse)
def api_budgets(request: Request, profile: str = Query("default")):
    from aws_cost_ultra.web.deps import cache_get, cache_set
    from aws_cost_ultra.web.render import render

    ckey = f"budgets:{profile}"
    cached = cache_get(ckey)
    if cached:
        return render(request, "partials/budget_alerts.html", cached)

    ctx: dict = {"error": None, "findings": []}
    try:
        session = get_session(profile)
        from aws_cost_ultra.audit.budgets import get_budget_findings
        findings = get_budget_findings(session)
        ctx["findings"] = [f.to_dict() for f in findings]
    except Exception as exc:
        ctx["error"] = friendly_error(exc)

    cache_set(ckey, ctx)
    return render(request, "partials/budget_alerts.html", ctx)


@router.get("/budgets/data")
def api_budgets_data(profile: str = Query("default")):
    from aws_cost_ultra.web.deps import cache_get, cache_set

    ckey = f"budgets:{profile}"
    cached = cache_get(ckey)
    if cached:
        return JSONResponse(cached)

    ctx: dict = {"error": None, "findings": []}
    try:
        session = get_session(profile)
        from aws_cost_ultra.audit.budgets import get_budget_findings
        findings = get_budget_findings(session)
        ctx["findings"] = [f.to_dict() for f in findings]
    except Exception as exc:
        ctx["error"] = friendly_error(exc)

    cache_set(ckey, ctx)
    return JSONResponse(ctx)


@router.post("/cache/clear")
async def api_cache_clear():
    return JSONResponse({"cleared": cache_bust()})
