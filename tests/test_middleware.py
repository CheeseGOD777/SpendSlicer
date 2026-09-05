import pytest

from spendslicer.web.middleware import CECallCounter, get_current_counter


def test_counter_starts_at_zero():
    c = CECallCounter()
    assert c.calls == 0
    assert c.estimated_usd() == 0.0


def test_counter_increment():
    c = CECallCounter()
    c.add(pages=1, records=0)
    c.add(pages=2, records=100)
    assert c.calls == 3
    assert c.estimated_usd() == pytest.approx(0.03 + 100 * 0.00001)


def test_get_current_counter_creates_default_outside_request():
    """When called outside an HTTP request the counter is a throwaway, not None."""
    c = get_current_counter()
    assert isinstance(c, CECallCounter)


def test_counter_records_only_costs_per_record():
    c = CECallCounter()
    c.add(pages=0, records=10)
    assert c.calls == 0
    assert c.estimated_usd() == pytest.approx(10 * 0.00001)


def test_middleware_writes_headers():
    """End-to-end: a route that increments the counter produces the expected headers."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from spendslicer.web.middleware import CECountingMiddleware, get_current_counter

    app = FastAPI()
    app.add_middleware(CECountingMiddleware)

    @app.get("/ping")
    def ping():
        get_current_counter().add(pages=2, records=50)
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/ping")
    assert resp.status_code == 200
    assert resp.headers["X-CE-Calls-Spent"] == "2"
    # 2 * 0.01 + 50 * 0.00001 = 0.0205
    assert float(resp.headers["X-CE-Estimated-Cost-USD"]) == pytest.approx(0.0205)


def test_middleware_isolates_counters_between_requests():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from spendslicer.web.middleware import CECountingMiddleware, get_current_counter

    app = FastAPI()
    app.add_middleware(CECountingMiddleware)

    @app.get("/a")
    def a():
        get_current_counter().add(pages=3)
        return {}

    @app.get("/b")
    def b():
        get_current_counter().add(pages=1)
        return {}

    client = TestClient(app)
    assert client.get("/a").headers["X-CE-Calls-Spent"] == "3"
    assert client.get("/b").headers["X-CE-Calls-Spent"] == "1"
    # Second hit to /a must be 3 again, not 4 — counters must not accumulate
    assert client.get("/a").headers["X-CE-Calls-Spent"] == "3"
