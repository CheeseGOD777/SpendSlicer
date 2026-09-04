"""Web UI — FastAPI + Jinja2 + HTMX + Alpine.js + Chart.js.

Run with:
    uvicorn costsight.web.app:app --reload --port 8080

Or via the serve() helper:
    from costsight.web.app import serve
    serve(port=8080, reload=True)
"""

from .app import app, serve

__all__ = ["app", "serve"]
