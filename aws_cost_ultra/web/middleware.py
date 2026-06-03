"""Per-request Cost Explorer call counter exposed as response headers.

A `CECallCounter` is stored in a `contextvars.ContextVar` so each
request has its own counter regardless of which worker thread runs the
handler. `CECountingMiddleware` creates the counter, attaches it to
the request's context, then writes the totals into the response.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


@dataclass
class CECallCounter:
    calls: int = 0
    records: int = 0

    def add(self, pages: int = 0, records: int = 0) -> None:
        self.calls += pages
        self.records += records

    def estimated_usd(self) -> float:
        # $0.01 / request, $0.00001 / UsageRecord
        return self.calls * 0.01 + self.records * 0.00001


_current: contextvars.ContextVar = contextvars.ContextVar("ce_counter", default=None)


def get_current_counter() -> CECallCounter:
    """Return the current request's counter, or a throwaway if outside a request.

    The fallback is intentionally side-effect-free: when called in a pool
    worker with no propagated context we return a throwaway counter WITHOUT
    storing it via ``_current.set``. Setting it would leak orphan counters
    across reused pool threads. Context propagation into workers is handled
    at submit sites via ``contextvars.copy_context().run``.
    """
    c = _current.get()
    if c is None:
        return CECallCounter()
    return c


class CECountingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        counter = CECallCounter()
        token = _current.set(counter)
        try:
            response = await call_next(request)
        finally:
            _current.reset(token)
        response.headers["X-CE-Calls-Spent"] = str(counter.calls)
        response.headers["X-CE-Estimated-Cost-USD"] = f"{counter.estimated_usd():.5f}"
        return response
