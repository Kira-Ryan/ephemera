#!/usr/bin/env python3
"""Restore one shipped cycle from Deep Archive and prove the whole evidence chain still holds.

Until this runs, "the raw files are safe in cold storage" is a claim. A drill that only checks the
object's SHA-256 proves far less than it looks: it proves S3 returned the bytes we uploaded, not
that those bytes are the archive the site publishes. So this checks the whole chain, in order:

  1. the restored tar hashes to the SHA-256 recorded in ship.json when it was uploaded;
  2. every files/*.gz member inside it hashes to the digest cycle.json records for that name, and
     the set of names matches exactly (no extra member, none missing);
  3. the Merkle root rebuilt from those digests, in manifest order, equals root.txt (D09);
  4. the files fingerprint recomputed from the record equals the one ship.json bound the tar to.

Only when all four pass does the OpenTimestamps proof over root.txt, and the Bitcoin block it is
attested in, actually cover the bytes that came back.

A Bulk restore takes 12 to 48 hours, so this is resumable: state lives in <spool>/drills/<sha12>.json
and each run advances one step. Run it by hand, or as a scheduled task with --interval.

    restore.py --spool Z:/ephemera/spool                 pick the oldest cycle whose local files
                                                         are gone, request, then poll and verify
    restore.py --spool ... --cycle 1b3b36972d57          drill a named cycle
    restore.py --spool ... --once                        one pass, then exit (for a scheduler)
    restore.py --spool ... --status                      print the drill record and exit

Costs, at the 9.3 GB a cycle currently runs to: Bulk retrieval is a few cents and the restored copy
sits in Standard staging for --days. Downloading it out of AWS is the expensive line at 0.09 USD per
GB, about 0.85 USD. Pass --out to a path on an in-region instance to avoid that; the verification is
identical either way, and P4 recommends in-region for a full-archive restore. For one drill the
egress is worth paying to prove the bytes reach a machine the owner holds.

The account guard runs first. There is no way to skip it.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "infra"))
import poll  # noqa: E402
import ship  # noqa: E402

SCHEMA = 1

log = logging.getLogger("ephemera.restore")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DrillFailed(RuntimeError):
    """The restored bytes are not the archive the record claims. Never swallowed, never retried."""


def pick_cycle(spool: Path) -> Path:
    """The most useful cycle to drill: the oldest whose local files have already been deleted, so
    the cold copy is the only copy and the drill proves something. Falls back to the oldest shipped
    cycle when nothing has been cleaned up yet."""
    shipped, cleaned = [], []
    for d in sorted(spool.glob("cycle_*")):
        state_path = d / "ship.json"
        if not state_path.exists():
            continue
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not (state.get("shipped") or {}).get("key"):
            continue
        shipped.append(d)
        if state.get("local_files_deleted_utc"):
            cleaned.append(d)
    pool = cleaned or shipped
    if not pool:
        raise DrillFailed(f"no shipped cycle found under {spool}")
    return min(pool, key=lambda d: json.loads((d / "ship.json").read_text(encoding="utf-8"))
               ["shipped"]["uploaded_utc"])


def load_drill(spool: Path, sha12: str) -> dict:
    path = spool / "drills" / f"{sha12}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"schema": SCHEMA, "cycle": f"cycle_{sha12}", "requested_utc": None, "restored_utc": None,
            "downloaded_utc": None, "verified_utc": None, "checks": {}, "error": None}


def save_drill(spool: Path, sha12: str, drill: dict) -> None:
    out = spool / "drills"
    out.mkdir(parents=True, exist_ok=True)
    poll.write_json_atomic(out / f"{sha12}.json", drill)


def request_restore(s3, shipped: dict, tier: str, days: int) -> str:
    """Ask for the object back. An object already restored answers RestoreAlreadyInProgress or
    succeeds again harmlessly, so this is safe to re-run."""
    try:
        s3.restore_object(Bucket=shipped["bucket"], Key=shipped["key"],
                          RestoreRequest={"Days": days, "GlacierJobParameters": {"Tier": tier}})
        return "requested"
    except ClientError as e:
        if e.response["Error"]["Code"] == "RestoreAlreadyInProgress":
            return "already in progress"
        raise


def restore_state(s3, shipped: dict) -> tuple[bool, str]:
    """(ready, what the object says). S3 reports progress in the x-amz-restore header, which boto3
    surfaces as Restore: ongoing-request="true" while it works, then "false" with an expiry."""
    head = s3.head_object(Bucket=shipped["bucket"], Key=shipped["key"])
    marker = head.get("Restore")
    if marker is None:
        return False, f"no restore in progress (storage class {head.get('StorageClass', 'STANDARD')})"
    return 'ongoing-request="false"' in marker, marker


def download(s3, shipped: dict, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("downloading %.2f GB from s3://%s/%s", shipped["bytes"] / 1e9, shipped["bucket"], shipped["key"])
    s3.download_file(shipped["bucket"], shipped["key"], str(dest))


def verify(tar_path: Path, cycle_dir: Path, shipped: dict) -> dict:
    """The four checks, in order, each one a named entry in the drill record. Raises DrillFailed on
    the first that does not hold: a restore that half-verifies is a failure, not a partial pass."""
    checks: dict = {}
    rec = json.loads((cycle_dir / "cycle.json").read_text(encoding="utf-8"))

    got = ship.sha256_file(tar_path)
    checks["tar_sha256"] = {"expected": shipped["sha256"], "got": got, "ok": got == shipped["sha256"]}
    if not checks["tar_sha256"]["ok"]:
        raise DrillFailed(f"restored tar hashes to {got[:12]}..., ship.json recorded {shipped['sha256'][:12]}...")
    checks["tar_bytes"] = {"expected": shipped["bytes"], "got": tar_path.stat().st_size,
                           "ok": tar_path.stat().st_size == shipped["bytes"]}

    # Read each member out of the tar rather than extracting the whole thing: a 9 GB cycle should
    # not need a second 9 GB of disk to check. ship.pack names members <cycle>/files/<name>.gz and
    # stores the GZIPPED bytes, while the record's sha256 is of the RAW bytes (archive/poll.py:205,
    # 209 and archive/ship.py:110-121), so each member is decompressed before it is hashed. A
    # member that is no longer a readable gzip is a failure, not a skip.
    prefix = f"{cycle_dir.name}/files/"
    want = {f["name"]: (f["sha256"], f["bytes"]) for f in rec.get("files") or []}
    seen: dict[str, tuple[str, int]] = {}
    unreadable: list[str] = []
    with tarfile.open(tar_path, "r") as tf:
        for member in tf:
            if not member.isfile() or not member.name.startswith(prefix) or not member.name.endswith(".gz"):
                continue
            name = member.name[len(prefix):-len(".gz")]
            fh = tf.extractfile(member)
            if fh is None:
                raise DrillFailed(f"{member.name} is in the tar but has no readable content")
            try:
                raw = gzip.decompress(fh.read())
            except (OSError, EOFError) as e:
                unreadable.append(f"{name} ({e})")
                continue
            seen[name] = (hashlib.sha256(raw).hexdigest(), len(raw))

    missing = sorted(set(want) - set(seen))
    extra = sorted(set(seen) - set(want))
    wrong = sorted(n for n in set(want) & set(seen) if want[n] != seen[n])
    checks["members"] = {"recorded": len(want), "in_tar": len(seen), "missing": missing[:10],
                         "extra": extra[:10], "wrong_digest": wrong[:10], "unreadable": unreadable[:10],
                         "ok": not missing and not extra and not wrong and not unreadable}
    if unreadable:
        raise DrillFailed(f"{len(unreadable)} member(s) are no longer readable gzip, first {unreadable[0]}")
    if not checks["members"]["ok"]:
        raise DrillFailed(f"tar does not match the record: {len(missing)} missing, {len(extra)} extra, "
                          f"{len(wrong)} with a different digest")

    # Manifest order, not sorted order: the root commits the leaves in the order the record lists.
    root = poll.merkle_root([f["sha256"] for f in rec.get("files") or []])
    on_disk = (cycle_dir / "root.txt").read_text(encoding="utf-8").strip() if (cycle_dir / "root.txt").exists() else None
    checks["merkle_root"] = {"rebuilt": root, "root_txt": on_disk, "recorded": rec.get("merkle_root"),
                             "ok": bool(root) and root == on_disk == rec.get("merkle_root")}
    if not checks["merkle_root"]["ok"]:
        raise DrillFailed(f"rebuilt root {str(root)[:12]}... does not match root.txt {str(on_disk)[:12]}...")

    fp = ship.files_fingerprint(rec)
    checks["files_fingerprint"] = {"expected": shipped.get("files_fingerprint"), "got": fp,
                                   "ok": fp == shipped.get("files_fingerprint")}
    if not checks["files_fingerprint"]["ok"]:
        raise DrillFailed("the record no longer matches the fingerprint the tar was bound to")
    return checks


def one_pass(spool: Path, cycle_dir: Path, s3, args) -> bool:
    """Advance the drill one step. Returns True when it is finished and verified."""
    sha12 = cycle_dir.name[6:]
    state = json.loads((cycle_dir / "ship.json").read_text(encoding="utf-8"))
    shipped = state.get("shipped") or {}
    if not shipped.get("key"):
        raise DrillFailed(f"{cycle_dir.name} has no shipped record to restore")
    drill = load_drill(spool, sha12)
    drill["shipped"] = {k: shipped.get(k) for k in ("bucket", "key", "bytes", "sha256", "storage_class")}

    if drill.get("verified_utc"):
        log.info("%s: already verified at %s", cycle_dir.name, drill["verified_utc"])
        return True

    tar_path = Path(args.out) if args.out else spool / "drills" / f"{sha12}.tar"
    try:
        if not drill.get("requested_utc"):
            how = request_restore(s3, shipped, args.tier, args.days)
            drill["requested_utc"] = utc_now()
            drill["tier"] = args.tier
            log.info("%s: restore %s (%s tier, %d day window)", cycle_dir.name, how, args.tier, args.days)
            save_drill(spool, sha12, drill)
            return False

        if not drill.get("restored_utc"):
            ready, marker = restore_state(s3, shipped)
            if not ready:
                waited = (datetime.now(timezone.utc) - ship.parse_utc(drill["requested_utc"])).total_seconds() / 3600
                log.info("%s: still restoring after %.1f h (%s)", cycle_dir.name, waited, marker)
                save_drill(spool, sha12, drill)
                return False
            drill["restored_utc"] = utc_now()
            log.info("%s: restored and readable (%s)", cycle_dir.name, marker)
            save_drill(spool, sha12, drill)

        if not drill.get("downloaded_utc") or not tar_path.exists():
            download(s3, shipped, tar_path)
            drill["downloaded_utc"] = utc_now()
            drill["local_tar"] = str(tar_path)
            save_drill(spool, sha12, drill)

        drill["checks"] = verify(tar_path, cycle_dir, shipped)
        drill["verified_utc"] = utc_now()
        drill["error"] = None
        save_drill(spool, sha12, drill)
        log.info("%s: RESTORE DRILL PASSED - tar sha256, %d members, Merkle root and fingerprint all "
                 "match the record", cycle_dir.name, drill["checks"]["members"]["in_tar"])
        if not args.keep_tar and not args.out:
            tar_path.unlink(missing_ok=True)
            log.info("%s: removed the local copy (pass --keep-tar to keep it)", cycle_dir.name)
        return True
    except (DrillFailed, ClientError, OSError, tarfile.TarError) as e:
        drill["error"] = f"{type(e).__name__}: {e}"
        save_drill(spool, sha12, drill)
        log.error("%s: drill failed: %s", cycle_dir.name, drill["error"])
        raise DrillFailed(drill["error"]) from e


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spool", type=Path, required=True)
    ap.add_argument("--cycle", default=None, help="cycle sha12; default is the oldest whose local files are gone")
    ap.add_argument("--bucket", default=ship.BUCKET_DEFAULT)
    ap.add_argument("--region", default=ship.REGION_DEFAULT)
    ap.add_argument("--tier", choices=["Bulk", "Standard"], default="Bulk",
                    help="Bulk is 12 to 48 h and nearly free; Standard is about 12 h and costs more")
    ap.add_argument("--days", type=int, default=3, help="how long the restored copy stays readable")
    ap.add_argument("--out", default=None, help="where to write the tar (default <spool>/drills/); "
                                                "point at in-region storage to avoid egress")
    ap.add_argument("--keep-tar", action="store_true", help="keep the downloaded tar after a pass")
    ap.add_argument("--interval", type=float, default=3600.0)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--status", action="store_true", help="print the drill record and exit")
    ap.add_argument("--log-file", type=Path, default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    import run_cycle
    run_cycle.configure_logging(args.log_file, args.verbose, args.spool)

    cycle_dir = (args.spool / f"cycle_{args.cycle}") if args.cycle else pick_cycle(args.spool)
    if not (cycle_dir / "ship.json").exists():
        log.error("%s has no ship.json - nothing to restore", cycle_dir.name)
        return 2

    if args.status:
        print(json.dumps(load_drill(args.spool, cycle_dir.name[6:]), indent=1))
        return 0

    import guard
    who = guard.enforce()                       # raises GuardRefused; nothing catches it here
    log.info("guard: account %s via profile %s", who["account"], who["profile"])
    s3 = boto3.client("s3", region_name=args.region)

    while True:
        try:
            if one_pass(args.spool, cycle_dir, s3, args):
                return 0
        except DrillFailed:
            return 1
        if args.once:
            return 3                            # not finished yet, and that is not an error
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            return poll.EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
