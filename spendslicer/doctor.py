"""`spendslicer doctor` — why AWS credentials are not resolving.

Written after a report where `aws configure list-profiles` worked in the
user's shell but the server process got NoCredentialsError. Diagnosing that
remotely took a round trip of "run this snippet and paste the output", which
is exactly the kind of thing the tool should answer itself.

It prints which files boto3 is actually reading, which profiles it can see,
and whether each one's credentials resolve — the three facts that separate
"no profile", "wrong file", and "profile exists but has no usable keys".

Read-only and free: resolving credentials touches no billable API. The
optional identity check calls sts:GetCallerIdentity, which is also free.
"""

from __future__ import annotations

import os
import sys

CHECK = "OK  "
CROSS = "FAIL"
INFO = "--  "


def _line(status: str, label: str, value: str = "") -> None:
    print(f"  [{status}] {label}" + (f": {value}" if value else ""))


def run(check_identity: bool = True) -> int:
    """Print a diagnosis. Returns 0 when at least one profile works."""
    import boto3

    from spendslicer import __version__
    from spendslicer.aws.session import aws_config_locations, list_profiles

    print(f"SpendSlicer {__version__} — AWS credential check")
    print(f"  python {sys.version.split()[0]} on {sys.platform}")
    print()

    print("Where boto3 reads configuration")
    loc = aws_config_locations()
    for key, label in (
        ("credentials_file", "credentials file"),
        ("config_file", "config file"),
    ):
        path = loc.get(key, "")
        exists = bool(path) and os.path.exists(path)
        _line(CHECK if exists else CROSS, label, f"{path or '(unknown)'}"
              + ("" if exists else "  <- does not exist"))
    # The single most common cause of "works in my shell, not in the app".
    home = os.path.expanduser("~")
    _line(INFO, "home directory", home)
    if loc.get("profile_env"):
        _line(INFO, "AWS_PROFILE is set", loc["profile_env"]
              + "  <- overrides the default profile")
    for var in ("AWS_SHARED_CREDENTIALS_FILE", "AWS_CONFIG_FILE",
                "AWS_ACCESS_KEY_ID", "AWS_SESSION_TOKEN"):
        if os.environ.get(var):
            shown = "(set)" if "KEY" in var or "TOKEN" in var else os.environ[var]
            _line(INFO, f"{var} is set", shown)
    print()

    profiles = list_profiles()
    print(f"Profiles boto3 can see ({len(profiles)})")
    if not profiles:
        _line(CROSS, "none found",
              "run `aws configure` to create a default profile")
    working = 0
    for name in profiles or []:
        try:
            sess = boto3.Session(profile_name=name)
            creds = sess.get_credentials()
        except Exception as exc:
            _line(CROSS, name, type(exc).__name__)
            continue
        if creds is None:
            _line(CROSS, name, "defined, but no credentials resolve")
            continue
        detail = f"credentials resolve (via {creds.method})"
        if check_identity:
            try:
                acct = sess.client("sts").get_caller_identity()["Account"]
                detail += f", account {acct}"
            except Exception as exc:
                _line(CROSS, name, f"credentials found but unusable: {type(exc).__name__}")
                continue
        working += 1
        _line(CHECK, name, detail)

    # The bare default chain works with no profile at all — env vars, an EC2
    # instance role, or ECS task role — so check it even when no profile is
    # defined.
    print()
    print("Default credential chain (no profile)")
    try:
        creds = boto3.Session().get_credentials()
        if creds is None:
            _line(CROSS, "unusable", "no credentials from env, profile or instance role")
        else:
            working += 1
            _line(CHECK, "usable", f"via {creds.method}")
    except Exception as exc:
        _line(CROSS, "unusable", type(exc).__name__)

    print()
    if working:
        print(f"{working} working credential source(s). SpendSlicer should run.")
        return 0
    print("No working credentials. Fix one of:")
    print("  - run `aws configure` (creates the default profile)")
    print("  - `aws sso login --profile <name>` for SSO profiles")
    print("  - check the home directory above is the one you ran `aws configure` in;")
    print("    a service or elevated shell can have a different HOME/USERPROFILE")
    return 1


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else []
    return run(check_identity="--offline" not in args)
