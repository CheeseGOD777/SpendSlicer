"""HTML page routes."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from costsight.web.assets import frontend_dist
from costsight.web.context import base_ctx

router = APIRouter()

_BUILD_HINT = (
    "Dashboard bundle not found. Build it with: cd frontend && npm install && npm run build"
)


@router.get("/", response_class=HTMLResponse)
def root_redirect():
    return RedirectResponse(url="/app", status_code=307)


@router.get("/api/ui/context")
def ui_context(profile: str = Query("default"), period: str = Query("mtd")):
    from costsight.web.deps import available_periods

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
    dist = frontend_dist()
    if dist is None:
        return HTMLResponse(_BUILD_HINT, status_code=404)
    return FileResponse(dist / "index.html")


@router.get("/app/{asset_path:path}", response_class=HTMLResponse)
def react_app_assets(asset_path: str):
    dist = frontend_dist()
    if dist is None:
        return HTMLResponse(_BUILD_HINT, status_code=404)
    root = dist.resolve()
    target = (root / asset_path).resolve()
    # Containment check keeps ../ traversal out; unknown in-app routes fall
    # through to index.html so client-side routing keeps working on reload.
    if target.is_file() and target.is_relative_to(root):
        return FileResponse(target)
    return FileResponse(root / "index.html")
