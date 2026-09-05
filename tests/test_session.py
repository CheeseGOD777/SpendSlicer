"""Phase 2 — session factory, ProfileBundle, fan-out."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from spendslicer.aws.session import (
    ProfileBundle,
    accessible_regions,
    account_alias_for,
    account_id_for,
    fanout,
    fanout_regions,
    load_profile_bundle,
    make_session,
)

# ---------------------------------------------------------------------------
# make_session
# ---------------------------------------------------------------------------

def test_make_session_no_args_returns_session():
    import boto3
    session = make_session()
    assert isinstance(session, boto3.Session)


def test_make_session_with_region_sets_region():
    session = make_session(region="eu-west-1")
    assert session.region_name == "eu-west-1"


# ---------------------------------------------------------------------------
# account_id_for
# ---------------------------------------------------------------------------

def test_account_id_for_returns_account_on_success():
    session = MagicMock()
    session.client.return_value.get_caller_identity.return_value = {"Account": "123456789012"}
    assert account_id_for(session) == "123456789012"


def test_account_id_for_returns_none_on_failure():
    session = MagicMock()
    session.client.return_value.get_caller_identity.side_effect = Exception("no creds")
    assert account_id_for(session) is None


# ---------------------------------------------------------------------------
# account_alias_for
# ---------------------------------------------------------------------------

def test_account_alias_for_returns_first_alias():
    session = MagicMock()
    session.client.return_value.list_account_aliases.return_value = {
        "AccountAliases": ["my-company"]
    }
    assert account_alias_for(session) == "my-company"


def test_account_alias_for_returns_none_when_no_aliases():
    session = MagicMock()
    session.client.return_value.list_account_aliases.return_value = {"AccountAliases": []}
    assert account_alias_for(session) is None


def test_account_alias_for_returns_none_on_error():
    session = MagicMock()
    session.client.return_value.list_account_aliases.side_effect = Exception("no perm")
    assert account_alias_for(session) is None


# ---------------------------------------------------------------------------
# accessible_regions
# ---------------------------------------------------------------------------

def test_accessible_regions_returns_sorted_list():
    session = MagicMock()
    session.client.return_value.describe_regions.return_value = {
        "Regions": [
            {"RegionName": "us-west-2"},
            {"RegionName": "eu-west-1"},
            {"RegionName": "ap-south-1"},
        ]
    }
    regions = accessible_regions(session)
    assert regions == ["ap-south-1", "eu-west-1", "us-west-2"]


def test_accessible_regions_falls_back_on_error():
    session = MagicMock()
    session.client.return_value.describe_regions.side_effect = Exception("no ec2 perm")
    regions = accessible_regions(session)
    assert len(regions) > 0  # returns fallback list
    assert "us-east-1" in regions


# ---------------------------------------------------------------------------
# ProfileBundle
# ---------------------------------------------------------------------------

def test_profile_bundle_display_name_prefers_alias():
    b = ProfileBundle(
        profile="prod", session=MagicMock(),
        account_id="111122223333", account_alias="my-company"
    )
    assert b.display_name() == "my-company"


def test_profile_bundle_display_name_falls_back_to_account_id():
    b = ProfileBundle(profile="prod", session=MagicMock(), account_id="111122223333")
    assert b.display_name() == "111122223333"


def test_profile_bundle_display_name_falls_back_to_profile():
    b = ProfileBundle(profile="prod", session=MagicMock())
    assert b.display_name() == "prod"


# ---------------------------------------------------------------------------
# load_profile_bundle
# ---------------------------------------------------------------------------

def test_load_profile_bundle_uses_provided_regions():
    with patch("spendslicer.aws.session.make_session") as mock_session, \
         patch("spendslicer.aws.session.account_id_for", return_value="123456789012"), \
         patch("spendslicer.aws.session.account_alias_for", return_value="acme"), \
         patch("spendslicer.aws.session.accessible_regions") as mock_regions:
        mock_session.return_value = MagicMock()
        bundle = load_profile_bundle("dev", regions=["us-east-1", "eu-west-1"])
        mock_regions.assert_not_called()  # provided regions bypass the discovery call
        assert bundle.regions == ["us-east-1", "eu-west-1"]
        assert bundle.account_alias == "acme"


# ---------------------------------------------------------------------------
# fanout
# ---------------------------------------------------------------------------

def test_fanout_runs_fn_for_each_bundle():
    bundles = [
        ProfileBundle(profile="a", session=MagicMock(), account_id="111111111111"),
        ProfileBundle(profile="b", session=MagicMock(), account_id="222222222222"),
    ]
    results = fanout(bundles, fn=lambda b: b.profile.upper(), max_workers=2)
    returned = {b.profile: r for b, r in results}
    assert returned["a"] == "A"
    assert returned["b"] == "B"


def test_fanout_captures_exceptions_without_raising():
    bundles = [
        ProfileBundle(profile="ok", session=MagicMock(), account_id="111111111111"),
        ProfileBundle(profile="bad", session=MagicMock(), account_id="222222222222"),
    ]

    def fn(b: ProfileBundle):
        if b.profile == "bad":
            raise ValueError("boom")
        return "ok"

    results = fanout(bundles, fn=fn)
    by_profile = {b.profile: r for b, r in results}
    assert by_profile["ok"] == "ok"
    assert isinstance(by_profile["bad"], ValueError)


def test_fanout_returns_empty_for_no_bundles():
    assert fanout([], fn=lambda b: None) == []


# ---------------------------------------------------------------------------
# fanout_regions
# ---------------------------------------------------------------------------

def test_fanout_regions_calls_fn_per_region():
    bundle = ProfileBundle(
        profile="prod", session=MagicMock(), account_id="111111111111",
        regions=["us-east-1", "eu-west-1"],
    )
    seen_regions: list[str] = []

    def fn(session, region):
        seen_regions.append(region)
        return region.upper()

    results = fanout_regions(bundle, fn=fn)
    region_results = {region: r for region, r in results}
    assert region_results["us-east-1"] == "US-EAST-1"
    assert region_results["eu-west-1"] == "EU-WEST-1"
