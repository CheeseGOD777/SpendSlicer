"""A profile that exists but resolves no credentials must fail once, clearly.

Reported from Windows: `aws configure` had created a working default profile,
`aws configure list-profiles` listed it, but credentials did not resolve for
the server process. The dashboard returned HTTP 200 with zeros while the
terminal filled with ~150 NoCredentialsError stack traces — one per
(service x region) work unit in the resource fan-out.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from spendslicer.resources.runner import _frozen_session
from spendslicer.web import deps


def test_get_session_rejects_a_profile_with_no_credentials(monkeypatch):
    session = MagicMock()
    session.get_credentials.return_value = None
    monkeypatch.setattr(deps, "make_session", lambda profile=None: session)

    with pytest.raises(HTTPException) as ei:
        deps.get_session("default")

    assert ei.value.status_code == 400
    # The message has to name the fix, not just the failure.
    assert "aws configure" in ei.value.detail
    assert "default" in ei.value.detail


def test_get_session_passes_a_profile_that_does_resolve(monkeypatch):
    session = MagicMock()
    session.get_credentials.return_value = MagicMock()
    monkeypatch.setattr(deps, "make_session", lambda profile=None: session)
    assert deps.get_session("default") is session


def test_frozen_session_refuses_to_go_anonymous():
    """The old code returned boto3.Session(region_name=...) here.

    That session has no credentials, so the failure moved from one place to
    every worker in the fan-out and the caller could not distinguish an empty
    account from an unauthenticated one.
    """
    base = MagicMock()
    base.get_credentials.return_value = None
    with pytest.raises(RuntimeError, match="No AWS credentials"):
        _frozen_session(base, "ap-south-1")


def test_friendly_error_recognises_a_missing_profile():
    """ProfileNotFound's message contains neither "credentials" nor
    "not authorized", so it fell through to the generic "see server logs"
    line and logged a stack trace for a mistyped profile name."""
    from botocore.exceptions import ProfileNotFound

    from spendslicer.web.context import friendly_error

    msg = friendly_error(ProfileNotFound(profile="typo"))
    assert "not found" in msg.lower()
    assert "aws configure" in msg
    assert "server logs" not in msg


def test_friendly_error_still_recognises_missing_credentials():
    from botocore.exceptions import NoCredentialsError

    from spendslicer.web.context import friendly_error

    assert friendly_error(NoCredentialsError()) == "AWS credentials not found. Run: aws configure"
