"""Shared web context — profiles, periods, errors."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from spendslicer.aws.session import list_profiles, load_profile_bundle
from spendslicer.web.deps import cache_get, cache_set

log = logging.getLogger(__name__)


def get_profile_choices() -> list[dict]:
    """AWS CLI profiles with human labels (alias · account id)."""
    ckey = "profile_choices"
    cached = cache_get(ckey)
    if cached:
        return cached

    profiles = list_profiles() or ["default"]
    choices: list[dict] = []
    failed: dict[str, str] = {}
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
                # Expected and common: a profile whose credentials expired, or
                # an SSO session that needs re-login. One stack trace per
                # profile turned an ordinary startup into a wall of text, so
                # the trace goes to debug and the loop reports a summary.
                failed[profile_name] = type(exc).__name__
                log.debug(
                    "get_profile_choices: could not load profile=%r",
                    profile_name, exc_info=True,
                )
                choices.append({
                    "profile": profile_name,
                    "label": profile_name,
                    "account_id": None,
                })

    if failed:
        log.warning(
            "%d of %d AWS profile(s) could not be loaded and are listed without "
            "an account id: %s. Usually expired credentials or an SSO session "
            "needing `aws sso login`.",
            len(failed), len(profiles),
            ", ".join(f"{p} ({e})" for p, e in sorted(failed.items())),
        )

    choices.sort(key=lambda c: c["profile"])
    cache_set(ckey, choices)
    return choices


def base_ctx(profile: str, period: str, active_page: str) -> dict:
    from spendslicer.web.deps import COMMON_REGIONS, available_periods, is_valid_period

    profile_choices = get_profile_choices()
    valid_profiles = [c["profile"] for c in profile_choices]
    if profile not in valid_profiles and valid_profiles:
        profile = valid_profiles[0]

    # Validate the client-supplied period against the allow-list before it is
    # reflected into any template. ``period`` is interpolated into an inline
    # <script> JS template literal on the export page, where Jinja's HTML
    # autoescaping does NOT neutralise backticks or ${...} — so an unvalidated
    # value is a reflected-XSS vector. Clamp to a safe default on mismatch.
    if not is_valid_period(period):
        period = "mtd"

    # Flat (value, label) tuples for the legacy Jinja template (base.html
    # unpacks two-tuples). The SPA gets the richer grouped list via
    # /api/ui/context, which calls available_periods() directly.
    periods = [(p["value"], p["label"]) for p in available_periods()]

    return {
        "active_profile": profile,
        "period": period,
        "active_page": active_page,
        "profiles": valid_profiles,
        "profile_choices": profile_choices,
        "regions": [("all", "All regions")] + list(COMMON_REGIONS),
        "periods": periods,
        "cost_basis_label": "Pre-credit · excludes Credit/Refund/Upfront · UTC",
    }


def friendly_error(exc: Exception) -> str:
    msg = str(exc)
    name = type(exc).__name__
    if "NoCredentialsError" in name or "credentials" in msg.lower():
        return "AWS credentials not found. Run: aws configure"
    # ProfileNotFound says "The config profile (x) could not be found", which
    # contains neither "credentials" nor "not authorized", so it used to fall
    # through to the generic "see server logs" line — and then logged a full
    # stack trace for what is just a mistyped or missing profile.
    if "ProfileNotFound" in name or "could not be found" in msg:
        return (
            "That AWS profile was not found in ~/.aws/config or "
            "~/.aws/credentials. Run `aws configure` to create it, or pick "
            "another profile."
        )
    if "ExpiredToken" in msg or "expired" in msg.lower():
        return "AWS session token expired. Re-authenticate and try again."
    if "AccessDenied" in msg or "not authorized" in msg.lower():
        return "Access denied. Check IAM permissions for Cost Explorer and resource APIs."
    # Do not leak raw exception text (may contain ARNs, account IDs, etc.) to clients.
    log.error("Unhandled AWS error: %s", exc, exc_info=True)
    return "AWS error — see server logs for details."
