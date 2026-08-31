#!/usr/bin/env python3
"""Cloudflare plumbing for the static site (D19). Stdlib only; called ONLY from scripts that
sourced infra/guard_cf.sh, which exports CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID after
verifying them against the personal allowlist.

  python infra/cf_site.py project   ensure the Pages project exists
  python infra/cf_site.py domain    attach ephemera.space to it and ensure the apex DNS record
  python infra/cf_site.py all       both (default)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.cloudflare.com/client/v4"
PROJECT = "ephemera"
DOMAIN = "ephemera.space"
BRANCH = "main"


def call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        API + path, method=method,
        headers={"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}",
                 "Content-Type": "application/json"},
        data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


def ok(r: dict) -> bool:
    return bool(r.get("success"))


ACCT = os.environ["CLOUDFLARE_ACCOUNT_ID"]


def ensure_project() -> None:
    r = call("GET", f"/accounts/{ACCT}/pages/projects/{PROJECT}")
    if ok(r):
        print(f"project {PROJECT}: exists ({r['result'].get('subdomain', '')})")
        return
    r = call("POST", f"/accounts/{ACCT}/pages/projects", {"name": PROJECT, "production_branch": BRANCH})
    if not ok(r):
        sys.exit(f"project create failed: {r.get('errors')}")
    print(f"project {PROJECT}: created ({r['result'].get('subdomain', '')})")


def ensure_domain() -> None:
    r = call("GET", f"/accounts/{ACCT}/pages/projects/{PROJECT}/domains")
    names = [d["name"] for d in (r.get("result") or [])] if ok(r) else []
    if DOMAIN in names:
        print(f"domain {DOMAIN}: already attached")
    else:
        r = call("POST", f"/accounts/{ACCT}/pages/projects/{PROJECT}/domains", {"name": DOMAIN})
        if not ok(r):
            sys.exit(f"domain attach failed: {r.get('errors')}")
        print(f"domain {DOMAIN}: attached")

    r = call("GET", f"/zones?name={DOMAIN}")
    if not ok(r) or not r.get("result"):
        sys.exit(f"zone lookup failed - the token needs Zone:Read on {DOMAIN}: {r.get('errors')}")
    zone = r["result"][0]["id"]
    target = f"{PROJECT}.pages.dev"
    r = call("GET", f"/zones/{zone}/dns_records?name={DOMAIN}")
    apex = [x for x in (r.get("result") or []) if x["name"] == DOMAIN and x["type"] in ("CNAME", "A", "AAAA")]
    if apex:
        print(f"dns {DOMAIN}: record exists ({', '.join(x['type'] + '->' + x.get('content', '?') for x in apex)})")
    else:
        r = call("POST", f"/zones/{zone}/dns_records",
                 {"type": "CNAME", "name": DOMAIN, "content": target, "proxied": True})
        if not ok(r):
            sys.exit(f"dns create failed: {r.get('errors')}")
        print(f"dns {DOMAIN}: CNAME -> {target} (proxied, flattened at the apex)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd not in ("project", "domain", "all"):
        sys.exit(__doc__)
    if cmd in ("project", "all"):
        ensure_project()
    if cmd in ("domain", "all"):
        ensure_domain()
