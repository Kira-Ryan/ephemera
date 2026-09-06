#!/usr/bin/env python3
"""Cloudflare plumbing for the static site (D19). Stdlib only.

Every entry point runs infra/guard_cf.enforce() before its first write. The shell guard covers the
developer machine, where the ambient Cloudflare login belongs to an employer identity; the Python
guard covers everywhere else, including the deploy workflow on a GitHub runner, which has no
personal.env to source and so previously ran no guard at all.

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
from pathlib import Path

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


def acct() -> str:
    """Read after the guard has run, never at import: the guard is what decides this is allowed."""
    return os.environ["CLOUDFLARE_ACCOUNT_ID"]


def ensure_project() -> None:
    r = call("GET", f"/accounts/{acct()}/pages/projects/{PROJECT}")
    if ok(r):
        print(f"project {PROJECT}: exists ({r['result'].get('subdomain', '')})")
        return
    r = call("POST", f"/accounts/{acct()}/pages/projects", {"name": PROJECT, "production_branch": BRANCH})
    if not ok(r):
        sys.exit(f"project create failed: {r.get('errors')}")
    print(f"project {PROJECT}: created ({r['result'].get('subdomain', '')})")


def ensure_domain() -> None:
    r = call("GET", f"/accounts/{acct()}/pages/projects/{PROJECT}/domains")
    names = [d["name"] for d in (r.get("result") or [])] if ok(r) else []
    if DOMAIN in names:
        print(f"domain {DOMAIN}: already attached")
    else:
        r = call("POST", f"/accounts/{acct()}/pages/projects/{PROJECT}/domains", {"name": DOMAIN})
        if not ok(r):
            sys.exit(f"domain attach failed: {r.get('errors')}")
        print(f"domain {DOMAIN}: attached")

    r = call("GET", f"/accounts/{acct()}/pages/projects/{PROJECT}")
    if not ok(r):
        sys.exit(f"project lookup failed: {r.get('errors')}")
    target = r["result"].get("subdomain") or f"{PROJECT}.pages.dev"  # e.g. ephemera-8pv.pages.dev

    r = call("GET", f"/zones?name={DOMAIN}")
    if not ok(r) or not r.get("result"):
        sys.exit(f"zone lookup failed - the token needs Zone:Read on {DOMAIN}: {r.get('errors')}")
    zone = r["result"][0]["id"]
    r = call("GET", f"/zones/{zone}/dns_records?name={DOMAIN}")
    apex = [x for x in (r.get("result") or []) if x["name"] == DOMAIN and x["type"] in ("CNAME", "A", "AAAA")]
    if not apex:
        r = call("POST", f"/zones/{zone}/dns_records",
                 {"type": "CNAME", "name": DOMAIN, "content": target, "proxied": True})
        if not ok(r):
            sys.exit(f"dns create failed: {r.get('errors')}")
        print(f"dns {DOMAIN}: CNAME -> {target} (proxied, flattened at the apex)")
    elif len(apex) == 1 and apex[0]["type"] == "CNAME" and apex[0].get("content") != target:
        r = call("PATCH", f"/zones/{zone}/dns_records/{apex[0]['id']}", {"content": target})
        if not ok(r):
            sys.exit(f"dns correction failed: {r.get('errors')}")
        print(f"dns {DOMAIN}: CNAME corrected {apex[0].get('content')} -> {target}")
    else:
        print(f"dns {DOMAIN}: record exists ({', '.join(x['type'] + '->' + x.get('content', '?') for x in apex)})")


def _request(method: str, url: str, headers: dict, data: bytes | None) -> dict:
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


def deploy(dist: Path) -> None:
    """Direct Upload deployment: hash every file the way Pages expects (blake3 over the base64
    content + the bare extension, first 32 hex chars), upload whatever the edge is missing, then
    create a production deployment from the manifest. No wrangler: verified 31 Aug 2026 that
    wrangler 4.45 resolves its target account from machine-level state it refuses to override,
    which on this machine means an employer account."""
    import base64
    import mimetypes

    import blake3  # deploy-only dependency (requirements.txt)

    entries = []
    for p in sorted(x for x in dist.rglob("*") if x.is_file()):
        content = p.read_bytes()
        h = blake3.blake3(base64.b64encode(content) + p.suffix.lstrip(".").encode()).hexdigest()[:32]
        entries.append(("/" + p.relative_to(dist).as_posix(), p, h, content))
    if not entries:
        sys.exit(f"nothing to deploy under {dist}")

    r = call("GET", f"/accounts/{acct()}/pages/projects/{PROJECT}/upload-token")
    if not ok(r):
        sys.exit(f"upload-token failed: {r.get('errors')}")
    jwt = r["result"]["jwt"]
    jhead = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}

    r = _request("POST", f"{API}/pages/assets/check-missing", jhead,
                 json.dumps({"hashes": [h for _, _, h, _ in entries]}).encode())
    missing = set(r.get("result") or []) if ok(r) else {h for _, _, h, _ in entries}
    payload = [{"key": h, "base64": True,
                "value": base64.b64encode(content).decode(),
                "metadata": {"contentType": mimetypes.guess_type(name)[0] or "application/octet-stream"}}
               for name, _, h, content in entries if h in missing]
    if payload:
        r = _request("POST", f"{API}/pages/assets/upload", jhead, json.dumps(payload).encode())
        if not ok(r):
            sys.exit(f"asset upload failed: {r.get('errors')}")
    _request("POST", f"{API}/pages/assets/upsert-hashes", jhead,
             json.dumps({"hashes": [h for _, _, h, _ in entries]}).encode())  # best effort, like wrangler

    boundary = "ephemera-" + blake3.blake3(json.dumps([h for _, _, h, _ in entries]).encode()).hexdigest()[:24]
    manifest = json.dumps({name: h for name, _, h, _ in entries})
    form = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"manifest\"\r\n\r\n{manifest}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"branch\"\r\n\r\n{BRANCH}\r\n"
            f"--{boundary}--\r\n").encode()
    r = _request("POST", f"{API}/accounts/{acct()}/pages/projects/{PROJECT}/deployments",
                 {"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}",
                  "Content-Type": f"multipart/form-data; boundary={boundary}"}, form)
    if not ok(r):
        sys.exit(f"deployment create failed: {r.get('errors')}")
    res = r["result"]
    print(f"deployed {len(entries)} file(s), {len(payload)} uploaded fresh -> {res.get('url')} "
          f"(environment: {res.get('environment')})")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd not in ("project", "domain", "deploy", "all"):
        sys.exit(__doc__)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import guard_cf  # noqa: E402

    try:
        guard_cf.enforce()
    except guard_cf.GuardRefused as e:
        sys.exit(str(e))
    if cmd in ("project", "all"):
        ensure_project()
    if cmd in ("deploy", "all"):
        deploy(Path(__file__).resolve().parents[1] / "web" / "dist")
    if cmd in ("domain", "all"):
        ensure_domain()
