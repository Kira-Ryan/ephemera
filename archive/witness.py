#!/usr/bin/env python3
"""Ephemera witness: third-party evidence for every complete cycle (D07, D16).

For each cycle in the spool that has a root.txt it
  1. stamps root.txt with OpenTimestamps -> root.txt.ots (native `ots` where it runs, else a
     python:3.12-slim Docker container - the client does not run on Windows, probe P2);
  2. retries `ots upgrade` at most every --upgrade-every seconds until the proof carries a
     Bitcoin block attestation, and records the block height;
  3. while the cycle is still the CURRENT one, submits MANIFEST.txt plus --samples files to the
     Wayback Machine and fetches every capture's id_ copy back, verifying
     sha256(gunzip(copy)) == the recorded hash (the id_ copy is the origin's gzip transfer
     encoding, probe P2b). A cycle superseded before its captures were made gets
     wayback.skipped with the reason - the loss is recorded, never hidden.

Sample selection (deterministic, unpredictable before the root exists, re-implementable from this
sentence): index_k = int(sha256(ascii(root_hex) + ":" + ascii(k)), 16) mod N for k = 0, 1, 2, ...,
skipping repeats, until --samples distinct indices into the cycle's recorded file list.

Everything learned or failed lands in <cycle>/witness.json (written atomically). Witnessing never
touches cycle.json and never blocks the poller or shipping (D16). Exit code of a pass: 0 when all
due work succeeded, 1 when any witnessing step recorded an error.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import poll  # noqa: E402

WAYBACK_DEFAULT = "https://web.archive.org"
HEARTBEAT_FRESH_S = 900
ATTESTATION_RE = re.compile(r"BitcoinBlockHeaderAttestation\((\d+)\)")
SCHEMA = 1

log = logging.getLogger("ephemera.witness")


def parse_utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def sample_indices(root_hex: str, n_files: int, samples: int) -> list[int]:
    """The documented SHA-256 chain: unpredictable before the root exists, reproducible after."""
    picked: list[int] = []
    k = 0
    while len(picked) < min(samples, n_files):
        i = int(hashlib.sha256(f"{root_hex}:{k}".encode("ascii")).hexdigest(), 16) % n_files
        if i not in picked:
            picked.append(i)
        k += 1
    return sorted(picked)


class OtsRunner:
    """Runs the OpenTimestamps client against one cycle directory, natively or through Docker."""

    def __init__(self, mode: str):
        if mode == "auto":
            mode = "ots" if shutil.which("ots") else "docker"
        if mode == "docker" and not shutil.which("docker"):
            raise RuntimeError("neither `ots` nor `docker` is available for OpenTimestamps stamping")
        self.mode = mode

    def _run(self, cycle_dir: Path, *ots_args: str) -> subprocess.CompletedProcess:
        if self.mode == "ots":
            cmd = ["ots", *ots_args]
            return subprocess.run(cmd, cwd=cycle_dir, capture_output=True, text=True, errors="replace", timeout=600)
        volume = f"{cycle_dir.resolve()}:/w"
        shell = f"pip install -q opentimestamps-client && cd /w && ots {' '.join(ots_args)}"
        return subprocess.run(["docker", "run", "--rm", "-v", volume, "python:3.12-slim", "sh", "-c", shell],
                              capture_output=True, text=True, errors="replace", timeout=900)

    def _check(self, r: subprocess.CompletedProcess, what: str) -> None:
        if r.returncode != 0:
            raise RuntimeError(f"{what} failed (rc {r.returncode}): {(r.stderr or r.stdout).strip()[:400]}")

    def stamp(self, cycle_dir: Path) -> None:
        self._check(self._run(cycle_dir, "stamp", "root.txt"), "ots stamp")

    def upgrade(self, cycle_dir: Path) -> None:
        # `ots upgrade` is non-zero while the attestation is still pending; that is not an error.
        self._run(cycle_dir, "upgrade", "root.txt.ots")

    def info(self, cycle_dir: Path) -> str:
        r = self._run(cycle_dir, "info", "root.txt.ots")
        self._check(r, "ots info")
        return r.stdout


def make_ots_runner(mode: str) -> OtsRunner:
    return OtsRunner(mode)


def current_manifest_sha(spool: Path, session: requests.Session, base: str) -> str | None:
    """The sha of the manifest currently served: from a fresh watcher heartbeat when there is one
    (same spool, same machine by design), else by asking the feed directly."""
    hb_path = spool / "heartbeat.json"
    try:
        hb = json.loads(hb_path.read_text())
        if (datetime.now(timezone.utc) - parse_utc(hb["utc"])).total_seconds() < HEARTBEAT_FRESH_S:
            return hb.get("manifest_sha256")
    except (OSError, ValueError, KeyError):
        pass
    try:
        r = session.get(f"{base}/MANIFEST.txt", timeout=poll.TIMEOUT_S)
        r.raise_for_status()
        return poll.sha256_bytes(r.content)
    except requests.RequestException as e:
        log.error("cannot determine the current manifest: %s", e)
        return None


def verified_sha(body: bytes) -> str:
    """The id_ copy is the origin's transfer encoding; the witness check gunzips when needed."""
    try:
        return poll.sha256_bytes(gzip.decompress(body))
    except (OSError, gzip.BadGzipFile):
        return poll.sha256_bytes(body)


def capture(session: requests.Session, wayback: str, url: str, expected_sha: str) -> dict:
    """One Save-Page-Now round trip: submit, read the capture timestamp, fetch the id_ copy back,
    re-hash. Returns the witness entry; an entry with an `error` key is a recorded failure."""
    entry: dict = {"url": url, "submitted_utc": poll.utc_now()}
    r = session.get(f"{wayback}/save/{url}", timeout=300)
    if r.status_code == 429:
        entry["error"] = "429 rate limited by Save-Page-Now"
        return entry
    m = re.search(r"/web/(\d{14})", r.url)
    if not m:
        entry["error"] = f"no capture timestamp in SPN response (HTTP {r.status_code}, url {r.url[:120]})"
        return entry
    entry["timestamp"] = m.group(1)
    entry["id_url"] = f"{wayback}/web/{m.group(1)}id_/{url}"
    copy = session.get(entry["id_url"], timeout=300)
    if copy.status_code != 200:
        entry["error"] = f"id_ fetch HTTP {copy.status_code}"
        return entry
    got = verified_sha(copy.content)
    entry["sha256_of_copy"] = got
    entry["verified"] = got == expected_sha
    if not entry["verified"]:
        entry["error"] = f"id_ copy hash mismatch: got {got[:16]}..., recorded {expected_sha[:16]}..."
    return entry


def ots_step(target_dir: Path, ots: dict, runner: OtsRunner | None, args) -> bool:
    """One tick of the stamping lifecycle for any directory holding a root.txt: stamp it if there
    is no proof yet, otherwise retry the upgrade (at most every --upgrade-every seconds) until the
    proof carries a Bitcoin block height. Used for cycle roots and daily roots alike."""
    try:
        if runner is None:
            ots.setdefault("error", "no OTS runner available on this host")
            return False
        if not (target_dir / "root.txt.ots").exists():
            runner.stamp(target_dir)
            ots.update({"stamped_utc": poll.utc_now(), "runner": runner.mode, "error": None})
            log.info("%s: stamped root.txt", target_dir.name)
        elif not ots.get("attested"):
            last = ots.get("last_upgrade_attempt_utc")
            due = last is None or (datetime.now(timezone.utc) - parse_utc(last)).total_seconds() >= args.upgrade_every
            if due:
                runner.upgrade(target_dir)
                ots["last_upgrade_attempt_utc"] = poll.utc_now()
                m = ATTESTATION_RE.search(runner.info(target_dir))
                if m:
                    ots["attested"] = {"block_height": int(m.group(1)), "upgraded_utc": poll.utc_now()}
                    log.info("%s: attested at Bitcoin block %s", target_dir.name, m.group(1))
        return True
    except (RuntimeError, subprocess.SubprocessError, OSError) as e:
        ots["error"] = str(e)[:400]
        log.error("%s: OTS step failed: %s", target_dir.name, e)
        return False


def witness_daily(spool: Path, runner: OtsRunner | None, args) -> bool:
    """D16: for every UTC day strictly before today, build daily/<date>/root.txt - the D09
    construction over that day's complete-cycle roots in first_seen_utc order - record which
    cycles entered (and how many gapped cycles could not), and run the same stamping lifecycle
    on it as on cycle roots. The day's root is built once and never rebuilt."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    days: dict[str, list[dict]] = {}
    gapped: dict[str, int] = {}
    for cdir in sorted(spool.glob("cycle_*")):
        rec_path = cdir / "cycle.json"
        if not rec_path.exists():
            continue
        rec = json.loads(rec_path.read_text())
        date = (rec.get("first_seen_utc") or "")[:10]
        if not date or date >= today:
            continue
        if rec.get("merkle_root"):
            days.setdefault(date, []).append(
                {"cycle": rec["cycle"], "first_seen_utc": rec["first_seen_utc"], "merkle_root": rec["merkle_root"]})
        else:
            gapped[date] = gapped.get(date, 0) + 1
    ok = True
    for date, cycles in sorted(days.items()):
        ddir = spool / "daily" / date
        d_path = ddir / "daily.json"
        if (ddir / "root.txt").exists():
            d = json.loads(d_path.read_text())
        else:
            cycles.sort(key=lambda c: c["first_seen_utc"])
            root = poll.merkle_root([c["merkle_root"] for c in cycles])
            ddir.mkdir(parents=True, exist_ok=True)
            d = {"schema": 1, "date": date, "built_utc": poll.utc_now(), "cycles": cycles,
                 "gapped_cycles_excluded": gapped.get(date, 0), "merkle_root": root,
                 "note": "leaves are the day's complete-cycle roots in first_seen_utc order; D09 construction",
                 "ots": {}}
            poll.write_json_atomic(d_path, d)
            poll.write_bytes_atomic(ddir / "root.txt", (root + "\n").encode("ascii"))
            log.info("daily %s: root over %d cycle root(s)%s", date, len(cycles),
                     f" ({d['gapped_cycles_excluded']} gapped excluded)" if gapped.get(date) else "")
        ok = ots_step(ddir, d["ots"], runner, args) and ok
        poll.write_json_atomic(d_path, d)
    return ok


def witness_cycle(cycle_dir: Path, session: requests.Session, runner: OtsRunner | None,
                  args, current_sha: str | None) -> bool:
    """Do whatever witnessing is due for one complete cycle. Returns True if no step errored."""
    rec = json.loads((cycle_dir / "cycle.json").read_text())
    root = rec.get("merkle_root")
    if not root:
        return True  # only complete cycles are witnessed; gaps are the poller's loud problem
    w_path = cycle_dir / "witness.json"
    w = json.loads(w_path.read_text()) if w_path.exists() else {
        "schema": SCHEMA, "cycle": cycle_dir.name, "merkle_root": root,
        "sample_rule": "index_k = int(sha256(root_hex + ':' + str(k)), 16) mod n_files, distinct, sorted",
        "ots": {}, "wayback": {}}
    ok = True

    ok = ots_step(cycle_dir, w["ots"], runner, args) and ok

    wb = w["wayback"]
    if not wb.get("skipped") and current_sha is not None:
        def pending(entry: dict) -> bool:
            return not entry.get("verified") and not entry.get("gave_up")

        is_current = rec["manifest_sha256"] == current_sha
        pending_manifest = pending(wb.get("manifest") or {})
        names = [f["name"] for f in rec["files"]]
        idx = sample_indices(root, len(names), args.samples)
        samples = wb.setdefault("samples", {})
        pending_files = [i for i in idx if pending(samples.get(str(i), {}))]
        if not is_current:
            if pending_manifest or pending_files:
                wb["skipped"] = (f"cycle superseded before witnessing completed: "
                                 f"{int(pending_manifest)} manifest + {len(pending_files)} sample captures never made")
                log.warning("%s: %s", cycle_dir.name, wb["skipped"])
                ok = False
        else:
            def attempt(prev: dict, entry: dict, label: str) -> dict:
                """Carry the attempt count; after --max-capture-attempts failures the entry gives
                up - the loss is recorded loudly ONCE and never retried or re-flagged (a capture
                Wayback keeps refusing must not turn every later pass red)."""
                nonlocal ok
                entry["attempts"] = (prev or {}).get("attempts", 0) + 1
                if not entry.get("verified"):
                    ok = False
                    if entry["attempts"] >= args.max_capture_attempts:
                        entry["gave_up"] = poll.utc_now()
                        log.warning("%s: giving up on capturing %s after %d attempts (%s)",
                                    cycle_dir.name, label, entry["attempts"], entry.get("error", "?"))
                return entry

            try:
                if pending_manifest:
                    # MANIFEST.txt is the one URL that never changes, and Wayback de-duplicates
                    # repeat captures of an unchanged URL by handing back the previous snapshot
                    # (measured 2 Sep 2026: the copy hashed to the PREVIOUS cycle's manifest).
                    # A per-cycle query gives each manifest its own capture; the origin serves
                    # identical bytes with or without it (verified), and the copy is still
                    # re-hashed against this cycle's recorded manifest sha.
                    manifest_url = f"{args.base}/MANIFEST.txt?cycle={rec['manifest_sha256'][:12]}"
                    wb["manifest"] = attempt(wb.get("manifest"),
                                             capture(session, args.wayback, manifest_url,
                                                     rec["manifest_sha256"]), "MANIFEST.txt")
                for i in pending_files:
                    pause(args.capture_gap)
                    f = rec["files"][i]
                    samples[str(i)] = attempt(samples.get(str(i)), {
                        "name": f["name"],
                        **capture(session, args.wayback, f"{args.base}/{f['name']}", f["sha256"])}, f["name"])
            except requests.RequestException as e:
                wb["last_error"] = f"{poll.utc_now()}: {e}"[:400]
                log.error("%s: Wayback step failed: %s", cycle_dir.name, e)
                ok = False

    poll.write_json_atomic(w_path, w)
    return ok


def pause(seconds: float) -> None:
    time.sleep(seconds)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spool", type=Path, required=True)
    ap.add_argument("--base", default=poll.BASE_DEFAULT)
    ap.add_argument("--wayback", default=WAYBACK_DEFAULT)
    ap.add_argument("--samples", type=int, default=10)
    ap.add_argument("--upgrade-every", type=float, default=3600.0,
                    help="seconds between ots upgrade attempts per still-pending proof")
    ap.add_argument("--capture-gap", type=float, default=12.0,
                    help="seconds between Save-Page-Now submissions; ~8 rapid unauthenticated "
                         "captures trip Wayback's 429 limiter (measured 31 Aug 2026)")
    ap.add_argument("--max-capture-attempts", type=int, default=5,
                    help="failed capture attempts per item before the loss is recorded once and "
                         "never retried (Wayback throttles repeat captures of one URL)")
    ap.add_argument("--ots", choices=["auto", "ots", "docker"], default="auto")
    ap.add_argument("--contact", default=os.environ.get("EPHEMERA_CONTACT"), help="required; goes in the User-Agent")
    ap.add_argument("--interval", type=float, default=300.0)
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
    try:
        runner: OtsRunner | None = make_ots_runner(args.ots)
    except RuntimeError as e:
        log.error("%s - stamping will be recorded as failed until one is available", e)
        runner = None

    n = 0
    while True:
        n += 1
        ok = True
        current = current_manifest_sha(args.spool, session, args.base)
        for cycle_dir in sorted(args.spool.glob("cycle_*")):
            if (cycle_dir / "cycle.json").exists():
                try:
                    ok = witness_cycle(cycle_dir, session, runner, args, current) and ok
                except Exception as e:  # noqa: BLE001 - one bad cycle must not stop the others (D16)
                    log.error("%s: witnessing crashed: %s", cycle_dir.name, e)
                    ok = False
        try:
            ok = witness_daily(args.spool, runner, args) and ok
        except Exception as e:  # noqa: BLE001 - the daily root must not stop the loop either
            log.error("daily-root step crashed: %s", e)
            ok = False
        log.info("witness pass %d: %s", n, "clean" if ok else "RECORDED ERRORS")
        if args.once or (args.ticks and n >= args.ticks):
            return 0 if ok else 1
        try:
            pause(args.interval)
        except KeyboardInterrupt:
            log.error("witness interrupted")
            return poll.EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
