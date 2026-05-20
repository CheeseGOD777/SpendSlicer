"""Jinja2 rendering helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

_HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))


def fmt_usd(v: Optional[float], decimals: int = 2) -> str:
    if v is None:
        return "—"
    return f"${v:,.{decimals}f}"


def fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.1f}%"


def delta_class(v: Optional[float]) -> str:
    if v is None:
        return "delta-neutral"
    return "delta-up" if v >= 0 else "delta-down"


templates.env.globals.update(
    fmt_usd=fmt_usd,
    fmt_pct=fmt_pct,
    delta_class=delta_class,
    enumerate=enumerate,
)
templates.env.filters["abs"] = abs
templates.env.filters["thousands"] = lambda v: f"{int(v):,}"


def render(request: Request, name: str, ctx: dict) -> HTMLResponse:
    return templates.TemplateResponse(request, name, ctx)
