#!/usr/bin/env python3
"""The AWS account guard for Python entry points (mirror of guard.sh, same rules, same file).

Long-running Python jobs (the shipper) run under pythonw as scheduled tasks and cannot source a
bash script, so they call enforce() first. It reads infra/personal.env, requires the named
PERSONAL profile (this machine's default profile is an employer account), pins AWS_PROFILE before
the first API call, asks STS who we are, refuses anything on the forbidden list, then refuses
anything not on the allowlist. Nothing bypasses it; an empty list is a refusal.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

INFRA = Path(__file__).resolve().parent
_LINE = re.compile(r'^\s*([A-Z_][A-Z0-9_]*)\s*=\s*"?([^"\n]*)"?\s*$')


class GuardRefused(RuntimeError):
    """Raised when the guard refuses; callers must not catch this and carry on."""


def load_env(path: Path = INFRA / "personal.env") -> dict[str, str]:
    if not path.exists():
        raise GuardRefused(f"guard: {path} is missing - copy personal.env.example and fill it in")
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("#"):
            continue
        m = _LINE.match(line)
        if m:
            env[m.group(1)] = m.group(2).strip()
    return env


def sts_account() -> str:
    import boto3  # noqa: PLC0415 - only needed when actually guarding

    return boto3.client("sts").get_caller_identity()["Account"]


def enforce(env: dict[str, str] | None = None, identity=sts_account) -> dict[str, str]:
    """Return {'profile', 'account'} for an allowlisted personal identity, or raise GuardRefused."""
    env = load_env() if env is None else env
    allow = env.get("EPHEMERA_AWS_ACCOUNT_IDS", "").split()
    forbidden = env.get("EPHEMERA_AWS_FORBIDDEN_IDS", "").split()
    profile = env.get("EPHEMERA_AWS_PROFILE", "")
    if not allow:
        raise GuardRefused("guard: EPHEMERA_AWS_ACCOUNT_IDS is empty - an empty allowlist is a refusal, not a pass")
    if not profile:
        raise GuardRefused("guard: EPHEMERA_AWS_PROFILE is empty - the default profile is an employer account; "
                           "the personal profile must be named explicitly")
    os.environ["AWS_PROFILE"] = profile          # pinned BEFORE the first API call
    try:
        acct = identity()
    except Exception as e:  # noqa: BLE001 - no identity, no infrastructure action
        raise GuardRefused(f"guard: could not establish the AWS identity ({type(e).__name__}: {e})") from e
    if acct in forbidden:
        raise GuardRefused(f"guard: REFUSED - AWS account {acct} is on the FORBIDDEN list (an employer account). Stop.")
    if acct not in allow:
        raise GuardRefused(f"guard: REFUSED - AWS account {acct} is not on the personal allowlist ({' '.join(allow)})")
    return {"profile": profile, "account": acct}


if __name__ == "__main__":
    print(enforce())
