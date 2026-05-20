"""FastAPI application entry point."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from aws_cost_ultra.web.context import get_profile_choices
from aws_cost_ultra.web.deps import get_profiles
from aws_cost_ultra.web.prewarm import prewarm_background
from aws_cost_ultra.web.middleware import CECountingMiddleware
from aws_cost_ultra.web.routes import audit_api, cost, export_api, pages, resources_api

_HERE = Path(__file__).parent

app = FastAPI(
    title="aws-cost-ultra",
    description="Self-hosted AWS cost visibility — uses your local AWS CLI profiles.",
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(CECountingMiddleware)

app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

app.include_router(pages.router)
app.include_router(cost.router)
app.include_router(resources_api.router)
app.include_router(audit_api.router)
app.include_router(export_api.router)


@app.on_event("startup")
def _kick_prewarm() -> None:
    get_profile_choices()
    # Disabled by default to avoid large CE/API fan-out on startup.
    # Enable explicitly for kiosk-like deployments.
    if os.environ.get("ACU_ENABLE_PREWARM", "0").lower() in ("1", "true", "yes"):
        profiles = get_profiles()
        threading.Thread(
            target=prewarm_background,
            args=(profiles,),
            daemon=True,
            name="acu-prewarm",
        ).start()


def serve(host: str = "127.0.0.1", port: int = 8080, reload: bool = False) -> None:
    import uvicorn
    uvicorn.run("aws_cost_ultra.web.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    serve(reload=True)
