"""FastAPI application entry point."""

from __future__ import annotations

import hmac
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from aws_cost_ultra.web.context import get_profile_choices
from aws_cost_ultra.web.deps import get_profiles
from aws_cost_ultra.web.prewarm import prewarm_background
from aws_cost_ultra.web.middleware import CECountingMiddleware
from aws_cost_ultra.web.routes import audit_api, cost, export_api, pages, resources_api

_HERE = Path(__file__).parent


def _auth_token() -> str:
    """Shared-secret token; empty/unset means auth is disabled (localhost UX)."""
    return (os.environ.get("ACU_AUTH_TOKEN") or "").strip()


def _allowed_hosts() -> set[str]:
    """Hosts this server is willing to answer state-changing requests for.

    Defaults to loopback only (the documented bind target). Override with
    ACU_ALLOWED_HOSTS (comma-separated) for non-loopback deployments. Used as
    an anti-DNS-rebinding / CSRF allow-list (FINDING 15).
    """
    env = (os.environ.get("ACU_ALLOWED_HOSTS") or "").strip()
    if env:
        return {h.strip().lower() for h in env.split(",") if h.strip()}
    return {"localhost", "127.0.0.1", "::1", "[::1]"}


def _host_of(value: str) -> str:
    """Bare hostname from a Host header authority (drops port, brackets)."""
    h = (value or "").strip().lower()
    if h.startswith("["):  # IPv6 literal e.g. [::1]:8080
        return h[1:].split("]", 1)[0]
    return h.split(":", 1)[0]


def _has_valid_token(request: Request) -> bool:
    token = _auth_token()
    if not token:
        return False
    presented = request.headers.get("x-acu-token") or request.query_params.get("token") or ""
    return hmac.compare_digest(presented, token)


# Path prefixes that never spend AWS money and stay open regardless of auth.
# Static is mounted (not subject to app-level dependencies) but listed for clarity.
_OPEN_PREFIXES = ("/static",)
# Exact paths that just serve HTML shells / non-AWS context — open even when gated.
_OPEN_PATHS = {"/", "/app"}


def _is_open_path(path: str) -> bool:
    if path in _OPEN_PATHS:
        return True
    if path.startswith("/app/"):
        return True
    return any(path.startswith(p) for p in _OPEN_PREFIXES)


def _origin_host_allowed(request: Request) -> bool:
    """CSRF / DNS-rebinding defense for state-changing requests (FINDING 15).

    1. The request's own Host must be in the allow-list — this blocks DNS
       rebinding (an attacker page resolving their domain to 127.0.0.1 then
       POSTing here would carry a non-allowed Host).
    2. If an Origin/Referer is present, its host must also be in the allow-list
       (blocks classic cross-origin CSRF).
    3. If neither Origin nor Referer is present, allow only when the request
       carries a valid token (an authenticated non-browser client such as
       curl). Previously this case was allowed unconditionally, which left an
       unauthenticated CSRF hole.
    """
    from urllib.parse import urlsplit

    allowed = _allowed_hosts()

    host = _host_of(request.headers.get("host") or "")
    if host and host not in allowed:
        return False

    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        return _has_valid_token(request)
    src_host = (urlsplit(origin).hostname or "").lower()
    return bool(src_host) and src_host in allowed


async def require_auth(request: Request) -> None:
    """Global dependency: token auth (when configured) + CSRF Origin check.

    - Token (ACU_AUTH_TOKEN) is required on every money-spending route via the
      X-ACU-Token header or `token` query param; mismatch -> 401. When unset,
      auth is disabled to preserve the zero-config localhost experience.
    - State-changing POSTs additionally enforce an Origin/Referer allow-list as
      defense-in-depth (active even when no token is configured).
    """
    path = request.url.path
    if _is_open_path(path):
        return

    # CSRF: reject cross-origin state-changing requests regardless of token.
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not _origin_host_allowed(request):
            raise HTTPException(status_code=403, detail="Cross-origin request rejected.")

    token = _auth_token()
    if not token:
        return  # auth disabled

    presented = request.headers.get("x-acu-token") or request.query_params.get("token") or ""
    # Constant-time compare so a timing side-channel can't recover the token.
    if not hmac.compare_digest(presented, token):
        raise HTTPException(status_code=401, detail="Invalid or missing API token.")


app = FastAPI(
    title="aws-cost-ultra",
    description="Self-hosted AWS cost visibility — uses your local AWS CLI profiles.",
    docs_url=None,
    redoc_url=None,
    dependencies=[Depends(require_auth)],
)

app.add_middleware(CECountingMiddleware)

app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

app.include_router(pages.router)
app.include_router(cost.router)
app.include_router(resources_api.router)
app.include_router(audit_api.router)
app.include_router(export_api.router)


@app.on_event("startup")
def _warn_if_unauthenticated() -> None:
    if not _auth_token():
        log.warning(
            "ACU_AUTH_TOKEN is not set — server is UNAUTHENTICATED. "
            "Anyone who can reach this port can spend real AWS money via Cost Explorer. "
            "Set ACU_AUTH_TOKEN to require a token (X-ACU-Token header or ?token=...)."
        )


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


def _cur_ingest_worker() -> None:
    interval = float(os.environ.get("ACU_CUR_INGEST_INTERVAL_SECONDS", str(6 * 3600)))
    bucket = os.environ.get("ACU_CUR_BUCKET")
    prefix = os.environ.get("ACU_CUR_PREFIX", "cur/")
    profile = os.environ.get("ACU_CUR_PROFILE")
    if not bucket:
        return
    while True:
        db = None
        try:
            import boto3
            from aws_cost_ultra.cur.ingestor import CurIngestor
            from aws_cost_ultra.cur.schema import connect as cur_connect
            from aws_cost_ultra.web.deps import _CUR_DB_PATH, _CACHE_DIR
            session = boto3.Session(profile_name=profile) if profile else boto3.Session()
            db = cur_connect(_CUR_DB_PATH)
            local_dir = _CACHE_DIR / "parquet"
            CurIngestor(
                s3_client=session.client("s3"),
                bucket=bucket,
                prefix=prefix,
                local_dir=local_dir,
                db=db,
            ).ingest()
        except Exception as exc:
            log.warning("CUR background ingest failed: %s", exc, exc_info=True)
        finally:
            if db is not None:
                db.close()
        time.sleep(interval)


@app.on_event("startup")
def _start_cur_worker() -> None:
    if os.environ.get("ACU_CUR_BUCKET"):
        t = threading.Thread(target=_cur_ingest_worker, daemon=True, name="acu-cur-ingest")
        t.start()
        log.info("CUR background ingest worker started (bucket=%s)", os.environ["ACU_CUR_BUCKET"])


def serve(host: str = "127.0.0.1", port: int = 8080, reload: bool = False) -> None:
    import uvicorn
    uvicorn.run("aws_cost_ultra.web.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    serve(reload=True)
