"""Shared web context — profiles, periods, errors."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from aws_cost_ultra.aws.session import list_profiles, load_profile_bundle
from aws_cost_ultra.web.deps import cache_get, cache_set

log = logging.getLogger(__name__)


def get_profile_choices() -> list[dict]:
    """AWS CLI profiles with human labels (alias · account id)."""
    ckey = "profile_choices"
    cached = cache_get(ckey)
    if cached:
        return cached

    profiles = list_profiles() or ["default"]
    choices: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(8, len(profiles))) as pool:
        futs = {pool.submit(load_profile_bundle, p, None): p for p in profiles}
        for fut in as_completed(futs):
            profile_name = futs[fut]
            try:
                bundle = fut.result()
                label = bundle.display_name()
                if bundle.account_id and bundle.account_id not in label:
                    label = f"{label} ({bundle.account_id})"
                choices.append({
                    "profile": bundle.profile,
                    "label": label,
                    "account_id": bundle.account_id,
                })
            except Exception as exc:
                log.warning("get_profile_choices: failed to load bundle for profile=%r: %s", profile_name, type(exc).__name__, exc_info=True)
                choices.append({
                    "profile": profile_name,
                    "label": profile_name,
                    "account_id": None,
                })

    choices.sort(key=lambda c: c["profile"])
    cache_set(ckey, choices)
    return choices


def base_ctx(profile: str, period: str, active_page: str) -> dict:
    from aws_cost_ultra.web.deps import COMMON_REGIONS

    profile_choices = get_profile_choices()
    valid_profiles = [c["profile"] for c in profile_choices]
    if profile not in valid_profiles and valid_profiles:
        profile = valid_profiles[0]

    return {
        "active_profile": profile,
        "period": period,
        "active_page": active_page,
        "profiles": valid_profiles,
        "profile_choices": profile_choices,
        "regions": [("all", "All regions")] + list(COMMON_REGIONS),
        "periods": [
            ("mtd", "Month to date"),
            ("last_month", "Last month"),
            ("30d", "Last 30 days"),
            ("3m", "Last 3 months"),
        ],
        "cost_basis_label": "Pre-credit · excludes Credit/Refund/Upfront · UTC",
    }


def friendly_error(exc: Exception) -> str:
    msg = str(exc)
    if "NoCredentialsError" in type(exc).__name__ or "credentials" in msg.lower():
        return "AWS credentials not found. Run: aws configure"
    if "ExpiredToken" in msg or "expired" in msg.lower():
        return "AWS session token expired. Re-authenticate and try again."
    if "AccessDenied" in msg or "not authorized" in msg.lower():
        return "Access denied. Check IAM permissions for Cost Explorer and resource APIs."
    # Do not leak raw exception text (may contain ARNs, account IDs, etc.) to clients.
    log.error("Unhandled AWS error: %s", exc, exc_info=True)
    return "AWS error — see server logs for details."
