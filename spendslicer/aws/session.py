"""AWS session factory — multi-profile, multi-region, parallel fan-out.

Exports:
  - ``accessible_regions(session)`` — EC2 describe_regions
  - ``account_alias_for(session)`` — IAM list_account_aliases
  - ``ProfileBundle`` — one fully-resolved profile: session + account + regions
  - ``load_profile_bundle(profile, regions)`` — single-profile loader
  - ``all_profile_bundles(regions)`` — loads all local profiles in parallel
  - ``fanout(bundles, fn, max_workers)`` — parallel execution across profiles
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TypeVar

import boto3
import botocore.session
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)

T = TypeVar("T")

# Regions to fall back to when EC2 describe_regions isn't available
_FALLBACK_REGIONS = [
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
    "eu-west-1",
    "eu-west-2",
    "eu-central-1",
    "ap-south-1",
    "ap-southeast-1",
    "ap-southeast-2",
    "ap-northeast-1",
]


@dataclass
class ProfileBundle:
    """Fully-resolved AWS profile: session, account identity, and usable regions.

    One instance per profile. Create via ``load_profile_bundle()`` or
    ``all_profile_bundles()``; don't construct directly unless testing.
    """

    profile: str
    session: boto3.Session
    account_id: str | None = None
    account_alias: str | None = None
    regions: list[str] = field(default_factory=list)

    def display_name(self) -> str:
        """Human label: alias preferred, then account ID, then profile name."""
        return self.account_alias or self.account_id or self.profile

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"ProfileBundle(profile={self.profile!r}, "
            f"account={self.account_id!r}, alias={self.account_alias!r}, "
            f"regions={len(self.regions)})"
        )


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

def make_session(profile: str | None = None, region: str | None = None) -> boto3.Session:
    """Build a boto3 session, preferring an explicit profile, else AWS_PROFILE env.

    "default" means the default credential chain, not a profile literally
    named "default". boto3.Session(profile_name="default") raises
    ProfileNotFound unless a [default] section exists, while boto3.Session()
    happily falls back to environment variables, an EC2 instance role or an
    ECS task role. Those are different behaviours and the UI passes the string
    "default" for both cases.

    get_session already made this distinction; load_profile_bundle did not, so
    on a machine with no profiles at all the "default" fallback in
    get_profile_choices produced "1 of 1 AWS profile(s) could not be loaded:
    default (ProfileNotFound)" — which points at a profile problem when the
    real answer is that no credentials were found anywhere. Doing it here
    covers every caller.
    """
    profile = profile or os.environ.get("AWS_PROFILE")
    kw: dict = {}
    if profile and profile != "default":
        kw["profile_name"] = profile
    if region:
        kw["region_name"] = region
    return boto3.Session(**kw)


# ---------------------------------------------------------------------------
# Profile discovery
# ---------------------------------------------------------------------------

def list_profiles() -> list[str]:
    """Every profile boto3 itself can see.

    This used to parse ~/.aws/credentials and ~/.aws/config by hand with
    configparser. That hardcoded the location and so ignored
    AWS_SHARED_CREDENTIALS_FILE and AWS_CONFIG_FILE, which botocore honours —
    common in CI, containers and corporate setups. The dropdown then listed a
    different set of profiles than the ones sessions actually resolve against,
    which is the confusing half of "the CLI sees my profile but the app does
    not".

    Delegating to botocore keeps the two in agreement by construction, and
    picks up the SSO and credential_process forms the hand parser never
    handled. Note it reports profiles that are *defined*, which is not the
    same as profiles whose credentials resolve — get_session checks that.
    """
    try:
        return sorted(boto3.Session().available_profiles)
    except Exception as exc:
        # A malformed config file makes botocore raise here. Returning empty
        # lets get_profiles() fall back to "default" rather than 500 the
        # whole dashboard on a stray character in someone's config.
        log.warning(
            "Could not read AWS profiles (%s); falling back to the default "
            "credential chain. Check ~/.aws/config and ~/.aws/credentials.",
            type(exc).__name__,
        )
        return []


def aws_config_locations() -> dict[str, str]:
    """Where boto3 is actually reading credentials and config from.

    Surfaced in diagnostics because the usual cause of "works in my shell,
    not in the app" is the two processes resolving different files — a
    different HOME/USERPROFILE, or one of the AWS_*_FILE env vars set in only
    one of them.
    """
    try:
        bs = botocore.session.Session()
        return {
            "credentials_file": os.path.expanduser(
                bs.get_config_variable("credentials_file") or ""
            ),
            "config_file": os.path.expanduser(
                bs.get_config_variable("config_file") or ""
            ),
            "profile_env": os.environ.get("AWS_PROFILE", ""),
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Account identity helpers
# ---------------------------------------------------------------------------

def account_id_for(session: boto3.Session) -> str | None:
    """Return the 12-digit AWS account id, or None if STS is unavailable."""
    try:
        return session.client("sts").get_caller_identity()["Account"]
    except (ClientError, KeyError, Exception):
        return None


def account_alias_for(session: boto3.Session) -> str | None:
    """Return the first IAM account alias, or None if none configured / no permission."""
    try:
        resp = session.client("iam").list_account_aliases()
        aliases = resp.get("AccountAliases", [])
        return aliases[0] if aliases else None
    except Exception as exc:
        log.warning("account_alias_for: IAM list_account_aliases failed: %s", type(exc).__name__)
        log.debug("account_alias_for traceback", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Region discovery
# ---------------------------------------------------------------------------

def accessible_regions(session: boto3.Session) -> list[str]:
    """Return opted-in region names for this account, sorted alphabetically.

    Uses EC2 describe_regions with ``AllRegions=False`` so disabled/not-opted-in
    regions are excluded. Falls back to a hardcoded safe set if the call fails
    (e.g. sandbox accounts, no EC2 perms).
    """
    try:
        ec2 = session.client("ec2", region_name="us-east-1")
        resp = ec2.describe_regions(Filters=[{"Name": "opt-in-status", "Values": ["opt-in-not-required", "opted-in"]}])
        return sorted(r["RegionName"] for r in resp.get("Regions", []))
    except Exception as exc:
        log.warning(
            "accessible_regions: EC2 describe_regions failed, using fallback "
            "list: %s", type(exc).__name__,
        )
        log.debug("accessible_regions traceback", exc_info=True)
        return list(_FALLBACK_REGIONS)


# ---------------------------------------------------------------------------
# ProfileBundle loader
# ---------------------------------------------------------------------------

def load_profile_bundle(
    profile: str | None = None,
    regions: list[str] | None = None,
) -> ProfileBundle:
    """Build a fully-resolved ProfileBundle for one profile.

    If ``regions`` is None, the account's accessible regions are discovered
    via EC2 describe_regions (one API call).
    """
    session = make_session(profile)
    profile_name = profile or "default"
    account = account_id_for(session)
    alias = account_alias_for(session)
    resolved_regions = regions if regions is not None else accessible_regions(session)
    return ProfileBundle(
        profile=profile_name,
        session=session,
        account_id=account,
        account_alias=alias,
        regions=resolved_regions,
    )


def all_profile_bundles(
    regions: list[str] | None = None,
    max_workers: int = 8,
) -> list[ProfileBundle]:
    """Load all local profiles in parallel, returning one ProfileBundle each.

    Profiles that fail credential validation are silently skipped (they'll
    appear as None in intermediate results and be filtered out).
    """
    profiles = list_profiles()
    if not profiles:
        return []

    bundles: list[ProfileBundle] = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(profiles))) as pool:
        futures = {
            pool.submit(load_profile_bundle, p, regions): p
            for p in profiles
        }
        for fut in as_completed(futures):
            try:
                bundle = fut.result()
                if bundle.account_id:  # skip profiles that can't authenticate
                    bundles.append(bundle)
            except Exception as exc:
                log.warning(
                    "all_profile_bundles: skipping profile=%s: %s",
                    futures[fut], type(exc).__name__,
                )
                log.debug("all_profile_bundles traceback", exc_info=True)

    return sorted(bundles, key=lambda b: b.profile)


# ---------------------------------------------------------------------------
# Parallel fan-out
# ---------------------------------------------------------------------------

def fanout(
    bundles: list[ProfileBundle],
    fn: Callable[[ProfileBundle], T],
    max_workers: int = 8,
) -> list[tuple[ProfileBundle, T | Exception]]:
    """Run ``fn(bundle)`` for each bundle in parallel.

    Returns a list of (bundle, result_or_exception) pairs in the order
    results complete. Callers decide how to handle per-profile failures —
    this function never silently swallows them.
    """
    if not bundles:
        return []

    results: list[tuple[ProfileBundle, T | Exception]] = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(bundles))) as pool:
        future_to_bundle = {pool.submit(fn, b): b for b in bundles}
        for fut in as_completed(future_to_bundle):
            bundle = future_to_bundle[fut]
            try:
                results.append((bundle, fut.result()))
            except Exception as exc:
                results.append((bundle, exc))

    return results


def fanout_regions(
    bundle: ProfileBundle,
    fn: Callable[[boto3.Session, str], T],
    max_workers: int = 8,
) -> list[tuple[str, T | Exception]]:
    """Run ``fn(session, region)`` for each region in a ProfileBundle in parallel.

    Useful for resource enumeration that must run once per region.
    """
    if not bundle.regions:
        return []

    results: list[tuple[str, T | Exception]] = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(bundle.regions))) as pool:
        future_to_region = {
            pool.submit(fn, bundle.session, region): region
            for region in bundle.regions
        }
        for fut in as_completed(future_to_region):
            region = future_to_region[fut]
            try:
                results.append((region, fut.result()))
            except Exception as exc:
                results.append((region, exc))

    return results
