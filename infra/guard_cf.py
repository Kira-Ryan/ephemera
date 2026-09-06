#!/usr/bin/env python3
"""The Cloudflare account guard for Python entry points (mirror of guard_cf.sh, same rules).

The shell guard can only run where `infra/personal.env` exists, which is this machine. The deploy
workflow runs on a GitHub runner with two secrets and no personal.env, so before this existed it
called the deploy client directly and no guard ran at all. `cf_site.py` now calls `enforce()`
before its first write, so there is no path to a Cloudflare write that skips the check.

Two rules, and neither has an override flag:

1. **Allowlist.** If an allowlist is available, in `EPHEMERA_CF_ACCOUNT_IDS` or in personal.env,
   the account being used must be on it. An allowlist that is present but empty is a refusal.
2. **Zone binding.** The token must be able to see the project's own zone, and that zone must
   belong to the account being used. This is the rule that does the real work on a runner: a token
   for any other account cannot see ephemera.space, so it is refused before anything is written.
   It is never skipped, on any machine.

Rule 1 is what protects the developer machine, whose ambient Cloudflare login belongs to an
employer identity. Rule 2 is what protects everywhere else. Where personal.env is absent and no
allowlist is supplied, the guard says so out loud rather than quietly checking less.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

INFRA = Path(__file__).resolve().parent
ZONE = "ephemera.space"
API = "https://api.cloudflare.com/client/v4"


class GuardRefused(RuntimeError):
    """Raised when the guard refuses; callers must not catch this and carry on."""


def _load_personal_env() -> dict[str, str]:
    import guard  # noqa: PLC0415 - the shared personal.env parser

    try:
        return guard.load_env()
    except guard.GuardRefused:
        return {}


def settings() -> tuple[str, str, str | None, str]:
    """(token, account, allowlist or None, where the allowlist came from)."""
    sys.path.insert(0, str(INFRA))
    env = _load_personal_env()
    token = os.environ.get("CLOUDFLARE_API_TOKEN") or env.get("CLOUDFLARE_API_TOKEN", "")
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID") or env.get("CLOUDFLARE_ACCOUNT_ID", "")
    # In personal.env the variable is written by hand, so present-but-empty is a deliberate empty
    # allowlist and a refusal, exactly as guard_cf.sh treats it. In the environment an unset GitHub
    # secret arrives as an empty string, so there empty means absent and the zone binding stands
    # alone. The difference is stated out loud when the guard runs.
    if os.environ.get("EPHEMERA_CF_ACCOUNT_IDS", "").strip():
        return token, account, os.environ["EPHEMERA_CF_ACCOUNT_IDS"], "the environment"
    if "EPHEMERA_CF_ACCOUNT_IDS" in env:
        return token, account, env["EPHEMERA_CF_ACCOUNT_IDS"], "personal.env"
    return token, account, None, "nowhere"


def zone_account(token: str, opener=None) -> str:
    """The account id that owns the project's zone, according to Cloudflare."""
    req = urllib.request.Request(f"{API}/zones?name={ZONE}",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=60) as r:
            body = json.load(r)
    except Exception as e:  # noqa: BLE001 - unreachable API means no verification, so no action
        raise GuardRefused(f"guard_cf: Cloudflare API unreachable ({e}) - no verification, no action") from e
    zones = body.get("result") or []
    if not body.get("success") or not zones:
        raise GuardRefused(f"guard_cf: REFUSED - this token cannot see the {ZONE} zone "
                           "(wrong account, or a token scoped somewhere else)")
    return zones[0]["account"]["id"]


def enforce(opener=None) -> str:
    token, account, allowlist, source = settings()
    if not token or not account:
        raise GuardRefused("guard_cf: REFUSED - CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID must both be set "
                           "(environment, or infra/personal.env)")
    if allowlist is not None:
        ids = allowlist.split()
        if not ids:
            raise GuardRefused(f"guard_cf: REFUSED - the allowlist in {source} is empty, and an empty allowlist "
                               "is a refusal, never a pass")
        if account not in ids:
            raise GuardRefused(f"guard_cf: REFUSED - account {account} is not on the allowlist from {source} "
                               f"({allowlist})")
    owner = zone_account(token, opener)
    if owner != account:
        raise GuardRefused(f"guard_cf: REFUSED - the {ZONE} zone belongs to account {owner}, not to the "
                           f"{account} this run is using")
    where = f"allowlisted in {source} and " if allowlist is not None else ""
    print(f"guard_cf: Cloudflare account {account} {where}confirmed to own the {ZONE} zone - proceeding",
          file=sys.stderr)
    if allowlist is None:
        print("guard_cf: no allowlist was supplied, so only the zone binding was checked. Set "
              "EPHEMERA_CF_ACCOUNT_IDS to add the second rule.", file=sys.stderr)
    os.environ["CLOUDFLARE_API_TOKEN"] = token
    os.environ["CLOUDFLARE_ACCOUNT_ID"] = account
    return account


def main(argv: list[str] | None = None) -> int:
    try:
        enforce()
    except GuardRefused as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
