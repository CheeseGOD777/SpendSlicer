"""Web UI — FastAPI + Jinja2 + HTMX + Alpine.js + Chart.js.

Run with:
    uvicorn aws_cost_ultra.web.app:app --reload --port 8080

Or via the serve() helper:
    from aws_cost_ultra.web.app import serve
    serve(port=8080, reload=True)
"""

from .app import app, serve

__all__ = ["app", "serve"]
