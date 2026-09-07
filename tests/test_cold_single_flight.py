"""Concurrent cold callers for one key must pay for the producer once.

The Resources tab hits two endpoints that share a cache key: /top/data
schedules a background scan and returns a placeholder, then /data finds the
cache still empty and ran the same scan inline. That billed two full
17-region Cost Explorer enumerations for a single cold page view.
"""

from __future__ import annotations

import threading

from spendslicer.web import deps


def test_concurrent_cold_callers_run_producer_once(monkeypatch):
    store: dict[str, object] = {}
    monkeypatch.setattr(deps, "cache_get", store.get)
    monkeypatch.setattr(deps, "cache_set", lambda k, v, **kw: store.__setitem__(k, v))

    calls = []
    started = threading.Event()

    def producer():
        calls.append(1)
        started.set()
        # Hold the lock long enough that every other thread is queued behind it.
        threading.Event().wait(0.3)
        return "computed"   # cold_single_flight publishes it, inside the lock

    results = []
    threads = [
        threading.Thread(target=lambda: results.append(deps.cold_single_flight("k", producer)))
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(calls) == 1, f"producer ran {len(calls)}x; single-flight is broken"
    assert results == ["computed"] * 8


def test_separate_keys_are_not_serialised(monkeypatch):
    monkeypatch.setattr(deps, "cache_get", lambda _k: None)
    monkeypatch.setattr(deps, "cache_set", lambda *a, **kw: None)
    calls = []
    deps.cold_single_flight("a", lambda: calls.append("a"))
    deps.cold_single_flight("b", lambda: calls.append("b"))
    assert len(calls) == 2
