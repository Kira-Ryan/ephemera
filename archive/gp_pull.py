#!/usr/bin/env python3
"""Ephemera catalogue puller: snapshot the PUBLIC general-perturbations catalogue for Starlink from
Space-Track - the thing the scoreboard measures (concept, layer 2). It is a separate feed from the
operator ephemerides: its own directory, record and hash, never mixed into a cycle's Merkle root
(D10 keeps two pollers' ephemeris roots comparable; the catalogue is fetched at a different
instant and would break that).

  <spool>/gp/<UTC stamp>_<sha12>/gp.json.gz   the Space-Track response bytes, gzipped; the
                                               recorded hash is of the RAW bytes
  <spool>/gp/<UTC stamp>_<sha12>/record.json   sha256, bytes, record count, epoch range, six-digit
                                               count, the query, fetched_utc

Rate policy: one login and one query per pass (default every 2 h, so 24 requests a day) against
the user agreement's 30/min and 300/hour. An unchanged catalogue (same bytes as the previous
snapshot) is logged and not stored twice. A failed login, a non-JSON body, an empty result or a
record without NORAD_CAT_ID/EPOCH is recorded loudly and the pass returns 1. Credentials come from
infra/personal.env (SPACETRACK_USER / SPACETRACK_PASS) or the environment; they are never logged.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "infra"))
import poll  # noqa: E402

BASE_DEFAULT = "https://www.space-track.org"
QUERY_DEFAULT = "basicspacedata/query/class/gp/OBJECT_NAME/STARLINK~~/orderby/NORAD_CAT_ID/format/json"
SCHEMA = 1

log = logging.getLogger("ephemera.gp_pull")


def credentials() -> tuple[str, str]:
    user, pw = os.environ.get("SPACETRACK_USER"), os.environ.get("SPACETRACK_PASS")
    if not (user and pw):
        import guard  # noqa: PLC0415
        env = guard.load_env()
        user, pw = env.get("SPACETRACK_USER", ""), env.get("SPACETRACK_PASS", "")
    if not (user and pw):
        raise RuntimeError("no Space-Track credentials (SPACETRACK_USER/PASS in env or infra/personal.env)")
    return user, pw


def fetch(session: requests.Session, base: str, query: str, user: str, pw: str) -> bytes:
    r = session.post(f"{base}/ajaxauth/login", data={"identity": user, "password": pw}, timeout=60)
    if r.status_code != 200 or "Failed" in r.text[:200]:
        raise RuntimeError(f"Space-Track login refused (HTTP {r.status_code})")
    r = session.get(f"{base}/{query}", timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"Space-Track query HTTP {r.status_code}: {r.text[:120]!r}")
    return r.content


def describe(raw: bytes) -> dict:
    """Validate the body as a non-empty GP list and summarise it; raises on anything else."""
    try:
        rows = json.loads(raw)
    except ValueError as e:
        raise RuntimeError(f"Space-Track body is not JSON ({e}); head={raw[:60]!r}") from e
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Space-Track returned an empty result - refusing to record an empty catalogue")
    for x in rows[:50] + rows[-50:]:
        if "NORAD_CAT_ID" not in x or "EPOCH" not in x:
            raise RuntimeError("Space-Track rows lack NORAD_CAT_ID/EPOCH - not a GP result")
    epochs = [x["EPOCH"] for x in rows]
    return {"records": len(rows), "epoch_min": min(epochs), "epoch_max": max(epochs),
            "six_digit_ids": sum(1 for x in rows if int(x["NORAD_CAT_ID"]) >= 100000)}


def latest_sha(gp_root: Path) -> str | None:
    snaps = sorted(gp_root.glob("*/record.json"))
    return json.loads(snaps[-1].read_text())["sha256"] if snaps else None


def snapshot(spool: Path, session: requests.Session, args) -> bool:
    gp_root = spool / "gp"
    gp_root.mkdir(parents=True, exist_ok=True)
    user, pw = credentials()
    raw = fetch(session, args.base, args.query, user, pw)
    digest = poll.sha256_bytes(raw)
    if digest == latest_sha(gp_root):
        log.info("catalogue unchanged since the last snapshot (sha %s...) - not stored twice", digest[:12])
        return True
    info = describe(raw)
    stamp = poll.utc_now().replace("-", "").replace(":", "")
    d = gp_root / f"{stamp}_{digest[:12]}"
    d.mkdir()
    with gzip.open(d / "gp.json.gz", "wb", compresslevel=6) as gz:
        gz.write(raw)
    poll.write_json_atomic(d / "record.json", {
        "schema": SCHEMA, "source": args.base, "query": args.query, "fetched_utc": poll.utc_now(),
        "sha256": digest, "bytes": len(raw), **info,
        "note": "public general-perturbations catalogue snapshot; hash is of the raw response bytes; "
                "redistributed only under Space-Track's blanket approval for basic SSA data, with citation (D06)"})
    log.info("snapshot %s: %d records, %.1f MB, epochs %s..%s, six-digit ids %d", d.name, info["records"],
             len(raw) / 1e6, info["epoch_min"][:16], info["epoch_max"][:16], info["six_digit_ids"])
    return True


def pause(seconds: float) -> None:
    time.sleep(seconds)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spool", type=Path, required=True)
    ap.add_argument("--base", default=BASE_DEFAULT)
    ap.add_argument("--query", default=QUERY_DEFAULT)
    ap.add_argument("--contact", default=os.environ.get("EPHEMERA_CONTACT"), help="required; goes in the User-Agent")
    ap.add_argument("--interval", type=float, default=7200.0)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--ticks", type=int, default=0)
    ap.add_argument("--log-file", type=Path, default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    import run_cycle
    run_cycle.configure_logging(args.log_file, args.verbose, args.spool)
    if not args.contact or "@" not in args.contact:
        log.error("refusing to run without a contact address (--contact or EPHEMERA_CONTACT)")
        return poll.EXIT_REFUSED
    session = requests.Session()
    session.headers["User-Agent"] = poll.user_agent(args.contact)
    n = 0
    while True:
        n += 1
        try:
            ok = snapshot(args.spool, session, args)
        except Exception as e:  # noqa: BLE001 - logged loudly, retried next pass
            log.error("gp pass %d failed: %s", n, e)
            ok = False
        log.info("gp pass %d: %s", n, "clean" if ok else "RECORDED ERRORS")
        if args.once or (args.ticks and n >= args.ticks):
            return 0 if ok else 1
        try:
            pause(args.interval)
        except KeyboardInterrupt:
            return poll.EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
