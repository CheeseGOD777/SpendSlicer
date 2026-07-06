"""Startup cache pre-warm — populate the canonical matrix before first click.

Only kicks in when ACU_ENABLE_PREWARM is truthy (handled by web/app.py).
Goal: drop the cost of a cold dashboard load to one cache lookup, while
not exceeding 1 CE call per profile per server start.
"""

from __future__ import annotations

import logging

from aws_cost_ultra.core.filters import pre_credit_gross
from aws_cost_ultra.web.deps import get_cost_source, get_session, period_to_window

log = logging.getLogger("aws_cost_ultra.prewarm")


def prewarm_background(profiles: list[str]) -> None:
    """Warm the canonical CostStore matrix for each profile's current month.

    All downstream views (summary, services, top-services) derive from this
    one matrix at request time, so a single fetch per profile is enough.
    """
    for profile in profiles:
        try:
            session = get_session(profile)
            spec = pre_credit_gross()

            try:
                account_id = session.client("sts").get_caller_identity()["Account"]
            except Exception as exc:
                log.info("skip prewarm %s: %s", profile, type(exc).__name__)
                continue

            window = period_to_window("mtd")
            # FINDING 43: warm through CostSource — the same path request
            # handlers use — so when CUR is configured the warm hits the (free)
            # CUR store instead of spending a CE call that the routes then never
            # read (they'd prefer CUR). With no CUR it's still the CE matrix.
            src = get_cost_source(session)
            src.get_matrix(profile, account_id, window, spec)

            log.info("prewarm matrix populated for profile=%s", profile)
        except Exception as exc:
            log.warning("prewarm error for %s: %s", profile, exc, exc_info=True)
