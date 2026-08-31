#!/usr/bin/env python3
"""Ephemera watcher: keep one spool current with the live feed, one manifest at a time.

Each tick: conditional GET of MANIFEST.txt (If-None-Match on the last ETag seen). On 200, hash the
body and remember the hash. Then, whether the answer was 200 or 304, look at
<spool>/cycle_<sha12>/cycle.json for the current manifest: if it says "complete", heartbeat only;
otherwise run poll.main() for that manifest - so a gapped, interrupted or crashed cycle is retried
on every tick while its manifest is still the current one, resuming via conditional requests.
Every tick rewrites <spool>/heartbeat.json - the last manifest seen, the action taken, the last
exit code, free disk and the count of complete cycles - so a status page can tell a live poller
from a dead one. A pull that ends with exit 4 (interrupted) stops the watcher with exit 4.
--once runs a single tick; --ticks N runs N ticks; both return the last poll exit code (0 when the
cycle was already complete).

This is the only long-running process in the archive layer; it holds no state beyond the spool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import poll  # noqa: E402

log = logging.getLogger("ephemera.run_cycle")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def configure_logging(log_file: Path | None, verbose: bool, spool: Path) -> Path | None:
    """Root logger to a file when asked, or when there is no stderr (pythonw / a windowless
    service), otherwise to stderr. poll.py's own basicConfig is then a no-op, so both modules log
    to the same place. Returns the file used, if any."""
    fmt = "%(asctime)s %(levelname)s %(message)s"
    level = logging.DEBUG if verbose else logging.INFO
    if log_file is None and sys.stderr is None:
        log_file = spool / "run_cycle.log"
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=level, format=fmt, handlers=[logging.FileHandler(log_file, encoding="utf-8")])
    else:
        logging.basicConfig(level=level, format=fmt)
    return log_file


def pause(seconds: float) -> None:
    """The between-tick wait; a seam so tests can act between ticks without touching time.sleep,
    which poll.py's retry backoff also uses."""
    time.sleep(seconds)


def cycle_status(spool: Path, sha: str) -> str | None:
    rec = spool / f"cycle_{sha[:12]}" / "cycle.json"
    if not rec.exists():
        return None
    try:
        return json.loads(rec.read_text()).get("status")
    except (OSError, ValueError) as e:
        log.error("unreadable %s: %s", rec, e)
        return "unreadable"


def count_complete(spool: Path) -> int:
    return sum(1 for p in spool.glob("cycle_*/root.txt"))


def tick(session: requests.Session, args, state: dict) -> tuple[str, int]:
    """One watcher pass. Returns (action, exit_code_of_poll_or_0)."""
    headers = {"If-None-Match": state["etag"]} if state.get("etag") else {}
    r = session.get(f"{args.base}/MANIFEST.txt", headers=headers, timeout=poll.TIMEOUT_S)
    if r.status_code == 304 and state.get("sha"):
        unchanged = True
    else:
        r.raise_for_status()
        state["etag"] = r.headers.get("ETag")
        state["sha"] = hashlib.sha256(r.content).hexdigest()
        unchanged = False
    sha = state["sha"]
    status = cycle_status(args.spool, sha)
    if status == "complete":
        return ("unchanged-304" if unchanged else "skipped-complete"), 0
    log.info("manifest %s (%s) status=%s -> pulling", sha[:12], "unchanged" if unchanged else "new", status)
    rc = poll.main(["--base", args.base, "--spool", str(args.spool), "--workers", str(args.workers),
                    "--contact", args.contact, "--min-free-gb", str(args.min_free_gb)])
    return "pulled", rc


def write_heartbeat(args, state: dict, action: str, rc: int, n: int) -> None:
    hb = {
        "utc": utc_now(),
        "poller": poll.user_agent(args.contact),
        "tick": n,
        "manifest_sha256": state.get("sha"),
        "manifest_etag": state.get("etag"),
        "action": action,
        "last_exit": rc,
        "free_gb": round(shutil.disk_usage(args.spool).free / 1e9, 1),
        "cycles_complete": count_complete(args.spool),
    }
    poll.write_json_atomic(args.spool / "heartbeat.json", hb)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default=poll.BASE_DEFAULT)
    ap.add_argument("--spool", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--contact", default=os.environ.get("EPHEMERA_CONTACT"), help="required; see poll.py")
    ap.add_argument("--min-free-gb", type=float, default=25.0)
    ap.add_argument("--interval", type=float, default=120.0, help="seconds between manifest checks")
    ap.add_argument("--once", action="store_true", help="one tick, then exit with the poll exit code")
    ap.add_argument("--ticks", type=int, default=0, help="stop after N ticks (0 = run until interrupted)")
    ap.add_argument("--log-file", type=Path, default=None,
                    help="append log lines here instead of stderr (required under pythonw, which has no stderr)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    configure_logging(args.log_file, args.verbose, args.spool)
    if not args.contact or "@" not in args.contact:
        log.error("refusing to run without a contact address (--contact or EPHEMERA_CONTACT)")
        return poll.EXIT_REFUSED
    args.spool.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers["User-Agent"] = poll.user_agent(args.contact)
    state: dict = {}
    n = 0
    while True:
        n += 1
        try:
            action, rc = tick(session, args, state)
        except KeyboardInterrupt:
            log.error("watcher interrupted")
            return poll.EXIT_INTERRUPTED
        except Exception as e:  # noqa: BLE001 - logged, heart-beaten as an error, retried next tick
            action, rc = "error", -1
            log.error("tick %d failed: %s", n, e)
        write_heartbeat(args, state, action, rc, n)
        log.info("tick %d: %s rc=%s complete=%d", n, action, rc, count_complete(args.spool))
        if rc == poll.EXIT_INTERRUPTED:
            log.error("pull was interrupted; stopping the watcher")
            return rc
        if args.once or (args.ticks and n >= args.ticks):
            return rc
        try:
            pause(args.interval)
        except KeyboardInterrupt:
            log.error("watcher interrupted")
            return poll.EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
