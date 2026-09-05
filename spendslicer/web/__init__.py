"""Web UI — FastAPI backend serving a prebuilt React single-page app.

Run with:
    uvicorn spendslicer.web.app:app --port 8080

Or via the helpers:
    from spendslicer.web.app import serve
    serve(port=8080)
"""

from .app import app, main, serve

__all__ = ["app", "main", "serve"]
