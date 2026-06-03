"""Per-resource attribution API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from aws_cost_ultra.core.filters import pre_credit_gross
from aws_cost_ultra.resources import enumerate_all
from aws_cost_ultra.resources.runner import ALL_REGIONS
from aws_cost_ultra.web.context import friendly_error
from aws_cost_ultra.web.deps import (
    cache_get,
    cache_get_swr,
    cache_set,
    get_ce_client,
    get_cost_source,
    get_session,
    period_to_window,
    schedule_refresh,
)
from aws_cost_ultra.web.render import render

router = APIRouter(prefix="/api/resources")

# Hard server-side caps on the number of per-resource rows returned to the
# browser. Even when a caller requests an unbounded list (limit <= 0) we never
# materialize/serialize the entire account resource list into the response.
_DEFAULT_ROW_CAP = 500   # used when limit <= 0
_MAX_ROW_CAP = 2000      # absolute ceiling, even when limit > 0


def _apply_row_cap(rows: list, limit: int) -> list:
    """Sort rows by cost desc and apply the bounded cap.

    - limit <= 0  -> cap at _DEFAULT_ROW_CAP (never unbounded)
    - limit  > 0  -> honor limit but ceiling at _MAX_ROW_CAP
    """
    effective = _DEFAULT_ROW_CAP if limit <= 0 else min(limit, _MAX_ROW_CAP)
    return sorted(rows, key=lambda r: r.get("cost", 0.0), reverse=True)[:effective]


def _normalize_cur_row(r: dict) -> dict:
    """Pad a CUR-sourced resource dict to match the shape of AttributedResource.to_dict()."""
    return {
        "service": r.get("service", ""),
        "resource_id": r.get("resource_id", ""),
        "name": r.get("name", r.get("resource_id", "")),
        "type": "",
        "state": "",
        "cost": r.get("cost", 0.0),
        "hours": 0.0,
        "region": "",
        "waste_reason": None,
        "attributes": {},
        "tags": r.get("tags", {}),
    }


def build_resources_ctx(profile: str, period: str, region: str) -> dict:
    ctx: dict = {
        "error": None,
        "rows": [],
        "total": 0.0,
        "ce_total": 0.0,
        "unattributed": 0.0,
        "region": region,
        "region_label": "All opted-in regions" if region == ALL_REGIONS else region,
        "service": "",
        "services_summary": [],
        "cost_basis_label": "Pre-credit · CE ground truth",
    }
    try:
        session = get_session(profile)
        spec = pre_credit_gross()
        window = period_to_window(period)

        # Try CostSource path: CUR when available, describe-based fallback otherwise.
        try:
            account_id = session.client("sts").get_caller_identity()["Account"]
            src = get_cost_source(session)
            # CostSource handles CUR-first / CE-describe fallback internally.
            # Both paths return the same simplified dict shape, so always normalize.
            raw_rows = src.attribute_resources(account_id, window, session=session, spec=spec)
            ctx["rows"] = [_normalize_cur_row(r) for r in raw_rows]
        except Exception:
            # Any error in CostSource wiring falls back to existing describe path.
            rows = enumerate_all(session, window, region=region, spec=spec)
            ctx["rows"] = [r.to_dict() for r in rows]

        ctx["total"] = sum(r["cost"] for r in ctx["rows"])

        svc_totals: dict[str, float] = {}
        svc_counts: dict[str, int] = {}
        for r in ctx["rows"]:
            svc_totals[r["service"]] = svc_totals.get(r["service"], 0.0) + r["cost"]
            svc_counts[r["service"]] = svc_counts.get(r["service"], 0) + 1
        ctx["services_summary"] = sorted(
            [
                {"service": s, "total": t, "count": svc_counts[s]}
                for s, t in svc_totals.items() if t > 0.001
            ],
            key=lambda e: e["total"],
            reverse=True,
        )

        ce = get_ce_client(session)
        ce_total_cv = ce.get_total_cost(window, spec=spec)
        ctx["ce_total"] = ce_total_cv.amount_usd
        ctx["unattributed"] = max(ctx["ce_total"] - ctx["total"], 0.0)
        ctx["unattributed_pct"] = (
            ctx["unattributed"] / ctx["ce_total"] * 100 if ctx["ce_total"] > 0 else 0.0
        )
    except Exception as exc:
        ctx["error"] = friendly_error(exc)
    return ctx


@router.get("", response_class=HTMLResponse)
def api_resources(
    request: Request,
    profile: str = Query("default"),
    period: str = Query("mtd"),
    region: str = Query(ALL_REGIONS),
    service: str = Query(""),
    limit: int = Query(0),
):
    ckey = f"resources:{profile}:{period}:{region}"
    cached, should_refresh = cache_get_swr(ckey)
    if cached is None:
        cached = build_resources_ctx(profile, period, region)
        cache_set(ckey, cached)
    elif should_refresh:
        schedule_refresh(ckey, lambda: build_resources_ctx(profile, period, region))

    ctx = dict(cached)
    ctx["service"] = service
    rows = list(ctx.get("rows", []))
    if service:
        rows = [r for r in rows if r.get("service") == service]
    total_count = len(rows)
    rows = _apply_row_cap(rows, limit)
    ctx["total_count"] = total_count
    ctx["rows"] = rows
    return render(request, "partials/resource_table.html", ctx)


@router.get("/data")
def api_resources_data(
    profile: str = Query("default"),
    period: str = Query("mtd"),
    region: str = Query(ALL_REGIONS),
    service: str = Query(""),
    limit: int = Query(0),
):
    ckey = f"resources:{profile}:{period}:{region}"
    cached, should_refresh = cache_get_swr(ckey)
    if cached is None:
        cached = build_resources_ctx(profile, period, region)
        cache_set(ckey, cached)
    elif should_refresh:
        schedule_refresh(ckey, lambda: build_resources_ctx(profile, period, region))

    ctx = dict(cached)
    rows = list(ctx.get("rows", []))
    if service:
        rows = [r for r in rows if r.get("service") == service]
    total_count = len(rows)
    rows = _apply_row_cap(rows, limit)
    ctx["service"] = service
    # Total matching rows before the server-side cap, so the UI can render
    # "showing N of M" without ever receiving the full unbounded list.
    ctx["total_count"] = total_count
    ctx["rows"] = rows
    return JSONResponse(ctx)


@router.get("/top", response_class=HTMLResponse)
def api_resources_top(
    request: Request,
    profile: str = Query("default"),
    period: str = Query("mtd"),
    region: str = Query(ALL_REGIONS),
    limit: int = Query(10),
):
    """Dashboard widget — top N resources by CE-backed cost."""
    return api_resources(
        request, profile=profile, period=period, region=region, service="", limit=limit,
    )


@router.get("/top/data")
def api_resources_top_data(
    profile: str = Query("default"),
    period: str = Query("mtd"),
    region: str = Query(ALL_REGIONS),
    limit: int = Query(10),
):
    # Fast path for dashboard: never block first paint on full attribution scan.
    ckey = f"resources:{profile}:{period}:{region}"
    cached, should_refresh = cache_get_swr(ckey)
    if cached is None:
        schedule_refresh(ckey, lambda: build_resources_ctx(profile, period, region))
        return JSONResponse({
            "error": None,
            "rows": [],
            "service": "",
            "services_summary": [],
            "total": 0.0,
            "ce_total": 0.0,
            "unattributed": 0.0,
            "unattributed_pct": 0.0,
            "warming": True,
            "region": region,
            "region_label": "All opted-in regions" if region == ALL_REGIONS else region,
            "cost_basis_label": "Pre-credit · CE ground truth",
        })
    if should_refresh:
        schedule_refresh(ckey, lambda: build_resources_ctx(profile, period, region))

    rows = sorted(list(cached.get("rows", [])), key=lambda r: r.get("cost", 0.0), reverse=True)[:limit]
    ctx = dict(cached)
    ctx["service"] = ""
    ctx["rows"] = rows
    ctx["warming"] = False
    return JSONResponse(ctx)


@router.get("/services", response_class=HTMLResponse)
def api_resources_services(
    request: Request,
    profile: str = Query("default"),
    period: str = Query("mtd"),
    region: str = Query(ALL_REGIONS),
    active_service: str = Query(""),
):
    ckey = f"resources:{profile}:{period}:{region}"
    cached = cache_get(ckey)
    services_summary = (cached or {}).get("services_summary", []) if cached else []
    ctx = {
        "services_summary": services_summary,
        "active_service": active_service,
        "profile": profile,
        "period": period,
        "region": region,
    }
    return render(request, "partials/resource_tabs.html", ctx)


@router.get("/services/data")
def api_resources_services_data(
    profile: str = Query("default"),
    period: str = Query("mtd"),
    region: str = Query(ALL_REGIONS),
):
    ckey = f"resources:{profile}:{period}:{region}"
    cached = cache_get(ckey)
    if not cached:
        cached = build_resources_ctx(profile, period, region)
        cache_set(ckey, cached)
    return JSONResponse({
        "services_summary": cached.get("services_summary", []),
        "profile": profile,
        "period": period,
        "region": region,
    })
