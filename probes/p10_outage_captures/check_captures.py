#!/usr/bin/env python3
"""Probe P10: do the Wayback Machine's copies exist for the cycles the witness recorded as never
captured, and do they hash to what the archive recorded?

The witness asked Save Page Now for a copy of each file, got HTTP 500, and recorded no copy. This
looks in the Wayback index afterwards. For each such cycle it takes the earliest capture of the
manifest and of each of the ten sampled files, fetches the id_ copy, unpacks it if it is gzip, and
compares the SHA-256 of the raw bytes with the digest the archive recorded when it pulled the file.

Read-only. It never writes to the spool or asks Save Page Now for anything. Results go to --out as
JSON, and only copies whose digest matched go to --late, added to what that file already holds: a copy
found by an earlier run is verified in the ledger by now, so this run does not look at it again.

    python probes/p10_outage_captures/check_captures.py --ledger ledger.json --cdx cdx.json \
        --spool Z:/ephemera/spool --out results.json --late archive/late_copies.json
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

FOLDER = "https://api.starlink.com/public-files/ephemerides/"
PAUSE_S = 2.0
HEADERS = {"User-Agent": "ephemera-verify/1.0 (+https://ephemera.space)"}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp(first_seen: str) -> str:
    """A cycle's first-seen time in the form the Wayback index uses for its timestamps."""
    return re.sub(r"\D", "", first_seen)[:14]


def fetch_raw(session: requests.Session, url: str) -> tuple[int, bytes]:
    """The body of an id_ copy with any gzip removed. requests unpacks Content-Encoding: gzip; a copy
    stored as the origin's gzip bytes without that header is unpacked here. Retries a throttled or
    failing request a few times, then reports the last status rather than hiding it."""
    code = -1
    for attempt in range(4):
        time.sleep(PAUSE_S * (1 + 5 * attempt))
        try:
            r = session.get(url, timeout=180)
        except requests.RequestException as e:
            print(f"  {type(e).__name__} on attempt {attempt + 1}: {url}", flush=True)
            continue
        code = r.status_code
        if code == 200:
            body = r.content
            return 200, gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
        if code not in (429, 500, 502, 503, 504):
            return code, b""
        print(f"  HTTP {code} on attempt {attempt + 1}: {url}", flush=True)
    return code, b""


def index_rows(cdx_path: Path) -> dict[str, list[str]]:
    """{original URL: its status-200 capture timestamps, oldest first} from a saved CDX prefix query."""
    rows = json.loads(cdx_path.read_text(encoding="utf-8"))
    head, rows = rows[0], rows[1:]
    ts, orig = head.index("timestamp"), head.index("original")
    out: dict[str, list[str]] = {}
    for row in rows:
        out.setdefault(row[orig], []).append(row[ts])
    return {k: sorted(v) for k, v in out.items()}


def check_one(session, index, url: str, want: str, after: str) -> dict:
    """The earliest capture of url at or after the cycle was first seen, fetched and hashed."""
    captures = [t for t in index.get(url, []) if t >= after]
    if not captures:
        return {"state": "not in index", "url": url}
    ts = captures[0]
    copy = f"https://web.archive.org/web/{ts}id_/{url}"
    code, raw = fetch_raw(session, copy)
    if code != 200:
        return {"state": f"HTTP {code}", "timestamp": ts, "copy_url": copy}
    got = hashlib.sha256(raw).hexdigest()
    return {"state": "match" if got == want else "DIFFERENT", "timestamp": ts, "copy_url": copy, "sha256_of_copy": got}


def merged_late(held: dict, found: dict) -> dict:
    """What the file holds plus what this run found. A copy that matched once stays, because a copy can
    answer 404 for days and come back (README), so a rerun only ever adds to an entry, and the entry
    keeps the date it was first found."""
    out = dict(held)
    for cycle, entry in found.items():
        was = held.get(cycle)
        out[cycle] = entry if was is None else {**entry, "checked_utc": was["checked_utc"], "manifest": was["manifest"],
                                                "samples": {**entry["samples"], **was["samples"]}}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ledger", type=Path, required=True)
    ap.add_argument("--cdx", type=Path, required=True)
    ap.add_argument("--spool", type=Path, required=True, help="a spool holding those cycles' cycle.json; only read")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--late", type=Path, required=True)
    args = ap.parse_args()

    ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
    index = index_rows(args.cdx)
    session = requests.Session()
    session.headers.update(HEADERS)
    targets = [c for c in ledger["cycles"]
               if c["wayback"].get("attempted") and not c["wayback"]["skipped"]
               and not c["wayback"]["manifest_verified"] and not c["wayback"]["manifest_captured"]]
    targets.sort(key=lambda c: c["first_seen_utc"])
    print(f"{len(targets)} cycles recorded as never captured; started {utc_now()}", flush=True)

    results, late = [], {}
    for c in targets:
        sha12 = c["cycle"][6:]
        after = stamp(c["first_seen_utc"])
        rec = json.loads((args.spool / c["cycle"] / "cycle.json").read_text(encoding="utf-8"))
        digests = {f["name"]: f["sha256"] for f in rec["files"]}
        manifest = check_one(session, index, f"{FOLDER}MANIFEST.txt?cycle={sha12}", c["manifest_sha256"], after)
        samples = {s["name"]: check_one(session, index, FOLDER + s["name"], digests[s["name"]], after)
                   for s in c["wayback"]["samples"]}
        counts = {}
        for s in samples.values():
            counts[s["state"]] = counts.get(s["state"], 0) + 1
        print(f"{sha12} {c['first_seen_utc']} manifest={manifest['state']} samples={counts}", flush=True)
        results.append({"cycle": c["cycle"], "first_seen_utc": c["first_seen_utc"], "manifest": manifest, "samples": samples})
        if manifest["state"] == "match":
            late[c["cycle"]] = {
                "checked_utc": utc_now(),
                "manifest": {"timestamp": manifest["timestamp"], "id_url": manifest["copy_url"],
                             "sha256_of_copy": manifest["sha256_of_copy"]},
                "samples": {n: {"timestamp": s["timestamp"], "id_url": s["copy_url"], "sha256_of_copy": s["sha256_of_copy"]}
                            for n, s in samples.items() if s["state"] == "match"}}
        # Written after every cycle, so a stopped run keeps what it measured.
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"checked_utc": utc_now(), "cycles": results}, indent=1), encoding="utf-8")

    held = json.loads(args.late.read_text(encoding="utf-8"))["cycles"] if args.late.exists() else {}
    args.late.write_text(json.dumps({"method": "probes/p10_outage_captures", "cycles": merged_late(held, late)},
                                    indent=1) + "\n", encoding="utf-8")
    print(f"finished {utc_now()}: {len(late)} of {len(targets)} manifests matched; "
          f"{sum(len(v['samples']) for v in late.values())} samples matched under them", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
