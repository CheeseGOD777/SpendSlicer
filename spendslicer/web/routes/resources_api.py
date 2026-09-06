"""Per-resource attribution API routes."""

from __future__ import annotations

import re as _re

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from spendslicer.core.filters import pre_credit_gross
from spendslicer.resources import enumerate_all
from spendslicer.resources.runner import ALL_REGIONS
from spendslicer.web.context import friendly_error
from spendslicer.web.deps import (
    cache_get,
    cache_get_swr,
    cache_set,
    get_ce_client,
    get_cost_source,
    get_session,
    is_valid_period,
    period_to_window,
    schedule_refresh,
)

router = APIRouter(prefix="/api/resources")

# AWS region code shape, or the ALL_REGIONS sentinel. Clamp unknown values so a
# client-supplied region can't mint unbounded cache keys.
_REGION_RE = _re.compile(r"^[a-z]{2}-[a-z]+-\d{1,2}$")


def _safe_region(region: str) -> str:
    return region if (region == ALL_REGIONS or _REGION_RE.match(region or "")) else ALL_REGIONS


def _safe_period(period: str) -> str:
    return period if is_valid_period(period) else "mtd"

# Hard server-side caps on the number of per-resource rows returned to the
# browser. Even when a caller requests an unbounded list (limit <= 0) we never
# materialize/serialize the entire account resource list into the response.
_DEFAULT_ROW_CAP = 500   # used when limit <= 0
_MAX_ROW_CAP = 2000      # absolute ceiling, even when limit > 0


def _apply_row_cap(rows: list, limit: int) -> list:
    """Sort rows by cost desc and apply the bounded cap.

    - limit <= 0  -> cap at _DEFAULT_ROW_CAP (never unbounded)
    - limit  > 0  -> honor limit but ceiling at _MAX_ROW_CAP
    """
    effective = _DEFAULT_ROW_CAP if limit <= 0 else min(limit, _MAX_ROW_CAP)
    return sorted(rows, key=lambda r: r.get("cost", 0.0), reverse=True)[:effective]


def _normalize_cur_row(r: dict) -> dict:
    """Pad a CUR-sourced resource dict to match the shape of AttributedResource.to_dict()."""
    return {
        "service": r.get("service", ""),
        "resource_id": r.get("resource_id", ""),
        "name": r.get("name", r.get("resource_id", "")),
        "type": "",
        "state": "",
        "cost": r.get("cost", 0.0),
        "hours": 0.0,
        "region": "",
        "waste_reason": None,
        "attributes": {},
        "tags": r.get("tags", {}),
    }


def build_resources_ctx(profile: str, period: str, region: str) -> dict:
    # Clamp here too (not just in the cache key) so an invalid region/period
    # can't drive a failing enumeration whose error then gets cached under the
    # clamped key, poisoning legitimate requests.
    region = _safe_region(region)
    period = _safe_period(period)
    ctx: dict = {
        "error": None,
        "rows": [],
        "total": 0.0,
        "ce_total": 0.0,
        "unattributed": 0.0,
        "region": region,
        "region_label": "All opted-in regions" if region == ALL_REGIONS else region,
        "service": "",
        "services_summary": [],
        "attribution_source": "estimated",
        "cost_basis_label": "Pre-credit · CE ground truth",
        "incomplete": False,
        "warnings": [],
    }
    try:
        session = get_session(profile)
        spec = pre_credit_gross()
        window = period_to_window(period)

        # Collect per-service attribution failures so we can warn the
        # user that results may be incomplete instead of silently showing low totals.
        attr_errors: list[dict] = []

        # Try CostSource path: CUR when available, describe-based fallback otherwise.
        try:
            account_id = session.client("sts").get_caller_identity()["Account"]
            src = get_cost_source(session)
            # CostSource handles CUR-first / CE-describe fallback internally.
            # Both paths return the same simplified dict shape, so always normalize.
            raw_rows = src.attribute_resources(
                account_id, window, session=session, spec=spec,
                errors=attr_errors, region=region,
            )
            ctx["rows"] = [_normalize_cur_row(r) for r in raw_rows]
            ctx["attribution_source"] = src.attribution_source(
                account_id, window, region=region
            )
        except Exception:
            # Any error in CostSource wiring falls back to existing describe path.
            rows = enumerate_all(session, window, region=region, spec=spec, errors=attr_errors)
            ctx["rows"] = [r.to_dict() for r in rows]
            ctx["attribution_source"] = "estimated"

        if attr_errors:
            ctx["incomplete"] = True
            failed = sorted({e.get("service", "?") for e in attr_errors})
            ctx["warnings"] = [
                f"Attribution incomplete — {', '.join(failed)} failed after retries; "
                "shown costs for those services may be understated."
            ]

        ctx["total"] = sum(r["cost"] for r in ctx["rows"])

        svc_totals: dict[str, float] = {}
        svc_counts: dict[str, int] = {}
        for r in ctx["rows"]:
            svc_totals[r["service"]] = svc_totals.get(r["service"], 0.0) + r["cost"]
            svc_counts[r["service"]] = svc_counts.get(r["service"], 0) + 1
        ctx["services_summary"] = sorted(
            [
                {"service": s, "total": t, "count": svc_counts[s]}
                for s, t in svc_totals.items() if t > 0.001
            ],
            key=lambda e: e["total"],
            reverse=True,
        )

        ce = get_ce_client(session)
        # Reconcile like-for-like: a region-filtered view must compare against
        # the REGION-scoped CE total, not the account-wide one (which reported
        # the rest of the world as "unattributed").
        totals_spec = spec
        if region != ALL_REGIONS:
            from dataclasses import replace as _dc_replace
            totals_spec = _dc_replace(spec, region=region)
        ce_total_cv = ce.get_total_cost(window, spec=totals_spec)
        ctx["ce_total"] = ce_total_cv.amount_usd
        # Drift may legitimately go NEGATIVE (attributed > CE total, e.g. an
        # attribution double count or a basis mismatch) — flooring at zero hid
        # exactly the failures this reconciliation exists to expose.
        ctx["unattributed"] = ctx["ce_total"] - ctx["total"]
        if ctx["unattributed"] < -0.01:
            ctx["warnings"].append(
                "Attributed total exceeds the CE total — some cost may be "
                "double-counted between per-resource rows and aggregates."
            )
        ctx["unattributed_pct"] = (
            ctx["unattributed"] / ctx["ce_total"] * 100 if ctx["ce_total"] > 0 else 0.0
        )

        # Cap the row list BEFORE caching (totals/services_summary
        # above are already computed from the full set). Otherwise the cached
        # blob — and every per-request dict() copy + re-sort — grows unbounded
        # with account size, even though the response only ever serves
        # <= _MAX_ROW_CAP rows. Keep the top rows by cost; collapse the tail
        # into one aggregate row so the displayed total still reconciles.
        all_rows = sorted(ctx["rows"], key=lambda r: r.get("cost", 0.0), reverse=True)
        if len(all_rows) > _MAX_ROW_CAP:
            head = all_rows[:_MAX_ROW_CAP]
            tail = all_rows[_MAX_ROW_CAP:]
            tail_cost = sum(r.get("cost", 0.0) for r in tail)
            head.append({
                "resource_id": "aggregate:other-resources",
                "name": f"{len(tail)} more resources",
                "service": "Other",
                "tags": {},
                "cost": round(tail_cost, 4),
                "usage_amount": None,
                "aggregate": True,
            })
            ctx["rows"] = head
        else:
            ctx["rows"] = all_rows
    except Exception as exc:
        ctx["error"] = friendly_error(exc)
    return ctx


@router.get("/data")
def api_resources_data(
    profile: str = Query("default"),
    period: str = Query("mtd"),
    region: str = Query(ALL_REGIONS),
    service: str = Query(""),
    limit: int = Query(0),
):
    ckey = f"resources:{profile}:{_safe_period(period)}:{_safe_region(region)}"
    cached, should_refresh = cache_get_swr(ckey)
    if cached is None:
        cached = build_resources_ctx(profile, period, region)
        if cached.get("error") is None:
            cache_set(ckey, cached)
    elif should_refresh:
        schedule_refresh(ckey, lambda: build_resources_ctx(profile, period, region), heavy=True)

    ctx = dict(cached)
    rows = list(ctx.get("rows", []))
    if service:
        rows = [r for r in rows if r.get("service") == service]
    total_count = len(rows)
    rows = _apply_row_cap(rows, limit)
    ctx["service"] = service
    # Total matching rows before the server-side cap, so the UI can render
    # "showing N of M" without ever receiving the full unbounded list.
    ctx["total_count"] = total_count
    ctx["rows"] = rows
    return JSONResponse(ctx)


@router.get("/top/data")
def api_resources_top_data(
    profile: str = Query("default"),
    period: str = Query("mtd"),
    region: str = Query(ALL_REGIONS),
    limit: int = Query(10),
):
    # Fast path for dashboard: never block first paint on full attribution scan.
    ckey = f"resources:{profile}:{_safe_period(period)}:{_safe_region(region)}"
    cached, should_refresh = cache_get_swr(ckey)
    if cached is None:
        schedule_refresh(ckey, lambda: build_resources_ctx(profile, period, region), heavy=True)
        return JSONResponse({
            "error": None,
            "rows": [],
            "service": "",
            "services_summary": [],
            "total": 0.0,
            "ce_total": 0.0,
            "unattributed": 0.0,
            "unattributed_pct": 0.0,
            "warming": True,
            "attribution_source": "estimated",
            "region": region,
            "region_label": "All opted-in regions" if region == ALL_REGIONS else region,
            "cost_basis_label": "Pre-credit · CE ground truth",
        })
    if should_refresh:
        schedule_refresh(ckey, lambda: build_resources_ctx(profile, period, region), heavy=True)

    # "Top resources" means actionable per-resource rows — synthetic
    # aggregates (long-tail rollup, service remainders, CE service totals)
    # would otherwise crowd out (or outrank) every real resource.
    _synthetic = ("aggregate:", "other:", "ce:", "ce-remainder:", "ce-usage:")
    real_rows = [
        r for r in cached.get("rows", [])
        if not str(r.get("resource_id", "")).startswith(_synthetic)
    ]
    rows = sorted(real_rows, key=lambda r: r.get("cost", 0.0), reverse=True)[:limit]
    ctx = dict(cached)
    ctx["service"] = ""
    ctx["rows"] = rows
    ctx["warming"] = False
    return JSONResponse(ctx)


@router.get("/services/data")
def api_resources_services_data(
    profile: str = Query("default"),
    period: str = Query("mtd"),
    region: str = Query(ALL_REGIONS),
):
    ckey = f"resources:{profile}:{_safe_period(period)}:{_safe_region(region)}"
    cached = cache_get(ckey)
    if not cached:
        cached = build_resources_ctx(profile, period, region)
        if cached.get("error") is None:
            cache_set(ckey, cached)
    return JSONResponse({
        "services_summary": cached.get("services_summary", []),
        "profile": profile,
        "period": period,
        "region": region,
    })
