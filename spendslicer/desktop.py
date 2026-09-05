"""Native desktop shell for the SpendSlicer dashboard.

Starts the FastAPI app on a loopback port in a background thread, then opens
the dashboard in the operating system's own webview — WebKit on macOS,
WebView2 on Windows. This is what the .dmg and .exe builds run.

Design notes
------------
*In-process server, not a subprocess.* A frozen PyInstaller binary re-executes
itself for any child process, so spawning a server subprocess would need
``multiprocessing.freeze_support`` plus argv sentinels to avoid a fork bomb. A
daemon thread running ``uvicorn.Server.run`` avoids that entirely.

*Ephemeral port.* Binding a fixed 8080 collides with anything already there —
including a second copy of SpendSlicer. We ask the OS for a free port and hand
that to uvicorn.

*Per-run auth token.* The server is loopback-only, but its CSRF check covers
only state-changing methods; a page in the user's browser could otherwise fire
cross-origin GETs at the port and spend real Cost Explorer money. So each run
mints a random token, exports it as SPENDSLICER_AUTH_TOKEN before the app is
imported, and passes it to the webview once via the URL.

*Browser fallback.* If pywebview is missing or no native webview is available
(a bare Linux container, an ancient Windows without WebView2), fall back to the
default browser rather than dying.
"""

from __future__ import annotations

import contextlib
import logging
import os
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

WINDOW_TITLE = "SpendSlicer"
_STARTUP_TIMEOUT_SECONDS = 45.0


def _storage_path() -> Path:
    """Where the webview keeps localStorage/cookies between runs."""
    base = os.environ.get("SPENDSLICER_CACHE_DIR")
    root = Path(base) if base else Path.home() / ".cache" / "spendslicer"
    return root / "webview"


def _free_port() -> int:
    """Ask the OS for an unused loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_until_serving(url: str, token: str, timeout: float) -> bool:
    """Poll until the server answers, or the timeout expires."""
    deadline = time.monotonic() + timeout
    request = urllib.request.Request(url, headers={"X-SpendSlicer-Token": token})
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=2) as resp:  # noqa: S310
                if resp.status < 500:
                    return True
        except urllib.error.HTTPError as exc:
            # Any HTTP status means the app is up and routing.
            if exc.code < 500:
                return True
        except (urllib.error.URLError, OSError, ConnectionError):
            pass  # not listening yet
        time.sleep(0.15)
    return False


def _start_server(host: str, port: int) -> threading.Thread:
    """Run uvicorn in a daemon thread and return it."""
    import uvicorn

    from spendslicer.web.app import app

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=os.environ.get("SPENDSLICER_LOG_LEVEL", "warning"),
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="spendslicer-server")
    thread.start()
    return thread


def _open_window(url: str) -> bool:
    """Open the native webview. False if no webview backend is usable."""
    try:
        import webview
    except ImportError:
        log.warning("pywebview is not installed — falling back to the browser.")
        return False

    try:
        webview.create_window(
            WINDOW_TITLE,
            url,
            width=1440,
            height=940,
            min_size=(1024, 700),
            confirm_close=False,
        )
        # private_mode=True (pywebview's default) throws away localStorage on
        # every quit, which would drop the dashboard's stale-while-revalidate
        # cache and force a full Cost Explorer refetch — real money — on each
        # launch. Persist it under the same cache dir the backend uses.
        storage = _storage_path()
        storage.mkdir(parents=True, exist_ok=True)
        # Blocks until the user closes the window.
        webview.start(private_mode=False, storage_path=str(storage))
        return True
    except Exception as exc:
        log.warning("Native webview unavailable (%s) — falling back to the browser.", exc)
        return False


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("SPENDSLICER_LOG_LEVEL", "WARNING").upper(),
        format="%(levelname)s %(name)s: %(message)s",
    )

    host = "127.0.0.1"
    port = int(os.environ.get("SPENDSLICER_PORT") or 0) or _free_port()

    # Must be set before spendslicer.web.app is imported: the app reads the token
    # at request time, but starting clean avoids any import-order surprise.
    token = os.environ.get("SPENDSLICER_AUTH_TOKEN") or secrets.token_urlsafe(32)
    os.environ["SPENDSLICER_AUTH_TOKEN"] = token

    _start_server(host, port)

    base = f"http://{host}:{port}"
    if not _wait_until_serving(f"{base}/app", token, _STARTUP_TIMEOUT_SECONDS):
        sys.stderr.write(
            f"SpendSlicer: the local server did not start within "
            f"{_STARTUP_TIMEOUT_SECONDS:.0f}s.\n"
        )
        return 1

    app_url = f"{base}/app?token={token}"

    if not _open_window(app_url):
        import webbrowser

        webbrowser.open(app_url)
        print(f"SpendSlicer is running at {base}/app")
        print("Close this window (or press Ctrl+C) to stop the server.")
        with contextlib.suppress(KeyboardInterrupt):
            threading.Event().wait()

    return 0


if __name__ == "__main__":
    sys.exit(main())
