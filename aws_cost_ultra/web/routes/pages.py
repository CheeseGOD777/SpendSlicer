"""HTML page routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from aws_cost_ultra.web.context import base_ctx

router = APIRouter()
_FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"


@router.get("/", response_class=HTMLResponse)
def root_redirect():
    return RedirectResponse(url="/app", status_code=307)


@router.get("/api/ui/context")
def ui_context(profile: str = Query("default"), period: str = Query("mtd")):
    from aws_cost_ultra.web.deps import available_periods

    ctx = base_ctx(profile, period, "dashboard")
    return JSONResponse({
        "active_profile": ctx["active_profile"],
        "period": ctx["period"],
        "profiles": ctx["profiles"],
        "profile_choices": ctx["profile_choices"],
        # Grouped {value,label,group} so the picker can show Ranges and Months
        # as separate <optgroup>s while both remain selectable simultaneously.
        "periods": available_periods(),
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
