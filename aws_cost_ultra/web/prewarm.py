"""Startup cache pre-warm — populate common views before first click."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from aws_cost_ultra.core.filters import pre_credit_gross
from aws_cost_ultra.core.service_groups import merge_ec2_service_groups, service_rows_from_groups
from aws_cost_ultra.core.time_windows import remainder_of_current_month
from aws_cost_ultra.core.types import Granularity
from aws_cost_ultra.resources import enumerate_all
from aws_cost_ultra.resources.runner import ALL_REGIONS
from aws_cost_ultra.web.deps import cache_set, get_ce_client, get_session, period_to_window
from aws_cost_ultra.web.routes.audit_api import build_audit_ctx
from aws_cost_ultra.web.routes.resources_api import build_resources_ctx

log = logging.getLogger("aws_cost_ultra.prewarm")


def prewarm_background(profiles: list[str]) -> None:
    from aws_cost_ultra.core.time_windows import current_month

    for profile in profiles:
        try:
            session = get_session(profile)
            ce = get_ce_client(session)
            spec = pre_credit_gross()

            try:
                session.client("sts").get_caller_identity()
            except Exception as exc:
                log.info("skip prewarm %s: %s", profile, type(exc).__name__)
                continue

            window = period_to_window("mtd")
            prev_window = period_to_window("last_month")
            fcast_window = remainder_of_current_month()

            with ThreadPoolExecutor(max_workers=4) as pool:
                f_total = pool.submit(ce.get_total_cost, window, spec=spec)
                f_prev = pool.submit(ce.get_total_cost, prev_window, spec=spec)
                f_services = pool.submit(ce.get_cost_by_service, window, spec=spec)
                f_forecast = pool.submit(ce.get_forecast, fcast_window, spec=spec)

            total_cv = f_total.result()
            prev_cv = f_prev.result()
            services = merge_ec2_service_groups(f_services.result())
            forecast_cv = f_forecast.result()

            summary_ctx = {
                "error": None,
                "total_mtd": total_cv.amount_usd,
                "total_prev": prev_cv.amount_usd,
                "change_pct": None,
                "forecast": None,
                "top_service_name": services[0].primary_key() if services else None,
                "top_service_cost": services[0].value.amount_usd if services else None,
                "period": "mtd",
                "cost_basis_label": "Pre-credit · excludes Credit/Refund · UTC",
            }
            if prev_cv.amount_usd >= 0.50:
                raw = (total_cv.amount_usd - prev_cv.amount_usd) / prev_cv.amount_usd * 100
                summary_ctx["change_pct"] = max(-999.9, min(9999.9, raw))
            if forecast_cv:
                summary_ctx["forecast"] = total_cv.amount_usd + forecast_cv.amount_usd
            cache_set(f"summary:{profile}:mtd", summary_ctx)

            prev_groups = ce.get_cost_by_service(prev_window, spec=spec)
            prev_map = {g.primary_key(): g.value.amount_usd for g in prev_groups}
            svc_rows, total = service_rows_from_groups(services, prev_map)
            cache_set(f"services:{profile}:mtd:8", {
                "error": None,
                "total": total,
                "services": svc_rows[:8],
                "cost_basis_label": "Pre-credit gross",
            })
            cache_set(f"services:{profile}:mtd:0", {
                "error": None,
                "total": total,
                "services": svc_rows,
                "cost_basis_label": "Pre-credit gross",
            })

            for p in ("6m", "12m"):
                w = period_to_window(p)
                points = ce.get_trend(w, granularity=Granularity.MONTHLY, spec=spec)
                cache_set(f"trend_data:{profile}:{p}", {
                    "labels": [pt.period_start[:7] for pt in points],
                    "values": [round(pt.value.amount_usd, 2) for pt in points],
                })

            try:
                from aws_cost_ultra.audit.budgets import get_budget_findings
                findings = get_budget_findings(session)
                cache_set(f"budgets:{profile}", {"error": None, "findings": [f.to_dict() for f in findings]})
            except Exception as exc:
                log.info("prewarm budgets skipped for %s: %s", profile, exc)

            try:
                cache_set(f"audit:{profile}:{ALL_REGIONS}:0", build_audit_ctx(profile, ALL_REGIONS, 0))
            except Exception as exc:
                log.info("prewarm audit skipped for %s: %s", profile, exc)

            try:
                cache_set(
                    f"resources:{profile}:mtd:{ALL_REGIONS}",
                    build_resources_ctx(profile, "mtd", ALL_REGIONS),
                )
            except Exception as exc:
                log.info("prewarm resources skipped for %s: %s", profile, exc)

            log.info("prewarm complete for profile=%s", profile)
        except Exception as exc:
            log.warning("prewarm error for %s: %s", profile, exc)
