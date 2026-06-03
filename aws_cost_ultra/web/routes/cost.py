"""Cost Explorer API routes (HTMX + JSON)."""

from __future__ import annotations

import contextvars
import html
import json
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from aws_cost_ultra.core.filters import pre_credit_gross
from aws_cost_ultra.core.service_groups import merge_ec2_service_groups, service_rows_from_groups
from aws_cost_ultra.core.time_windows import current_month, last_month, month_before_last, remainder_of_current_month
from aws_cost_ultra.core.types import Granularity, TimeWindow
from aws_cost_ultra.web.context import friendly_error
from aws_cost_ultra.web.deps import cache_get, cache_set, get_ce_client, get_cost_source, get_session, period_to_window
from aws_cost_ultra.web.render import render

router = APIRouter(prefix="/api/cost")


_KNOWN_PERIODS = ("mtd", "last_month", "30d", "60d", "90d", "3m", "6m", "12m")


def _json_for_script(value) -> str:
    """json.dumps escaped for safe embedding inside an inline <script> body.

    json.dumps does NOT escape ``</script>``, ``<``, ``>``, ``&`` or the
    JS line-terminators U+2028/U+2029, so a string value reaching here
    could break out of the script context. Escape them defensively.
    """
    s = json.dumps(value)
    return (
        s.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def _trend_granularity_for_period(period: str) -> Granularity:
    # Month-to-date and short windows need daily points; monthly collapses to 1 bar.
    if period in ("mtd", "30d", "last_month"):
        return Granularity.DAILY
    return Granularity.MONTHLY


def _prev_window(period: str, window: TimeWindow) -> TimeWindow:
    """Window to compare the current ``window`` against.

    For true calendar-month periods stay calendar-aligned; for rolling
    windows return the immediately-preceding window of the same duration.
    """
    if period == "mtd":
        return last_month()
    if period == "last_month":
        return month_before_last()
    dur = window.end - window.start
    return TimeWindow(start=window.start - dur, end=window.start)


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

        # account_id is required as the cache namespace so two profiles
        # pointing at different accounts don't share matrix entries.
        account_id = session.client("sts").get_caller_identity()["Account"]

        window = period_to_window(period)
        prev_window = _prev_window(period, window)
        fcast_window = remainder_of_current_month()
        mtd_window = window if period == "mtd" else current_month()

        src = get_cost_source(session)

        # Parallelism is preserved — but everything is cached so cold cost
        # is at most 3 CE calls (window, prev, optional mtd) + 1 forecast.
        # Each submit runs inside a copied context so the CE call-counter
        # ContextVar set by middleware propagates into the worker threads.
        with ThreadPoolExecutor(max_workers=4) as pool:
            f_matrix = pool.submit(
                contextvars.copy_context().run, src.get_matrix, profile, account_id, window, spec
            )
            f_prev_matrix = pool.submit(
                contextvars.copy_context().run, src.get_matrix, profile, account_id, prev_window, spec
            )
            f_forecast = pool.submit(
                contextvars.copy_context().run, lambda: ce.get_forecast(fcast_window, spec=spec)
            )
            f_mtd_matrix = (
                pool.submit(
                    contextvars.copy_context().run, src.get_matrix, profile, account_id, mtd_window, spec
                )
                if period != "mtd" else None
            )

        m = f_matrix.result()
        prev_m = f_prev_matrix.result()
        forecast_cv = f_forecast.result()
        mtd_m = f_mtd_matrix.result() if f_mtd_matrix else m

        # Build a synthetic provenance label for the merged services list.
        # The matrix already carries no per-cell provenance; use a coarse one.
        from aws_cost_ultra.core.provenance import Provenance
        from aws_cost_ultra.core.types import CostMetric
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

        total_amount = m.total()
        prev_amount = prev_m.total()
        mtd_amount = mtd_m.total()

        ctx["total_mtd"] = total_amount
        ctx["total_prev"] = prev_amount
        if prev_amount >= 0.50:
            raw = (total_amount - prev_amount) / prev_amount * 100
            ctx["change_pct"] = max(-999.9, min(9999.9, raw))
        if forecast_cv:
            ctx["forecast"] = mtd_amount + forecast_cv.amount_usd
            ctx["forecast_mtd_actual"] = mtd_amount
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
        spec = pre_credit_gross()
        account_id = session.client("sts").get_caller_identity()["Account"]
        window = period_to_window(period)
        prev_window = _prev_window(period, window)

        src = get_cost_source(session)

        # Copy the context into each worker so the CE call-counter ContextVar
        # set by middleware reaches the pool threads (see X-CE-Calls-Spent).
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_matrix = pool.submit(
                contextvars.copy_context().run, src.get_matrix, profile, account_id, window, spec
            )
            f_prev = pool.submit(
                contextvars.copy_context().run, src.get_matrix, profile, account_id, prev_window, spec
            )

        m = f_matrix.result()
        prev_m = f_prev.result()

        from aws_cost_ultra.core.provenance import Provenance
        from aws_cost_ultra.core.types import CostMetric
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

        groups = merge_ec2_service_groups(m.to_grouped_cost_list(prov))
        prev_map = {svc: cost for svc, cost in prev_m.by_service()}

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
    if ctx.get("error") is None:
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
    if ctx.get("error") is None:
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
    if ctx.get("error") is None:
        cache_set(ckey, ctx)

    if chart:
        labels = [s["name"][:24] for s in ctx.get("services", [])[:10]]
        values = [s["cost"] for s in ctx.get("services", [])[:10]]
        html = (
            f'<canvas id="service-chart" style="height:400px;display:block;width:100%"></canvas>'
            f"<script>buildServiceChart('service-chart',"
            f"{_json_for_script(labels)},{_json_for_script(values)});</script>"
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
    if ctx.get("error") is None:
        cache_set(ckey, ctx)
    return JSONResponse(ctx)


# ---------------------------------------------------------------------------
# Service composition (USAGE_TYPE bucketing) — what's actually driving each
# service's spend: compute vs storage vs data-transfer vs network vs other.
# Single CE call (SERVICE × USAGE_TYPE) covers every service in the window.
# ---------------------------------------------------------------------------

_COMPOSITION_BUCKETS = ("compute", "storage", "data-transfer", "network", "other")
_EC2_MERGED_NAME = "Amazon Elastic Compute Cloud"
_EC2_RAW_NAMES = frozenset({
    "Amazon Elastic Compute Cloud - Compute",
    "EC2 - Other",
})


def _bucket_for_usage_type(usage_type: str) -> str:
    ut = usage_type or ""
    if "DataTransfer" in ut:
        return "data-transfer"
    network_markers = (
        "NatGateway", "LoadBalancer", "LCU", "ElasticIP", "PublicIPv4",
        "VPN", "VpcEndpoint", "TransitGateway", "DirectConnect",
    )
    if any(m in ut for m in network_markers):
        return "network"
    storage_markers = (
        "Storage", "EBS:", "Snapshot", "Piops", "IOUsage",
        "ByteHrs", "TimedStorage",
    )
    if any(m in ut for m in storage_markers):
        return "storage"
    compute_markers = (
        "BoxUsage", "SpotUsage", "HeavyUsage", "DedicatedUsage",
        "InstanceUsage", "Lambda-GB-Second", "Lambda-Edge",
        "Multi-AZ", "ServerlessUsage", "GB-Hours",
    )
    if any(m in ut for m in compute_markers):
        return "compute"
    return "other"


def _build_services_composition_ctx(profile: str, period: str) -> dict:
    ctx: dict = {"error": None, "services": {}, "cost_basis_label": ""}
    try:
        session = get_session(profile)
        ce = get_ce_client(session)
        spec = pre_credit_gross()
        window = period_to_window(period)
        groups = ce.get_cost_by_service_and_usage_type(window, spec=spec)

        services: dict[str, dict] = {}
        for g in groups:
            if len(g.key) < 2:
                continue
            svc, ut = g.key[0], g.key[1]
            amount = g.value.amount_usd
            if svc in _EC2_RAW_NAMES:
                svc = _EC2_MERGED_NAME
            bucket = _bucket_for_usage_type(ut)
            entry = services.setdefault(svc, {b: 0.0 for b in _COMPOSITION_BUCKETS})
            entry[bucket] += amount

        ctx["services"] = {
            svc: {**buckets, "total": sum(buckets.values())}
            for svc, buckets in services.items()
        }
        ctx["buckets"] = list(_COMPOSITION_BUCKETS)
        ctx["cost_basis_label"] = spec.summary() or "Pre-credit gross usage"
    except Exception as exc:
        ctx["error"] = friendly_error(exc)
    return ctx


@router.get("/services/composition/data")
def api_cost_services_composition_data(
    profile: str = Query("default"),
    period: str = Query("mtd"),
):
    ckey = f"services_composition_json:{profile}:{period}"
    cached = cache_get(ckey)
    if cached:
        return JSONResponse(cached)
    ctx = _build_services_composition_ctx(profile, period)
    if ctx.get("error") is None:
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
    # Validate period against the known set; profile is neutralised by urlencode.
    if period not in _KNOWN_PERIODS:
        period = "3m"
    qs = urllib.parse.urlencode({"profile": profile, "period": period})
    data_url = f"/api/cost/trend/data?{qs}"
    # Emit the URL into a data-* attribute (HTML-escaped) instead of
    # interpolating untrusted input into the inline <script> body.
    attr = html.escape(data_url, quote=True)
    markup = (
        f'<canvas id="trend-chart" data-url="{attr}" '
        f'style="height:220px;display:block;width:100%"></canvas>'
        f"<script>(function(){{var el=document.getElementById('trend-chart');"
        f"fetch(el.dataset.url).then(r=>r.json()).then(d=>{{"
        f"if(d.labels&&d.values)buildTrendChart('trend-chart',d.labels,d.values);"
        f"}}).catch(()=>{{}});}})();</script>"
    )
    return HTMLResponse(markup)


@router.get("/trend-table", response_class=HTMLResponse)
def api_trend_table(
    request: Request,
    profile: str = Query("default"),
    period: str = Query("3m"),
):
    gran = _trend_granularity_for_period(period)
    ckey = f"trend_table_html:{profile}:{period}:{gran.value}"
    cached = cache_get(ckey)
    if cached:
        return render(request, "partials/trend_table.html", cached)

    ctx: dict = {
        "error": None,
        "points": [],
        "max_cost": 0.0,
        "cost_basis_label": "Pre-credit · excludes Credit/Refund · UTC",
    }
    try:
        session = get_session(profile)
        ce = get_ce_client(session)
        window = period_to_window(period)
        raw = ce.get_trend(window, granularity=gran, spec=pre_credit_gross())
        period_fmt = (lambda p: p.period_start[:10]) if gran == Granularity.DAILY else (lambda p: p.period_start[:7])
        points = [{"period": period_fmt(p), "cost": p.value.amount_usd} for p in reversed(raw)]
        ctx["points"] = points
        ctx["max_cost"] = max((p["cost"] for p in points), default=0.0)
    except Exception as exc:
        ctx["error"] = friendly_error(exc)
    if ctx.get("error") is None:
        cache_set(ckey, ctx)
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

    ctx: dict = {
        "error": None,
        "points": [],
        "max_cost": 0.0,
        "cost_basis_label": "Pre-credit · excludes Credit/Refund · UTC",
    }
    try:
        session = get_session(profile)
        ce = get_ce_client(session)
        window = period_to_window(period)
        raw = ce.get_trend(window, granularity=gran, spec=pre_credit_gross())
        period_fmt = (lambda p: p.period_start[:10]) if gran == Granularity.DAILY else (lambda p: p.period_start[:7])
        points = [{"period": period_fmt(p), "cost": p.value.amount_usd} for p in reversed(raw)]
        ctx["points"] = points
        ctx["max_cost"] = max((p["cost"] for p in points), default=0.0)
    except Exception as exc:
        ctx["error"] = friendly_error(exc)
    if ctx.get("error") is None:
        cache_set(ckey, ctx)
    return JSONResponse(ctx)


