#!/usr/bin/env python3
"""Ephemera shipper: move each finished cycle into cold storage and, later, free the local disk
(D15). The local spool is a three-day desk; the archive lives in S3 Glacier Deep Archive.

Per cycle whose record is final (status complete or gaps - a recorded gap is shipped too, D09):
  1. pack one uncompressed tar - files/*.gz, MANIFEST.txt, cycle.json, root.txt, root.txt.ots,
     witness.json - into <spool>/outbox/, hash it (SHA-256) and size it;
  2. multipart-upload it to s3://<bucket>/cycles/<sha12>/files.tar with StorageClass
     DEEP_ARCHIVE, per-part CRC32 checksums validated by S3 in transit, and the tar's SHA-256 in
     object metadata (S3 offers no full-object SHA-256 for multipart uploads, so the recorded
     SHA-256 is what a restore is verified against - see VERIFY.md);
  3. HEAD the object: size and metadata must match, storage class must be DEEP_ARCHIVE; only
     then is the cycle marked shipped in <cycle>/ship.json (the poller's cycle.json is never
     touched by the shipper) and the outbox tar removed;
  4. keep the small records readable without a restore: cycle.json, root.txt, root.txt.ots,
     witness.json and MANIFEST.txt are put beside the tar in STANDARD class, re-synced whenever
     their bytes change;
  5. once a cycle is shipped, verified, and older than --keep-days, delete its local files/ and
     record when. An unshipped cycle is never deleted, whatever the disk says.

Every failure is logged and recorded in ship.json and the pass returns 1; one bad cycle never
stops the others. The account guard (infra/guard.py) runs first; there is no way to skip it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "infra"))
import poll  # noqa: E402

BUCKET_DEFAULT = "ephemera-space-raw"
REGION_DEFAULT = "eu-west-1"
RECORD_FILES = ("cycle.json", "root.txt", "root.txt.ots", "witness.json", "MANIFEST.txt")
SCHEMA = 1

log = logging.getLogger("ephemera.ship")


def parse_utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def pack(cycle_dir: Path, outbox: Path) -> Path:
    """One uncompressed tar of the cycle: the gzipped files plus every record present."""
    outbox.mkdir(parents=True, exist_ok=True)
    tar_path = outbox / f"{cycle_dir.name}.tar"
    tmp = tar_path.with_suffix(".tar.part")
    with tarfile.open(tmp, "w") as tar:
        for name in RECORD_FILES:
            p = cycle_dir / name
            if p.exists():
                tar.add(p, arcname=f"{cycle_dir.name}/{name}")
        for p in sorted((cycle_dir / "files").glob("*.gz")):
            tar.add(p, arcname=f"{cycle_dir.name}/files/{p.name}")
    os.replace(tmp, tar_path)
    return tar_path


def load_state(cycle_dir: Path) -> dict:
    p = cycle_dir / "ship.json"
    return json.loads(p.read_text()) if p.exists() else {"schema": SCHEMA, "cycle": cycle_dir.name,
                                                          "shipped": None, "records": {}, "error": None}


def ship_cycle(cycle_dir: Path, s3, args) -> bool:
    rec = json.loads((cycle_dir / "cycle.json").read_text())
    if rec.get("status") not in ("complete", "gaps"):
        return True
    state = load_state(cycle_dir)
    prefix = f"cycles/{cycle_dir.name[6:]}"
    ok = True
    try:
        if not state["shipped"]:
            key = f"{prefix}/files.tar"
            tar_path = args.spool / "outbox" / f"{cycle_dir.name}.tar"
            if not tar_path.exists():
                free = shutil.disk_usage(args.spool).free
                need = sum(p.stat().st_size for p in (cycle_dir / "files").glob("*.gz")) * 1.1 + 50_000_000
                if free < need:
                    raise RuntimeError(f"outbox needs {need / 1e9:.1f} GB free, have {free / 1e9:.1f} GB")
                tar_path = pack(cycle_dir, args.spool / "outbox")
            size = tar_path.stat().st_size
            digest = sha256_file(tar_path)
            log.info("%s: uploading %.2f GB tar (sha256 %s...) to s3://%s/%s", cycle_dir.name, size / 1e9,
                     digest[:12], args.bucket, key)
            cfg = TransferConfig(multipart_threshold=args.part_size_mb * 1024 * 1024,
                                 multipart_chunksize=args.part_size_mb * 1024 * 1024, max_concurrency=4)
            s3.upload_file(str(tar_path), args.bucket, key, Config=cfg, ExtraArgs={
                "StorageClass": "DEEP_ARCHIVE", "ChecksumAlgorithm": "CRC32",
                "Metadata": {"sha256": digest, "cycle": cycle_dir.name, "merkle_root": rec.get("merkle_root") or ""}})
            head = s3.head_object(Bucket=args.bucket, Key=key)
            if head["ContentLength"] != size:
                raise RuntimeError(f"size mismatch after upload: {head['ContentLength']} != {size}")
            if head.get("Metadata", {}).get("sha256") != digest:
                raise RuntimeError("metadata sha256 missing or mismatched after upload")
            if head.get("StorageClass") != "DEEP_ARCHIVE":
                raise RuntimeError(f"storage class is {head.get('StorageClass')}, not DEEP_ARCHIVE")
            state["shipped"] = {"bucket": args.bucket, "key": key, "bytes": size, "sha256": digest,
                                "storage_class": "DEEP_ARCHIVE", "etag": head.get("ETag"),
                                "uploaded_utc": poll.utc_now(), "verified_utc": poll.utc_now()}
            state["error"] = None
            tar_path.unlink()
            log.info("%s: shipped and verified (%d bytes)", cycle_dir.name, size)

        for name in RECORD_FILES:               # small records, always readable without a restore
            p = cycle_dir / name
            if not p.exists():
                continue
            digest = sha256_file(p)
            if state["records"].get(name) == digest:
                continue
            s3.put_object(Bucket=args.bucket, Key=f"{prefix}/{name}", Body=p.read_bytes(),
                          StorageClass="STANDARD", ChecksumAlgorithm="CRC32", Metadata={"sha256": digest})
            state["records"][name] = digest

        if state["shipped"] and not state.get("local_files_deleted_utc"):
            age_days = (datetime.now(timezone.utc) - parse_utc(rec["first_seen_utc"])).total_seconds() / 86400
            files_dir = cycle_dir / "files"
            if age_days >= args.keep_days and files_dir.exists():
                shutil.rmtree(files_dir)
                state["local_files_deleted_utc"] = poll.utc_now()
                log.info("%s: local files/ deleted (%.1f days old, shipped and verified)", cycle_dir.name, age_days)
    except Exception as e:  # noqa: BLE001 - recorded loudly; the next cycle still gets its turn
        state["error"] = f"{poll.utc_now()}: {type(e).__name__}: {e}"[:500]
        log.error("%s: shipping failed: %s", cycle_dir.name, e)
        ok = False
    poll.write_json_atomic(cycle_dir / "ship.json", state)
    return ok


def pause(seconds: float) -> None:
    time.sleep(seconds)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spool", type=Path, required=True)
    ap.add_argument("--bucket", default=BUCKET_DEFAULT)
    ap.add_argument("--region", default=REGION_DEFAULT)
    ap.add_argument("--keep-days", type=float, default=3.0)
    ap.add_argument("--part-size-mb", type=int, default=512)
    ap.add_argument("--max-cycles", type=int, default=0,
                    help="ship at most N not-yet-shipped cycles per pass (0 = all); bounds a pass on a slow uplink")
    ap.add_argument("--interval", type=float, default=1800.0)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--ticks", type=int, default=0)
    ap.add_argument("--log-file", type=Path, default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    import run_cycle
    run_cycle.configure_logging(args.log_file, args.verbose, args.spool)

    import guard
    who = guard.enforce()                       # raises GuardRefused; nothing catches it here
    log.info("guard: account %s via profile %s", who["account"], who["profile"])
    s3 = boto3.client("s3", region_name=args.region)

    n = 0
    while True:
        n += 1
        ok = True
        uploads = 0
        for cycle_dir in sorted(args.spool.glob("cycle_*")):
            if not (cycle_dir / "cycle.json").exists():
                continue
            unshipped = not load_state(cycle_dir)["shipped"]
            if unshipped and args.max_cycles and uploads >= args.max_cycles:
                continue                    # record syncs and retention still run for shipped cycles
            ok = ship_cycle(cycle_dir, s3, args) and ok
            uploads += int(unshipped)
        log.info("ship pass %d: %s", n, "clean" if ok else "RECORDED ERRORS")
        if args.once or (args.ticks and n >= args.ticks):
            return 0 if ok else 1
        try:
            pause(args.interval)
        except KeyboardInterrupt:
            return poll.EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
