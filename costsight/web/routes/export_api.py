"""Export and cache API routes."""

from __future__ import annotations

import datetime as _dt
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask

from costsight.core.types import Granularity
from costsight.core.service_groups import merge_ec2_service_groups
from costsight.exporters import ScheduledExportConfig, run_scheduled_export
from costsight.web.context import friendly_error
from costsight.web.deps import (
    cache_bust,
    cache_get,
    cache_set,
    get_ce_client,
    get_cost_source,
    get_session,
    is_valid_period,
    period_to_window,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# App-owned export directory (mode 0700), not a world-shared /tmp subdir that
# any local user could pre-create and then read/replace (FINDING 22).
_EXPORT_DIR = Path(
    os.environ.get("COSTSIGHT_EXPORT_DIR", str(Path.home() / ".cache" / "costsight" / "exports"))
)
# Prune exported files older than this many seconds on each run (FINDING 48).
_EXPORT_MAX_AGE_S = 24 * 3600
# Short TTL cache for the built report, so repeated/concurrent exports of the
# same (profile, period) don't each re-run STS + CE + full resource enumeration
# (FINDING 23).
_REPORT_TTL_S = 300


def _app_export_dir() -> Path:
    _EXPORT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(_EXPORT_DIR, 0o700)
    except OSError:
        pass
    return _EXPORT_DIR


def _prune_old_exports(directory: Path) -> None:
    cutoff = time.time() - _EXPORT_MAX_AGE_S
    try:
        for f in directory.iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
            except OSError:
                pass
    except OSError:
        pass


def _cached_report(profile: str, period: str) -> tuple[dict, object]:
    """Return ``(report, session)``, reusing a recently-built report.

    The report (the expensive STS + CE + resource-enumeration product) is
    cached for a short TTL keyed by profile+period; the session is always
    fetched fresh (cheap, no API spend) since it isn't serialisable.
    """
    period = period if is_valid_period(period) else "mtd"
    key = f"export_report:{profile}:{period}"
    cached = cache_get(key)
    if cached is not None:
        return cached, get_session(profile)
    report, session = _build_report(profile, period)
    cache_set(key, report, ttl_seconds=_REPORT_TTL_S, swr_seconds=0.0)
    return report, session

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
    import contextvars
    from concurrent.futures import ThreadPoolExecutor

    from costsight.core.filters import pre_credit_gross
    from costsight.core.provenance import Provenance
    from costsight.core.types import CostMetric
    from costsight.audit.budgets import get_budget_findings

    session = get_session(profile)
    ce = get_ce_client(session)
    window = period_to_window(period)
    spec = pre_credit_gross()

    account_id = session.client("sts").get_caller_identity()["Account"]
    src = get_cost_source(session)

    with ThreadPoolExecutor(max_workers=3) as pool:
        # Copy the current context into each worker so the CE call counter
        # ContextVar (set by CECountingMiddleware) propagates into pool threads.
        ctx_matrix = contextvars.copy_context()
        ctx_trend = contextvars.copy_context()
        ctx_resources = contextvars.copy_context()
        f_matrix = pool.submit(ctx_matrix.run, src.get_matrix, profile, account_id, window, spec)
        f_trend = pool.submit(ctx_trend.run, lambda: ce.get_trend(window, Granularity.MONTHLY, spec=spec))
        f_resources = pool.submit(
            ctx_resources.run,
            lambda: src.attribute_resources(account_id, window, session=session, spec=spec),
        )

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
    service_dicts = [
        {"service": g.primary_key(), "cost_usd": g.value.amount_usd}
        for g in services
    ]
    trend = [
        {"period": p.period_start[:7], "cost_usd": round(p.value.amount_usd, 3)}
        for p in trend_points
    ]
    report = _assemble_report(
        profile=profile, period=period, total=m.total(),
        services=service_dicts, raw_resources=raw_resources,
        trend_points=trend, budget_findings=budget_findings,
    )
    return report, session


def _assemble_report(
    profile: str,
    period: str,
    total: float,
    services: list[dict],
    raw_resources: list[dict],
    trend_points: list[dict],
    budget_findings: list[dict],
) -> dict:
    """Shape the report payload. Tables are capped for readability, but the
    KPI counts carry the REAL totals — a tile reading "Top Resources 50" that
    was just the list cap told the reader nothing."""
    return {
        "title": "Cloud Ledger Cost Report",
        "platform_name": "Cloud Ledger",
        "account": profile,
        "period": period,
        "generated_at": _dt.datetime.utcnow().isoformat() + "Z",
        "cost_basis": "Pre-credit gross (excludes Credit/Refund/Upfront)",
        "total_cost_usd": total,
        "services_count": len(services),
        "resources_count": len(raw_resources),
        "top_services": services[:25],
        "top_resources": sorted(
            raw_resources, key=lambda r: r.get("cost", 0.0), reverse=True,
        )[:50],
        "trend_points": trend_points,
        "budget_findings": budget_findings,
    }


@router.post("/export/run")
def api_export_run(
    profile: str = Query("default"),
    period: str = Query("mtd"),
    fmt: str = Query("json"),
):
    try:
        report, session = _cached_report(profile, period)
        # App-owned dir (mode 0700), never a world-shared /tmp subdir; prune old
        # exports so they don't accumulate forever.
        output_dir = _app_export_dir()
        _prune_old_exports(output_dir)
        config = ScheduledExportConfig(output_dir=str(output_dir), formats=[fmt])
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
        report, session = _cached_report(profile, period)
        # Per-request private temp dir (unpredictable name, mode 0700) instead
        # of a fixed world-shared /tmp path a local user could pre-create and
        # then read or swap the file out from under FileResponse (FINDING 22).
        output_dir = Path(tempfile.mkdtemp(prefix="costsight-dl-"))
        config = ScheduledExportConfig(output_dir=str(output_dir), formats=[fmt])
        results = run_scheduled_export(report, config, session=session)
        r = results[0] if results else None
        if not r or not r.success or not r.destination:
            shutil.rmtree(output_dir, ignore_errors=True)
            err = r.error if r else "No output"
            return JSONResponse({"success": False, "error": err}, status_code=500)

        src = Path(r.destination)
        if not src.exists():
            shutil.rmtree(output_dir, ignore_errors=True)
            return JSONResponse({"success": False, "error": "Export file missing."}, status_code=500)

        filename = _safe_filename(name, _FMT_EXT[fmt])
        # The downloaded file is a throwaway intermediate — delete the whole
        # per-request dir after the response finishes streaming (FINDING 48).
        return FileResponse(
            path=src,
            media_type=_FMT_MEDIA[fmt],
            filename=filename,
            background=BackgroundTask(shutil.rmtree, output_dir, ignore_errors=True),
        )
    except Exception as exc:
        return JSONResponse({"success": False, "error": friendly_error(exc)}, status_code=500)


@router.get("/budgets/data")
def api_budgets_data(profile: str = Query("default")):
    from costsight.web.deps import cache_get, cache_set

    ckey = f"budgets:{profile}"
    cached = cache_get(ckey)
    if cached:
        return JSONResponse(cached)

    ctx: dict = {"error": None, "findings": []}
    try:
        session = get_session(profile)
        from costsight.audit.budgets import get_budget_findings
        findings = get_budget_findings(session)
        ctx["findings"] = [f.to_dict() for f in findings]
    except Exception as exc:
        ctx["error"] = friendly_error(exc)

    if ctx.get("error") is None:
        cache_set(ckey, ctx)
    return JSONResponse(ctx)


@router.post("/cache/clear")
async def api_cache_clear():
    return JSONResponse({"cleared": cache_bust()})
