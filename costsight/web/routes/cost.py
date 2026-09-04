"""Cost Explorer API routes (JSON)."""

from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, timedelta

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from costsight.core.filters import pre_credit_gross
from costsight.core.service_groups import merge_ec2_service_groups, service_rows_from_groups
from costsight.core.time_windows import (
    current_month,
    month_before_last,
    month_window,
    remainder_of_current_month,
)
from costsight.core.types import Granularity, TimeWindow
from costsight.web.context import friendly_error
from costsight.web.deps import (
    cache_get,
    cache_set,
    get_ce_client,
    get_cost_source,
    get_session,
    is_valid_period,
    period_to_window,
)

router = APIRouter(prefix="/api/cost")

# One shared, long-lived pool for the per-request fan-out
# instead of constructing (and tearing down) a ThreadPoolExecutor per request.
# Persistent workers mean the per-thread SQLite connections (and their PRAGMAs)
# are actually reused rather than opened-and-abandoned on every request.
_FANOUT_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="costsight-fanout")


@contextmanager
def _fanout_pool():
    # Yields the shared pool WITHOUT shutting it down on exit; callers still
    # block on each future's .result(), so completion semantics are unchanged.
    yield _FANOUT_POOL

# A specific calendar month period, e.g. "2026-05".
_MONTH_PERIOD_RE = __import__("re").compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def _safe_period(period: str, default: str = "mtd") -> str:
    """Clamp a client-supplied period to the validated allow-list.

    Applied at every route entry so an arbitrary string can neither reach a
    CE call nor inflate the cache-key space (the unbounded-key finding)."""
    return period if is_valid_period(period) else default


def _account_tag(profile: str) -> str:
    """Resolved account id for ``profile`` from the (cached) profile choices.

    Route-level cache keys are namespaced by account, not just profile name:
    if a profile is later repointed to a different AWS account (config edit,
    SSO role change), its stale cached numbers must not be served as the new
    account's. Returns ``"na"`` when the account can't be resolved cheaply."""
    try:
        from costsight.web.context import get_profile_choices
        for c in get_profile_choices():
            if c.get("profile") == profile:
                return c.get("account_id") or "na"
    except Exception:
        pass
    return "na"


def _cache_ctx(ckey: str, ctx: dict) -> None:
    """Persist a built ctx unless it errored or is flagged transient.

    ``_no_cache`` is set by builders when a value (e.g. the forecast) failed
    transiently and should be retried rather than frozen for the whole TTL."""
    if ctx.get("error") is None and not ctx.pop("_no_cache", False):
        cache_set(ckey, ctx)


def _trend_granularity_for_period(period: str) -> Granularity:
    # Daily points for: MTD, short rolling windows, the rolling "3m" (90d)
    # window — which starts mid-month, so MONTHLY would mislabel its truncated
    # first/last buckets as full months — and a single specific calendar month.
    # Longer month-aligned windows (6m/12m) collapse to monthly bars.
    # "90d"/"60d" share last_n_days windows with "3m" and need DAILY for the
    # same reason — MONTHLY rendered their truncated edge buckets as
    # full-month bars ("Apr $2,200" for 22 days of April).
    if period in ("mtd", "30d", "60d", "90d", "3m", "last_month") or _MONTH_PERIOD_RE.match(period or ""):
        return Granularity.DAILY
    return Granularity.MONTHLY


def _window_days(window: TimeWindow) -> int:
    """Whole-day span of a window using its CE-rounded iso() date strings.

    Computed from iso() (not raw timestamps) so the count is stable across the
    UTC day — a window's end is ``now`` but iso() rounds it up to the next
    midnight, so a raw end-minus-start would vary with request time.
    """
    s_iso, e_iso = window.iso()
    return (date.fromisoformat(e_iso) - date.fromisoformat(s_iso)).days


def _prev_window(period: str, window: TimeWindow) -> TimeWindow:
    """Window to compare the current ``window`` against.

    - ``mtd``: the *same day-of-month slice* of the previous calendar month
      (e.g. on the 6th, compare against the 1st–6th of last month), matching
      the AWS console — not the full previous month, which made change_pct
      structurally negative for most of the month.
    - ``last_month`` / specific ``YYYY-MM``: the previous full calendar month
      (month lengths differ, so a duration shift would land mid-month).
    - rolling windows: the immediately-preceding window of the same whole-day
      duration, computed in whole days so it doesn't drift with request time.
    """
    if period == "mtd":
        prev_first = (window.start - timedelta(days=1)).replace(day=1)
        days = _window_days(window)
        end = prev_first + timedelta(days=days)
        # Don't spill past the end of the previous month.
        this_first = window.start
        if end > this_first:
            end = this_first
        return TimeWindow(start=prev_first, end=end)
    if period == "last_month":
        return month_before_last()
    m = _MONTH_PERIOD_RE.match(period or "")
    if m:
        # Previous calendar month relative to the selected month's 1st.
        prev_first = (window.start - timedelta(days=1)).replace(day=1)
        return month_window(prev_first.year, prev_first.month)
    n = _window_days(window)
    return TimeWindow(start=window.start - timedelta(days=n), end=window.start)


def _build_summary_ctx(profile: str, period: str) -> dict:
    ctx: dict = {
        "error": None,
        "total_mtd": None,
        "total_prev": None,
        "change_pct": None,
        "forecast": None,
        "top_service_name": None,
        "top_service_cost": None,
        "period": period,
        "cost_basis_label": "Pre-credit · excludes Credit/Refund · UTC",
    }
    period = _safe_period(period)
    ctx["period"] = period
    try:
        session = get_session(profile)
        ce = get_ce_client(session)
        spec = pre_credit_gross()

        # account_id is required as the cache namespace so two profiles
        # pointing at different accounts don't share matrix entries.
        account_id = session.client("sts").get_caller_identity()["Account"]

        window = period_to_window(period)
        prev_window = _prev_window(period, window)

        # A forecast ("projected end-of-month spend") only makes sense for a
        # window that reaches into the current month. For a specific historical
        # month (e.g. viewing April while it's June) there is nothing to
        # forecast, so skip the forecast + this-month matrix calls entirely.
        is_specific_month = bool(_MONTH_PERIOD_RE.match(period))
        fcast_window = None if is_specific_month else remainder_of_current_month()
        want_forecast = fcast_window is not None
        # On the last day of the month there is no remainder to forecast; the
        # "projected month close" is simply the MTD actual — still fetch the
        # MTD matrix so the card doesn't go blank.
        is_month_last_day = not is_specific_month and fcast_window is None
        mtd_window = window if period == "mtd" else current_month()

        src = get_cost_source(session)

        # Parallelism is preserved — but everything is cached so cold cost
        # is at most 3 CE calls (window, prev, optional mtd) + 1 forecast.
        # Each submit runs inside a copied context so the CE call-counter
        # ContextVar set by middleware propagates into the worker threads.
        with _fanout_pool() as pool:
            f_matrix = pool.submit(
                contextvars.copy_context().run, src.get_matrix, profile, account_id, window, spec
            )
            f_prev_matrix = pool.submit(
                contextvars.copy_context().run, src.get_matrix, profile, account_id, prev_window, spec
            )
            f_forecast = (
                pool.submit(
                    contextvars.copy_context().run, lambda: ce.get_forecast(fcast_window, spec=spec)
                )
                if want_forecast else None
            )
            f_mtd_matrix = (
                pool.submit(
                    contextvars.copy_context().run, src.get_matrix, profile, account_id, mtd_window, spec
                )
                if (want_forecast or is_month_last_day) and period != "mtd" else None
            )

        m = f_matrix.result()
        prev_m = f_prev_matrix.result()
        # Distinguish a forecast that is *legitimately* unavailable (CE returns
        # None — e.g. too little history) from a *transient* failure (throttle/
        # timeout, surfaced as a raised exception). The former is cacheable; the
        # latter must NOT be cached, or one throttled call blanks the forecast
        # card for every viewer for the whole TTL.
        forecast_cv = None
        if f_forecast:
            try:
                forecast_cv = f_forecast.result()
            except Exception:
                forecast_cv = None
                ctx["_no_cache"] = True
        mtd_m = f_mtd_matrix.result() if f_mtd_matrix else m

        # Build a synthetic provenance label for the merged services list.
        # The matrix already carries no per-cell provenance; use a coarse one.
        from costsight.core.provenance import Provenance
        from costsight.core.types import CostMetric
        prov = Provenance(
            source="cost_explorer",
            metric=CostMetric.UNBLENDED,
            window=window,
            timezone_str="UTC",
            excluded_record_types=tuple(spec.excluded_record_types) if spec.excluded_record_types else None,
            included_record_types=tuple(spec.included_record_types) if spec.included_record_types else None,
            group_by=("SERVICE",),
            filter_summary=spec.summary(),
        )
        services = merge_ec2_service_groups(m.to_grouped_cost_list(prov))

        total_amount = m.total()
        prev_amount = prev_m.total()
        mtd_amount = mtd_m.total()

        ctx["total_mtd"] = total_amount
        ctx["total_prev"] = prev_amount
        if prev_amount >= 0.50:
            raw = (total_amount - prev_amount) / prev_amount * 100
            ctx["change_pct"] = max(-999.9, min(9999.9, raw))
        if forecast_cv:
            ctx["forecast"] = mtd_amount + forecast_cv.amount_usd
            ctx["forecast_mtd_actual"] = mtd_amount
        elif is_month_last_day:
            # Nothing left to forecast — the month closes today at the actual.
            ctx["forecast"] = mtd_amount
            ctx["forecast_mtd_actual"] = mtd_amount
        if services:
            ctx["top_service_name"] = services[0].primary_key()
            ctx["top_service_cost"] = services[0].value.amount_usd
            ctx["top_service_provenance"] = services[0].value.provenance.label()
    except Exception as exc:
        ctx["error"] = friendly_error(exc)
    return ctx


def _build_services_ctx(profile: str, period: str, limit: int) -> dict:
    ctx: dict = {"error": None, "services": [], "total": 0.0, "cost_basis_label": ""}
    period = _safe_period(period)
    try:
        session = get_session(profile)
        spec = pre_credit_gross()
        account_id = session.client("sts").get_caller_identity()["Account"]
        window = period_to_window(period)
        prev_window = _prev_window(period, window)

        src = get_cost_source(session)

        # Copy the context into each worker so the CE call-counter ContextVar
        # set by middleware reaches the pool threads (see X-CE-Calls-Spent).
        with _fanout_pool() as pool:
            f_matrix = pool.submit(
                contextvars.copy_context().run, src.get_matrix, profile, account_id, window, spec
            )
            f_prev = pool.submit(
                contextvars.copy_context().run, src.get_matrix, profile, account_id, prev_window, spec
            )

        m = f_matrix.result()
        prev_m = f_prev.result()

        from costsight.core.provenance import Provenance
        from costsight.core.types import CostMetric
        prov = Provenance(
            source="cost_explorer",
            metric=CostMetric.UNBLENDED,
            window=window,
            timezone_str="UTC",
            excluded_record_types=tuple(spec.excluded_record_types) if spec.excluded_record_types else None,
            included_record_types=tuple(spec.included_record_types) if spec.included_record_types else None,
            group_by=("SERVICE",),
            filter_summary=spec.summary(),
        )

        groups = merge_ec2_service_groups(m.to_grouped_cost_list(prov))
        # Build prev_map from the *merged* prev groups too: the current groups
        # rename CE's split EC2 rows ("- Compute" / "- Other") into a single
        # "Amazon Elastic Compute Cloud" line, so a prev_map keyed by raw CE
        # names would always miss the merged EC2 row and report its previous
        # spend (and change %) as $0 — for what is usually the largest line item.
        prev_groups = merge_ec2_service_groups(prev_m.to_grouped_cost_list(prov))
        prev_map = {g.primary_key(): g.value.amount_usd for g in prev_groups}

        effective_limit = limit if limit > 0 else None
        services, total = service_rows_from_groups(groups, prev_map, limit=effective_limit)
        ctx["services"] = services
        ctx["total"] = total
        ctx["cost_basis_label"] = spec.summary() or "Pre-credit gross usage"
    except Exception as exc:
        ctx["error"] = friendly_error(exc)
    return ctx


@router.get("/summary/data")
def api_cost_summary_data(
    profile: str = Query("default"),
    period: str = Query("mtd"),
):
    period = _safe_period(period)
    ckey = f"summary_json:{_account_tag(profile)}:{profile}:{period}"
    cached = cache_get(ckey)
    if cached:
        return JSONResponse(cached)
    ctx = _build_summary_ctx(profile, period)
    _cache_ctx(ckey, ctx)
    return JSONResponse(ctx)


@router.get("/services/data")
def api_cost_services_data(
    profile: str = Query("default"),
    period: str = Query("mtd"),
    limit: int = Query(0),
):
    period = _safe_period(period)
    ckey = f"services_json:{_account_tag(profile)}:{profile}:{period}:{limit}"
    cached = cache_get(ckey)
    if cached:
        return JSONResponse(cached)
    ctx = _build_services_ctx(profile, period, limit)
    _cache_ctx(ckey, ctx)
    return JSONResponse(ctx)


# ---------------------------------------------------------------------------
# Service composition (USAGE_TYPE bucketing) — what's actually driving each
# service's spend: compute vs storage vs data-transfer vs network vs other.
# Single CE call (SERVICE × USAGE_TYPE) covers every service in the window.
# ---------------------------------------------------------------------------

_COMPOSITION_BUCKETS = ("compute", "storage", "data-transfer", "network", "other")
_EC2_MERGED_NAME = "Amazon Elastic Compute Cloud"
_EC2_RAW_NAMES = frozenset({
    "Amazon Elastic Compute Cloud - Compute",
    "EC2 - Other",
})


def _bucket_for_usage_type(usage_type: str) -> str:
    ut = usage_type or ""
    if "DataTransfer" in ut:
        return "data-transfer"
    network_markers = (
        "NatGateway", "LoadBalancer", "LCU", "ElasticIP", "PublicIPv4",
        "VPN", "VpcEndpoint", "TransitGateway", "DirectConnect",
    )
    if any(m in ut for m in network_markers):
        return "network"
    storage_markers = (
        "Storage", "EBS:", "Snapshot", "Piops", "IOUsage",
        "ByteHrs", "TimedStorage",
    )
    if any(m in ut for m in storage_markers):
        return "storage"
    compute_markers = (
        "BoxUsage", "SpotUsage", "HeavyUsage", "DedicatedUsage",
        "InstanceUsage", "Lambda-GB-Second", "Lambda-Edge",
        "Multi-AZ", "ServerlessUsage", "GB-Hours",
        "Fargate", "vCPU", "NodeUsage", "CPUCredits",
    )
    if any(m in ut for m in compute_markers):
        return "compute"
    return "other"


# USAGE_TYPE cardinality is regional (e.g. "USE1-BoxUsage:m5.large",
# "APN1-BoxUsage:m5.large", ...), so a single service on a many-region account can
# carry thousands of distinct types. Cap the serialized detail list to the top-N by
# cost and roll the long tail into one "other" row so the cached JSON stays bounded
# while the displayed total still reconciles.
_USAGE_TYPES_PER_SERVICE_CAP = 50


def _cap_usage_types(usage_map: dict[str, float], cap: int = _USAGE_TYPES_PER_SERVICE_CAP) -> list[dict]:
    rows = sorted(
        (
            {"usage_type": ut, "bucket": _bucket_for_usage_type(ut), "cost": round(cost, 4)}
            for ut, cost in usage_map.items()
        ),
        key=lambda r: r["cost"],
        reverse=True,
    )
    if cap is not None and cap >= 0 and len(rows) > cap:
        head = rows[:cap]
        tail = rows[cap:]
        head.append({
            "usage_type": f"other ({len(tail)} types)",
            "bucket": "other",
            "cost": round(sum(r["cost"] for r in tail), 4),
        })
        rows = head
    return rows


def _build_services_composition_ctx(profile: str, period: str) -> dict:
    ctx: dict = {"error": None, "services": {}, "cost_basis_label": ""}
    period = _safe_period(period)
    try:
        session = get_session(profile)
        ce = get_ce_client(session)
        spec = pre_credit_gross()
        window = period_to_window(period)
        groups = ce.get_cost_by_service_and_usage_type(window, spec=spec)

        # Per service: broad-bucket totals (the at-a-glance bar) AND the exact
        # USAGE_TYPE detail (so "other" is never a black box). Both come from
        # the single SERVICE × USAGE_TYPE call above — no extra CE budget.
        buckets_by_svc: dict[str, dict] = {}
        usage_by_svc: dict[str, dict[str, float]] = {}
        for g in groups:
            if len(g.key) < 2:
                continue
            svc, ut = g.key[0], g.key[1]
            amount = g.value.amount_usd
            if svc in _EC2_RAW_NAMES:
                svc = _EC2_MERGED_NAME
            bucket = _bucket_for_usage_type(ut)
            entry = buckets_by_svc.setdefault(svc, {b: 0.0 for b in _COMPOSITION_BUCKETS})
            entry[bucket] += amount
            # USAGE_TYPE strings are unique per (service, type); a service can
            # repeat one across regions, so accumulate rather than overwrite.
            uts = usage_by_svc.setdefault(svc, {})
            uts[ut] = uts.get(ut, 0.0) + amount

        ctx["services"] = {
            svc: {
                **buckets,
                "total": sum(buckets.values()),
                "usage_types": _cap_usage_types(usage_by_svc.get(svc, {})),
            }
            for svc, buckets in buckets_by_svc.items()
        }
        ctx["buckets"] = list(_COMPOSITION_BUCKETS)
        ctx["cost_basis_label"] = spec.summary() or "Pre-credit gross usage"
    except Exception as exc:
        ctx["error"] = friendly_error(exc)
    return ctx


@router.get("/services/composition/data")
def api_cost_services_composition_data(
    profile: str = Query("default"),
    period: str = Query("mtd"),
):
    period = _safe_period(period)
    ckey = f"services_composition_json:{_account_tag(profile)}:{profile}:{period}"
    cached = cache_get(ckey)
    if cached:
        return JSONResponse(cached)
    ctx = _build_services_composition_ctx(profile, period)
    _cache_ctx(ckey, ctx)
    return JSONResponse(ctx)


@router.get("/trend/data")
def api_trend_data(profile: str = Query("default"), period: str = Query("3m")):
    period = _safe_period(period, default="3m")
    gran = _trend_granularity_for_period(period)
    ckey = f"trend_data:{_account_tag(profile)}:{profile}:{period}:{gran.value}"
    cached = cache_get(ckey)
    if cached:
        return JSONResponse(cached)
    try:
        session = get_session(profile)
        ce = get_ce_client(session)
        spec = pre_credit_gross()
        window = period_to_window(period)
        points = ce.get_trend(window, granularity=gran, spec=spec)
        labels = [p.period_start[:10] for p in points] if gran == Granularity.DAILY else [p.period_start[:7] for p in points]
        data = {
            "labels": labels,
            "values": [round(p.value.amount_usd, 3) for p in points],
        }
        cache_set(ckey, data)
        return JSONResponse(data)
    except Exception as exc:
        return JSONResponse({"error": friendly_error(exc), "labels": [], "values": []})


@router.get("/trend-table/data")
def api_trend_table_data(
    profile: str = Query("default"),
    period: str = Query("3m"),
):
    period = _safe_period(period, default="3m")
    gran = _trend_granularity_for_period(period)
    ckey = f"trend_table_json:{_account_tag(profile)}:{profile}:{period}:{gran.value}"
    cached = cache_get(ckey)
    if cached:
        return JSONResponse(cached)

    ctx: dict = {
        "error": None,
        "points": [],
        "max_cost": 0.0,
        "cost_basis_label": "Pre-credit · excludes Credit/Refund · UTC",
    }
    try:
        session = get_session(profile)
        ce = get_ce_client(session)
        window = period_to_window(period)
        raw = ce.get_trend(window, granularity=gran, spec=pre_credit_gross())
        period_fmt = (lambda p: p.period_start[:10]) if gran == Granularity.DAILY else (lambda p: p.period_start[:7])
        points = [{"period": period_fmt(p), "cost": p.value.amount_usd} for p in reversed(raw)]
        ctx["points"] = points
        ctx["max_cost"] = max((p["cost"] for p in points), default=0.0)
    except Exception as exc:
        ctx["error"] = friendly_error(exc)
    if ctx.get("error") is None:
        cache_set(ckey, ctx)
    return JSONResponse(ctx)


