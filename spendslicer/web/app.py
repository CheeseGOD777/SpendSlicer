"""FastAPI application entry point."""

from __future__ import annotations

import hmac
import logging
import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request

from spendslicer.web.context import get_profile_choices
from spendslicer.web.deps import get_profiles
from spendslicer.web.middleware import CECountingMiddleware
from spendslicer.web.prewarm import prewarm_background
from spendslicer.web.routes import audit_api, cost, export_api, pages, resources_api

log = logging.getLogger(__name__)


def _auth_token() -> str:
    """Shared-secret token; empty/unset means auth is disabled (localhost UX)."""
    return (os.environ.get("SPENDSLICER_AUTH_TOKEN") or "").strip()


def _allowed_hosts() -> set[str]:
    """Hosts this server is willing to answer state-changing requests for.

    Defaults to loopback only (the documented bind target). Override with
    SPENDSLICER_ALLOWED_HOSTS (comma-separated) for non-loopback deployments. Used as
    an anti-DNS-rebinding / CSRF allow-list.
    """
    env = (os.environ.get("SPENDSLICER_ALLOWED_HOSTS") or "").strip()
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
    presented = request.headers.get("x-spendslicer-token") or request.query_params.get("token") or ""
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
    """CSRF / DNS-rebinding defense for state-changing requests.

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

    - Token (SPENDSLICER_AUTH_TOKEN) is required on every money-spending route via the
      X-SpendSlicer-Token header or `token` query param; mismatch -> 401. When unset,
      auth is disabled to preserve the zero-config localhost experience.
    - State-changing POSTs additionally enforce an Origin/Referer allow-list as
      defense-in-depth (active even when no token is configured).
    """
    path = request.url.path
    if _is_open_path(path):
        return

    # CSRF: reject cross-origin state-changing requests regardless of token.
    if request.method not in ("GET", "HEAD", "OPTIONS") and not _origin_host_allowed(request):
        raise HTTPException(status_code=403, detail="Cross-origin request rejected.")

    token = _auth_token()
    if not token:
        return  # auth disabled

    presented = request.headers.get("x-spendslicer-token") or request.query_params.get("token") or ""
    # Constant-time compare so a timing side-channel can't recover the token.
    if not hmac.compare_digest(presented, token):
        raise HTTPException(status_code=401, detail="Invalid or missing API token.")

def _warn_if_unauthenticated() -> None:
    if not _auth_token():
        log.warning(
            "SPENDSLICER_AUTH_TOKEN is not set — server is UNAUTHENTICATED. "
            "Anyone who can reach this port can spend real AWS money via Cost Explorer. "
            "Set SPENDSLICER_AUTH_TOKEN to require a token (X-SpendSlicer-Token header or ?token=...)."
        )


def _kick_prewarm() -> None:
    # get_profile_choices() calls STS (and IAM) once per local AWS profile.
    # Running it inline held the port closed until every profile resolved —
    # ~15s here with five profiles, and far worse with an expired SSO session
    # or a VPN down, where botocore burns its full retry budget per profile.
    # It only warms a cache that base_ctx populates lazily on first request,
    # so a daemon thread keeps the benefit without delaying startup.
    threading.Thread(
        target=_warm_profile_choices,
        daemon=True,
        name="spendslicer-profiles",
    ).start()

    # Disabled by default to avoid large CE/API fan-out on startup.
    # Enable explicitly for kiosk-like deployments.
    if os.environ.get("SPENDSLICER_ENABLE_PREWARM", "0").lower() in ("1", "true", "yes"):
        profiles = get_profiles()
        threading.Thread(
            target=prewarm_background,
            args=(profiles,),
            daemon=True,
            name="spendslicer-prewarm",
        ).start()


def _warm_profile_choices() -> None:
    try:
        get_profile_choices()
    except Exception as exc:
        log.warning("profile warm-up failed: %s", type(exc).__name__, exc_info=True)


def _cur_ingest_worker(stop: threading.Event) -> None:
    interval = float(os.environ.get("SPENDSLICER_CUR_INGEST_INTERVAL_SECONDS", str(6 * 3600)))
    bucket = os.environ.get("SPENDSLICER_CUR_BUCKET")
    prefix = os.environ.get("SPENDSLICER_CUR_PREFIX", "cur/")
    profile = os.environ.get("SPENDSLICER_CUR_PROFILE")
    if not bucket:
        return
    while not stop.is_set():
        db = None
        try:
            import boto3

            from spendslicer.cur.ingestor import CurIngestor
            from spendslicer.cur.schema import connect as cur_connect
            from spendslicer.web.deps import _CACHE_DIR, _CUR_DB_PATH

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
        # Event.wait instead of time.sleep so shutdown doesn't block for hours.
        stop.wait(interval)


def _start_cur_worker(stop: threading.Event) -> threading.Thread | None:
    if not os.environ.get("SPENDSLICER_CUR_BUCKET"):
        return None
    t = threading.Thread(
        target=_cur_ingest_worker,
        args=(stop,),
        daemon=True,
        name="spendslicer-cur-ingest",
    )
    t.start()
    log.info("CUR background ingest worker started (bucket=%s)", os.environ["SPENDSLICER_CUR_BUCKET"])
    return t


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown hooks.

    Replaces the three deprecated ``@app.on_event("startup")`` handlers.
    ``on_event`` is slated for removal in a future Starlette release, and it
    also had no shutdown counterpart here — the CUR ingest thread slept up to
    six hours in ``time.sleep``, so a packaged desktop build could hang on
    quit. The stop Event lets it exit promptly.
    """
    _warn_if_unauthenticated()
    _kick_prewarm()
    stop = threading.Event()
    _start_cur_worker(stop)
    try:
        yield
    finally:
        stop.set()


app = FastAPI(
    title="SpendSlicer",
    description="Self-hosted AWS cost visibility — uses your local AWS CLI profiles.",
    docs_url=None,
    redoc_url=None,
    dependencies=[Depends(require_auth)],
    lifespan=lifespan,
)

app.add_middleware(CECountingMiddleware)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Baseline hardening headers.

    Clickjacking is the one that actually bites here. Without a frame
    directive, any page in the user's browser can iframe the dashboard: the
    frame's origin *is* the dashboard's origin, so same-origin policy does not
    help, and a click the user thinks lands on the attacker's page can trigger
    an export or a Cost Explorer refetch that spends real money. The Origin
    allow-list on POSTs does not cover that, because the framed page is
    same-origin.

    The CSP is deliberately limited to directives that cannot change how the
    page renders. A full script-src/style-src policy is worth adding, but the
    React bundle sets inline styles, so it needs verifying in a real browser
    before it ships rather than being asserted here.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Content-Security-Policy",
        "frame-ancestors 'none'; object-src 'none'; base-uri 'none'",
    )
    return response

app.include_router(pages.router)
app.include_router(cost.router)
app.include_router(resources_api.router)
app.include_router(audit_api.router)
app.include_router(export_api.router)


def serve(host: str = "127.0.0.1", port: int = 8080, reload: bool = False) -> None:
    """Run the dashboard under uvicorn.

    ``reload`` is opt-in: it re-execs the process via a watcher, which breaks
    frozen (PyInstaller) builds outright and is never what a user running the
    launcher wants. Developers get it via ``SPENDSLICER_RELOAD=1``.
    """
    import uvicorn

    if reload:
        # The import-string form is required for reload to work at all.
        uvicorn.run("spendslicer.web.app:app", host=host, port=port, reload=True)
    else:
        uvicorn.run(app, host=host, port=port)


def main() -> None:
    host = os.environ.get("SPENDSLICER_HOST", "127.0.0.1")
    port = int(os.environ.get("SPENDSLICER_PORT", "8080"))
    reload = os.environ.get("SPENDSLICER_RELOAD", "0").lower() in ("1", "true", "yes")
    serve(host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
