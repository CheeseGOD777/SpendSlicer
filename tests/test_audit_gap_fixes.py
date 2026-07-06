"""Tests for the second-round audit-gap fixes (#13, #14, #15, #21, #24, #41).

These close the gaps the fix-verification review found: profile validation,
constant-time token compare, CSRF hardening, EC2/EBS describe dedup, partial-
attribution surfacing, and the unbounded per-service usage_type list.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# #13 — get_session must validate the profile against the local profile list
# ---------------------------------------------------------------------------

def test_get_session_rejects_unknown_profile(monkeypatch):
    from aws_cost_ultra.web import deps
    monkeypatch.setattr(deps, "list_profiles", lambda: ["prod", "dev"])
    with pytest.raises(HTTPException) as ei:
        deps.get_session("evil; rm -rf /")
    assert ei.value.status_code == 400


def test_get_session_allows_known_and_default(monkeypatch):
    from aws_cost_ultra.web import deps
    monkeypatch.setattr(deps, "list_profiles", lambda: ["prod"])
    # Decouple from the local ~/.aws config: a validated profile whose session
    # builds successfully must pass through unchanged.
    sentinel = object()
    monkeypatch.setattr(deps, "make_session", lambda profile=None: sentinel)
    assert deps.get_session("default") is sentinel
    assert deps.get_session("prod") is sentinel


def test_get_session_does_not_silently_fall_back_to_default(monkeypatch):
    # AUDIT (high): when a *validated* profile's session cannot be built,
    # get_session must NOT silently return boto3.Session() (the default
    # credentials may resolve to a DIFFERENT account, whose costs would then be
    # cached under this profile's keys). It must raise instead.
    from aws_cost_ultra.web import deps

    monkeypatch.setattr(deps, "list_profiles", lambda: ["prod"])

    def _boom(profile=None):
        raise RuntimeError("creds unavailable")

    monkeypatch.setattr(deps, "make_session", _boom)
    with pytest.raises(HTTPException) as ei:
        deps.get_session("prod")
    assert ei.value.status_code == 502


# ---------------------------------------------------------------------------
# Minimal app exercising the real require_auth dependency (avoids heavy
# startup events in aws_cost_ultra.web.app:app).
# ---------------------------------------------------------------------------

def _client():
    from aws_cost_ultra.web.app import require_auth
    app = FastAPI(dependencies=[Depends(require_auth)])

    @app.get("/api/probe")
    def _g():
        return {"ok": True}

    @app.post("/api/probe")
    def _p():
        return {"ok": True}

    return TestClient(app)


# ---------------------------------------------------------------------------
# #14 — token auth behaviour (constant-time compare under the hood)
# ---------------------------------------------------------------------------

def test_token_required_when_configured(monkeypatch):
    monkeypatch.setenv("ACU_AUTH_TOKEN", "s3cret")
    c = _client()
    assert c.get("/api/probe").status_code == 401
    assert c.get("/api/probe", headers={"X-ACU-Token": "wrong"}).status_code == 401
    assert c.get("/api/probe", headers={"X-ACU-Token": "s3cret"}).status_code == 200


def test_no_token_means_open(monkeypatch):
    monkeypatch.delenv("ACU_AUTH_TOKEN", raising=False)
    c = _client()
    assert c.get("/api/probe").status_code == 200


# ---------------------------------------------------------------------------
# #15 — CSRF: state-changing requests need an allowed Origin/Host
# ---------------------------------------------------------------------------

def test_csrf_rejects_cross_origin_post(monkeypatch):
    monkeypatch.delenv("ACU_AUTH_TOKEN", raising=False)
    c = _client()
    r = c.post("/api/probe", headers={"Origin": "http://evil.example", "Host": "localhost"})
    assert r.status_code == 403


def test_csrf_rejects_spoofed_host(monkeypatch):
    # DNS-rebinding style: attacker sets both Host and Origin to their domain.
    monkeypatch.delenv("ACU_AUTH_TOKEN", raising=False)
    c = _client()
    r = c.post("/api/probe", headers={"Origin": "http://evil.example", "Host": "evil.example"})
    assert r.status_code == 403


def test_csrf_rejects_originless_post_when_unauthenticated(monkeypatch):
    # No Origin/Referer AND no token -> must be rejected (was silently allowed).
    monkeypatch.delenv("ACU_AUTH_TOKEN", raising=False)
    c = _client()
    r = c.post("/api/probe", headers={"Host": "localhost"})
    assert r.status_code == 403


def test_csrf_allows_same_origin_localhost_post(monkeypatch):
    monkeypatch.delenv("ACU_AUTH_TOKEN", raising=False)
    c = _client()
    r = c.post("/api/probe", headers={"Origin": "http://localhost:8080", "Host": "localhost:8080"})
    assert r.status_code == 200


def test_csrf_allows_originless_post_with_valid_token(monkeypatch):
    # Authenticated non-browser client (curl with token) may POST without Origin.
    monkeypatch.setenv("ACU_AUTH_TOKEN", "s3cret")
    c = _client()
    r = c.post("/api/probe", headers={"Host": "localhost", "X-ACU-Token": "s3cret"})
    assert r.status_code == 200


def test_get_not_subject_to_csrf(monkeypatch):
    monkeypatch.delenv("ACU_AUTH_TOKEN", raising=False)
    c = _client()
    assert c.get("/api/probe", headers={"Host": "localhost"}).status_code == 200


# ---------------------------------------------------------------------------
# #41 — per-service usage_type list must be capped (top-N + "other" remainder)
# ---------------------------------------------------------------------------

def test_cap_usage_types_limits_and_preserves_total():
    from aws_cost_ultra.web.routes.cost import _cap_usage_types

    usage = {f"USE1-Type{i}": float(i) for i in range(1, 101)}  # 100 distinct types
    rows = _cap_usage_types(usage, cap=10)

    # capped to 10 detail rows + 1 aggregate remainder row
    assert len(rows) == 11
    assert rows[-1]["usage_type"].lower().startswith("other")
    # total cost preserved exactly
    assert round(sum(r["cost"] for r in rows), 6) == round(sum(usage.values()), 6)
    # detail rows are the highest-cost ones, sorted desc
    costs = [r["cost"] for r in rows[:10]]
    assert costs == sorted(costs, reverse=True)
    assert costs[0] == 100.0


def test_cap_usage_types_no_remainder_when_under_cap():
    from aws_cost_ultra.web.routes.cost import _cap_usage_types
    usage = {"A": 3.0, "B": 1.0}
    rows = _cap_usage_types(usage, cap=10)
    assert len(rows) == 2
    assert all(not r["usage_type"].lower().startswith("other") for r in rows)


# ---------------------------------------------------------------------------
# #24 — do not rescale a service whose attribution was incomplete
# ---------------------------------------------------------------------------

def test_rescale_skipped_for_incomplete_service():
    from aws_cost_ultra.resources import runner
    from aws_cost_ultra.resources.base import AttributedResource

    def mk(cost):
        return AttributedResource(
            service="RDS", resource_id="db-1", name="db-1", resource_type="db",
            state="available", cost_usd=cost, hours=0.0, region="us-east-1",
        )

    rows = [mk(10.0), mk(10.0)]
    # complete -> rescales toward ce_tot (factor 2.0, within band)
    runner._rescale_rows(rows, ce_tot=40.0, what="RDS", incomplete=False)
    assert sum(r.cost_usd for r in rows) == pytest.approx(40.0)

    rows2 = [mk(10.0), mk(10.0)]
    # incomplete -> must NOT rescale (partial data would be misattributed up)
    runner._rescale_rows(rows2, ce_tot=40.0, what="RDS", incomplete=True)
    assert sum(r.cost_usd for r in rows2) == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# #21 — EC2's describe scan and EBS's name lookup must share one scan
# ---------------------------------------------------------------------------

def test_live_instance_names_uses_prefetched_instances():
    from aws_cost_ultra.resources import ec2

    class _Boom:
        def get_paginator(self, *a, **k):
            raise AssertionError("describe_instances must not be called when instances are provided")

    prefetched = [
        {"InstanceId": "i-1", "Tags": [{"Key": "Name", "Value": "web"}], "State": {"Name": "running"}},
        {"InstanceId": "i-2", "Tags": [], "State": {"Name": "stopped"}},
    ]
    names = ec2.live_instance_names(_Boom(), "us-east-1", instances=prefetched)
    assert names["i-1"] == "web"
    assert names["i-2"] == "i-2"  # falls back to id
