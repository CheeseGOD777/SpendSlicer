"""Cost Explorer API routes (HTMX + JSON)."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from aws_cost_ultra.core.filters import pre_credit_gross
from aws_cost_ultra.core.service_groups import merge_ec2_service_groups, service_rows_from_groups
from aws_cost_ultra.core.time_windows import current_month, remainder_of_current_month
from aws_cost_ultra.core.types import Granularity
from aws_cost_ultra.web.context import friendly_error
from aws_cost_ultra.web.deps import cache_get, cache_set, get_ce_client, get_session, period_to_window
from aws_cost_ultra.web.render import render

router = APIRouter(prefix="/api/cost")


def _trend_granularity_for_period(period: str) -> Granularity:
    # Month-to-date and short windows need daily points; monthly collapses to 1 bar.
    if period in ("mtd", "30d", "last_month"):
        return Granularity.DAILY
    return Granularity.MONTHLY


def _build_summary_ctx(profile: str, period: str) -> dict:
    ctx: dict = {
        "error": None,
        "total_mtd": None,
        "total_prev": None,
        "change_pct": None,
        "forecast": None,
        "top_service_name": None,
        "top_service_cost": None,
        "period": period,
        "cost_basis_label": "Pre-credit · excludes Credit/Refund · UTC",
    }
    try:
        session = get_session(profile)
        ce = get_ce_client(session)
        spec = pre_credit_gross()
        window = period_to_window(period)
        prev_window = period_to_window("last_month") if period in ("mtd", "3m", "30d") else period_to_window("3m")
        fcast_window = remainder_of_current_month()
        mtd_window = window if period == "mtd" else current_month()

        with ThreadPoolExecutor(max_workers=4) as pool:
            f_total = pool.submit(ce.get_total_cost, window, spec=spec)
            f_prev = pool.submit(ce.get_total_cost, prev_window, spec=spec)
            f_services = pool.submit(ce.get_cost_by_service, window, spec=spec)
            f_forecast = pool.submit(ce.get_forecast, fcast_window, spec=spec)
            f_mtd = pool.submit(ce.get_total_cost, mtd_window, spec=spec) if period != "mtd" else None

        total_cv = f_total.result()
        prev_cv = f_prev.result()
        services = merge_ec2_service_groups(f_services.result())
        forecast_cv = f_forecast.result()
        mtd_cv = f_mtd.result() if f_mtd else total_cv

        ctx["total_mtd"] = total_cv.amount_usd
        ctx["total_prev"] = prev_cv.amount_usd
        if prev_cv.amount_usd >= 0.50:
            raw = (total_cv.amount_usd - prev_cv.amount_usd) / prev_cv.amount_usd * 100
            ctx["change_pct"] = max(-999.9, min(9999.9, raw))
        if forecast_cv:
            ctx["forecast"] = mtd_cv.amount_usd + forecast_cv.amount_usd
            ctx["forecast_mtd_actual"] = mtd_cv.amount_usd
        if services:
            ctx["top_service_name"] = services[0].primary_key()
            ctx["top_service_cost"] = services[0].value.amount_usd
            ctx["top_service_provenance"] = services[0].value.provenance.label()
    except Exception as exc:
        ctx["error"] = friendly_error(exc)
    return ctx


def _build_services_ctx(profile: str, period: str, limit: int) -> dict:
    ctx: dict = {"error": None, "services": [], "total": 0.0, "cost_basis_label": ""}
    try:
        session = get_session(profile)
        ce = get_ce_client(session)
        spec = pre_credit_gross()
        window = period_to_window(period)
        prev_window = period_to_window("last_month") if period in ("mtd", "30d") else period_to_window("3m")

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_groups = pool.submit(ce.get_cost_by_service, window, spec=spec)
            f_prev = pool.submit(ce.get_cost_by_service, prev_window, spec=spec)
        groups = merge_ec2_service_groups(f_groups.result())
        prev_map = {g.primary_key(): g.value.amount_usd for g in f_prev.result()}

        effective_limit = limit if limit > 0 else None
        services, total = service_rows_from_groups(groups, prev_map, limit=effective_limit)
        ctx["services"] = services
        ctx["total"] = total
        ctx["cost_basis_label"] = spec.summary() or "Pre-credit gross usage"
    except Exception as exc:
        ctx["error"] = friendly_error(exc)
    return ctx


@router.get("/summary", response_class=HTMLResponse)
def api_cost_summary(
    request: Request,
    profile: str = Query("default"),
    period: str = Query("mtd"),
):
    ckey = f"summary:{profile}:{period}"
    cached = cache_get(ckey)
    if cached:
        return render(request, "partials/cost_cards.html", cached)

    ctx = _build_summary_ctx(profile, period)
    cache_set(ckey, ctx)
    return render(request, "partials/cost_cards.html", ctx)


@router.get("/summary/data")
def api_cost_summary_data(
    profile: str = Query("default"),
    period: str = Query("mtd"),
):
    ckey = f"summary_json:{profile}:{period}"
    cached = cache_get(ckey)
    if cached:
        return JSONResponse(cached)
    ctx = _build_summary_ctx(profile, period)
    cache_set(ckey, ctx)
    return JSONResponse(ctx)


@router.get("/services", response_class=HTMLResponse)
def api_cost_services(
    request: Request,
    profile: str = Query("default"),
    period: str = Query("mtd"),
    limit: int = Query(0),
    chart: int = Query(0),
):
    ckey = f"services:{profile}:{period}:{limit}"
    cached = cache_get(ckey)
    if cached and not chart:
        return render(request, "partials/service_table.html", cached)

    ctx = _build_services_ctx(profile, period, limit)
    cache_set(ckey, ctx)

    if chart:
        labels = [s["name"][:24] for s in ctx.get("services", [])[:10]]
        values = [s["cost"] for s in ctx.get("services", [])[:10]]
        html = (
            f'<canvas id="service-chart" style="height:400px;display:block;width:100%"></canvas>'
            f"<script>buildServiceChart('service-chart',"
            f"{json.dumps(labels)},{json.dumps(values)});</script>"
        )
        return HTMLResponse(html)

    return render(request, "partials/service_table.html", ctx)


@router.get("/services/data")
def api_cost_services_data(
    profile: str = Query("default"),
    period: str = Query("mtd"),
    limit: int = Query(0),
):
    ckey = f"services_json:{profile}:{period}:{limit}"
    cached = cache_get(ckey)
    if cached:
        return JSONResponse(cached)
    ctx = _build_services_ctx(profile, period, limit)
    cache_set(ckey, ctx)
    return JSONResponse(ctx)


@router.get("/trend/data")
def api_trend_data(profile: str = Query("default"), period: str = Query("3m")):
    gran = _trend_granularity_for_period(period)
    ckey = f"trend_data:{profile}:{period}:{gran.value}"
    cached = cache_get(ckey)
    if cached:
        return JSONResponse(cached)
    try:
        session = get_session(profile)
        ce = get_ce_client(session)
        spec = pre_credit_gross()
        window = period_to_window(period)
        points = ce.get_trend(window, granularity=gran, spec=spec)
        labels = [p.period_start[:10] for p in points] if gran == Granularity.DAILY else [p.period_start[:7] for p in points]
        data = {
            "labels": labels,
            "values": [round(p.value.amount_usd, 3) for p in points],
        }
        cache_set(ckey, data)
        return JSONResponse(data)
    except Exception as exc:
        return JSONResponse({"error": friendly_error(exc), "labels": [], "values": []})


@router.get("/trend-chart", response_class=HTMLResponse)
def api_trend_chart(profile: str = Query("default"), period: str = Query("3m")):
    data_url = f"/api/cost/trend/data?profile={profile}&period={period}"
    html = (
        f'<canvas id="trend-chart" style="height:220px;display:block;width:100%"></canvas>'
        f'<script>fetch("{data_url}").then(r=>r.json()).then(d=>{{'
        f"if(d.labels&&d.values)buildTrendChart('trend-chart',d.labels,d.values);"
        f"}}).catch(()=>{{}});</script>"
    )
    return HTMLResponse(html)


@router.get("/trend-table", response_class=HTMLResponse)
def api_trend_table(
    request: Request,
    profile: str = Query("default"),
    period: str = Query("3m"),
):
    ctx: dict = {"error": None, "points": [], "max_cost": 0.0}
    try:
        session = get_session(profile)
        ce = get_ce_client(session)
        window = period_to_window(period)
        gran = _trend_granularity_for_period(period)
        raw = ce.get_trend(window, granularity=gran)
        period_fmt = (lambda p: p.period_start[:10]) if gran == Granularity.DAILY else (lambda p: p.period_start[:7])
        points = [{"period": period_fmt(p), "cost": p.value.amount_usd} for p in reversed(raw)]
        ctx["points"] = points
        ctx["max_cost"] = max((p["cost"] for p in points), default=0.0)
    except Exception as exc:
        ctx["error"] = friendly_error(exc)
    return render(request, "partials/trend_table.html", ctx)


@router.get("/trend-table/data")
def api_trend_table_data(
    profile: str = Query("default"),
    period: str = Query("3m"),
):
    gran = _trend_granularity_for_period(period)
    ckey = f"trend_table_json:{profile}:{period}:{gran.value}"
    cached = cache_get(ckey)
    if cached:
        return JSONResponse(cached)

    ctx: dict = {"error": None, "points": [], "max_cost": 0.0}
    try:
        session = get_session(profile)
        ce = get_ce_client(session)
        window = period_to_window(period)
        raw = ce.get_trend(window, granularity=gran)
        period_fmt = (lambda p: p.period_start[:10]) if gran == Granularity.DAILY else (lambda p: p.period_start[:7])
        points = [{"period": period_fmt(p), "cost": p.value.amount_usd} for p in reversed(raw)]
        ctx["points"] = points
        ctx["max_cost"] = max((p["cost"] for p in points), default=0.0)
    except Exception as exc:
        ctx["error"] = friendly_error(exc)
    cache_set(ckey, ctx)
    return JSONResponse(ctx)


