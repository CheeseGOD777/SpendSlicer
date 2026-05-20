"""HTML page routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from aws_cost_ultra.web.context import base_ctx
from aws_cost_ultra.web.render import render

router = APIRouter()
_FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


@router.get("/", response_class=HTMLResponse)
def root_redirect():
    return RedirectResponse(url="/app", status_code=307)


@router.get("/legacy", response_class=HTMLResponse)
def dashboard(request: Request, profile: str = Query("default"), period: str = Query("mtd")):
    return render(request, "dashboard.html", base_ctx(profile, period, "dashboard"))


@router.get("/services", response_class=HTMLResponse)
def services_page(request: Request, profile: str = Query("default"), period: str = Query("mtd")):
    return render(request, "services.html", base_ctx(profile, period, "services"))


@router.get("/audit", response_class=HTMLResponse)
def audit_page(
    request: Request,
    profile: str = Query("default"),
    period: str = Query("mtd"),
    region: str = Query("all"),
):
    ctx = base_ctx(profile, period, "audit")
    ctx["region"] = region
    return render(request, "audit.html", ctx)


@router.get("/trends", response_class=HTMLResponse)
def trends_page(request: Request, profile: str = Query("default"), period: str = Query("3m")):
    return render(request, "trends.html", base_ctx(profile, period, "trends"))


@router.get("/resources", response_class=HTMLResponse)
def resources_page(
    request: Request,
    profile: str = Query("default"),
    period: str = Query("mtd"),
    region: str = Query("all"),
):
    ctx = base_ctx(profile, period, "resources")
    ctx["region"] = region
    return render(request, "resources.html", ctx)


@router.get("/export", response_class=HTMLResponse)
def export_page(request: Request, profile: str = Query("default"), period: str = Query("mtd")):
    return render(request, "export.html", base_ctx(profile, period, "export"))


@router.get("/api/ui/context")
def ui_context(profile: str = Query("default"), period: str = Query("mtd")):
    ctx = base_ctx(profile, period, "dashboard")
    return JSONResponse({
        "active_profile": ctx["active_profile"],
        "period": ctx["period"],
        "profiles": ctx["profiles"],
        "profile_choices": ctx["profile_choices"],
        "periods": [{"value": value, "label": label} for value, label in ctx["periods"]],
        "regions": [{"value": value, "label": label} for value, label in ctx["regions"]],
        "cost_basis_label": ctx["cost_basis_label"],
    })


@router.get("/app", response_class=HTMLResponse)
def react_app_index():
    index_path = _FRONTEND_DIST / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse(
        "Frontend build not found. Run: cd frontend && npm run build",
        status_code=404,
    )


@router.get("/app/{asset_path:path}", response_class=HTMLResponse)
def react_app_assets(asset_path: str):
    if not _FRONTEND_DIST.exists():
        return HTMLResponse(
            "Frontend build not found. Run: cd frontend && npm run build",
            status_code=404,
        )
    target = (_FRONTEND_DIST / asset_path).resolve()
    if target.is_file() and target.is_relative_to(_FRONTEND_DIST.resolve()):
        return FileResponse(target)
    return FileResponse(_FRONTEND_DIST / "index.html")
