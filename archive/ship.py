#!/usr/bin/env python3
"""Ephemera shipper: move each finished cycle into cold storage and, later, free the local disk
(D15). The local spool is a three-day desk; the archive lives in S3 Glacier Deep Archive.

Per cycle whose record is final (status complete or gaps - a recorded gap is shipped too, D09):
  1. pack one uncompressed tar into <spool>/outbox/, hash it (SHA-256) and size it. The tar is
     built from the RECORD, not from whatever *.gz happens to be on disk: every file the record
     names is read, decompressed, and checked against its recorded SHA-256 and byte count as it
     goes in, a file on disk that the record does not name is an error, and a mismatch stops the
     shipment. The poller hashed these bytes when it fetched them; this is the check that they are
     still those bytes now, which is the only moment left to make it before they become the
     archive;
  2. multipart-upload it to s3://<bucket>/cycles/<sha12>/files.tar with StorageClass
     DEEP_ARCHIVE, per-part CRC32 checksums validated by S3 in transit, and the tar's SHA-256 in
     object metadata (S3 offers no full-object SHA-256 for multipart uploads, so the recorded
     SHA-256 is what a restore is verified against - see VERIFY.md);
  3. HEAD the object: size and metadata must match, storage class must be DEEP_ARCHIVE; the cycle
     is then marked shipped in <cycle>/ship.json (the poller's cycle.json is never touched by the
     shipper) and only after that state is on disk is the outbox tar removed. Nothing is destroyed
     before the upload that replaces it is durably recorded;
  4. keep the small records readable without a restore: cycle.json, root.txt, root.txt.ots,
     witness.json and MANIFEST.txt are put beside the tar in STANDARD class, re-synced whenever
     their bytes change;
  5. once a cycle is shipped, verified, and older than --keep-days, delete its local files/ and
     record when. An unshipped cycle is never deleted, whatever the disk says.

A cycle can be shipped with gaps and healed later by a resumed pull. ship.json therefore records a
fingerprint of exactly which files the tar held, and every pass recomputes it from the current
record: if they differ the tar is stale, so the cycle is packed and uploaded again before anything
local is deleted. Without that the cold copy kept the gapped tar while the records beside it were
re-synced to say complete, and then the recovered files were deleted from the disk.

Every failure is logged and recorded in ship.json and the pass returns 1; one bad cycle never
stops the others. The account guard (infra/guard.py) runs first; there is no way to skip it.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
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


class CorruptCycle(RuntimeError):
    """Local bytes no longer match the record. Never shipped, never deleted, always recorded."""


def files_fingerprint(rec: dict) -> str:
    """A digest over the (name, sha256) pairs the record names, in record order.

    This is what a shipped tar is bound to. It is not the Merkle root: the root commits content
    hashes only, so a healed cycle that gains a file, or one whose names changed, has to be visible
    here even where a root would not move."""
    h = hashlib.sha256()
    for f in rec.get("files") or []:
        h.update(f"{f['name']}\x00{f['sha256']}\n".encode())
    return h.hexdigest()


def verify_local_files(cycle_dir: Path, rec: dict) -> None:
    """Every file the record names is present and still hashes to what the record says, and no
    unrecorded file is sitting in files/ waiting to be archived as though it were real."""
    files_dir = cycle_dir / "files"
    named = {f["name"] for f in rec.get("files") or []}
    on_disk = {p.name[:-3] for p in files_dir.glob("*.gz")} if files_dir.exists() else set()
    stray = sorted(on_disk - named)
    if stray:
        raise CorruptCycle(f"{len(stray)} file(s) in files/ that the record does not name, "
                           f"first {stray[0]}")
    missing = sorted(named - on_disk)
    if missing:
        raise CorruptCycle(f"{len(missing)} recorded file(s) missing from files/, first {missing[0]}")


def _checked_bytes(cycle_dir: Path, f: dict) -> bytes:
    """The stored gzip for one recorded file, having confirmed it still holds the recorded bytes."""
    gz = cycle_dir / "files" / (f["name"] + ".gz")
    blob = gz.read_bytes()
    try:
        raw = gzip.decompress(blob)
    except OSError as e:
        raise CorruptCycle(f"{f['name']}: stored gzip is unreadable ({e})") from e
    if len(raw) != f["bytes"] or hashlib.sha256(raw).hexdigest() != f["sha256"]:
        raise CorruptCycle(f"{f['name']}: stored bytes do not match the record")
    return blob


def pack(cycle_dir: Path, outbox: Path, rec: dict) -> Path:
    """One uncompressed tar built from the record: every record file present, then every file the
    record names, each verified against its recorded digest as it is added."""
    outbox.mkdir(parents=True, exist_ok=True)
    verify_local_files(cycle_dir, rec)
    tar_path = outbox / f"{cycle_dir.name}.tar"
    tmp = tar_path.with_suffix(".tar.part")
    with tarfile.open(tmp, "w") as tar:
        for name in RECORD_FILES:
            p = cycle_dir / name
            if p.exists():
                tar.add(p, arcname=f"{cycle_dir.name}/{name}")
        for f in sorted(rec.get("files") or [], key=lambda x: x["name"]):
            blob = _checked_bytes(cycle_dir, f)
            info = tarfile.TarInfo(f"{cycle_dir.name}/files/{f['name']}.gz")
            info.size = len(blob)
            info.mtime = int((cycle_dir / "files" / (f["name"] + ".gz")).stat().st_mtime)
            tar.addfile(info, io.BytesIO(blob))
    os.replace(tmp, tar_path)
    return tar_path


def load_state(cycle_dir: Path) -> dict:
    p = cycle_dir / "ship.json"
    return json.loads(p.read_text()) if p.exists() else {"schema": SCHEMA, "cycle": cycle_dir.name,
                                                          "shipped": None, "records": {}, "error": None}


def needs_upload(state: dict, rec: dict) -> str | None:
    """Why this cycle must be uploaded, or None if the cold copy is already the current one."""
    shipped = state.get("shipped")
    if not shipped:
        return "not yet shipped"
    want = files_fingerprint(rec)
    have = shipped.get("files_fingerprint")
    if have == want:
        return None
    if have is None:
        # Shipped before the tar was bound to a record. The tar does match the record whenever the
        # record was final before the upload ran, and both sides recorded their times, so that is
        # checked rather than assumed: adopting on faith would bless a stale cold copy, and
        # re-uploading everything would cost days of uplink to re-send bytes already there.
        finished, uploaded = rec.get("finished_utc"), shipped.get("uploaded_utc")
        if finished and uploaded and finished <= uploaded:
            return None
        return ("shipped before the tar was bound to a record, and the record was not final when the "
                "upload ran, so the cold copy cannot be shown to match it")
    return ("the record has changed since the tar was built (healed or resumed cycle); "
            "the cold copy is missing files the record now names")


def ship_cycle(cycle_dir: Path, s3, args) -> tuple[bool, bool]:
    """(no error, an upload happened). The second value is what --max-cycles counts: a cycle that
    uploads nothing must not consume the pass budget, or an unfinished cycle sorting earlier by
    hash blocks a finished one every pass, forever."""
    rec = json.loads((cycle_dir / "cycle.json").read_text())
    if rec.get("status") not in ("complete", "gaps"):
        return True, False
    state = load_state(cycle_dir)
    prefix = f"cycles/{cycle_dir.name[6:]}"
    ok = True
    uploaded = False
    try:
        why = needs_upload(state, rec)
        if why:
            key = f"{prefix}/files.tar"
            tar_path = args.spool / "outbox" / f"{cycle_dir.name}.tar"
            log.info("%s: %s", cycle_dir.name, why)
            if not tar_path.exists():
                free = shutil.disk_usage(args.spool).free
                need = sum(p.stat().st_size for p in (cycle_dir / "files").glob("*.gz")) * 1.1 + 50_000_000
                if free < need:
                    raise RuntimeError(f"outbox needs {need / 1e9:.1f} GB free, have {free / 1e9:.1f} GB")
                tar_path = pack(cycle_dir, args.spool / "outbox", rec)
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
                                "files_fingerprint": files_fingerprint(rec),
                                "files_count": len(rec.get("files") or []),
                                "uploaded_utc": poll.utc_now(), "verified_utc": poll.utc_now()}
            state["error"] = None
            # Durable BEFORE destructive. A crash between these two lines used to lose all record of
            # a finished upload, and the next pass replaced the object with a records-only tar.
            poll.write_json_atomic(cycle_dir / "ship.json", state)
            uploaded = True
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

        # Adopt the fingerprint for a cycle shipped before it existed, so the next pass compares
        # rather than reasoning from timestamps again.
        if state["shipped"] and not state["shipped"].get("files_fingerprint") and not needs_upload(state, rec):
            state["shipped"]["files_fingerprint"] = files_fingerprint(rec)
            state["shipped"]["files_count"] = len(rec.get("files") or [])
            state["shipped"]["fingerprint_adopted_utc"] = poll.utc_now()
            log.info("%s: recorded the tar's file fingerprint (shipped before the binding existed)", cycle_dir.name)

        # Retention runs only when the cold copy is the current one. needs_upload() is asked again
        # rather than assumed, so a cycle healed after its tar was written keeps its local files.
        if state["shipped"] and not needs_upload(state, rec) and not state.get("local_files_deleted_utc"):
            age_days = (datetime.now(timezone.utc) - parse_utc(rec["first_seen_utc"])).total_seconds() / 86400
            files_dir = cycle_dir / "files"
            if age_days >= args.keep_days and files_dir.exists():
                shutil.rmtree(files_dir)
                state["local_files_deleted_utc"] = poll.utc_now()
                log.info("%s: local files/ deleted (%.1f days old, shipped and verified)", cycle_dir.name, age_days)
    except CorruptCycle as e:
        state["error"] = f"{poll.utc_now()}: local bytes do not match the record: {e}"[:500]
        log.error("%s: REFUSING to ship, %s", cycle_dir.name, e)
        ok = False
    except Exception as e:  # noqa: BLE001 - recorded loudly; the next cycle still gets its turn
        state["error"] = f"{poll.utc_now()}: {type(e).__name__}: {e}"[:500]
        log.error("%s: shipping failed: %s", cycle_dir.name, e)
        ok = False
    poll.write_json_atomic(cycle_dir / "ship.json", state)
    return ok, uploaded


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
            rec_path = cycle_dir / "cycle.json"
            wants = needs_upload(load_state(cycle_dir), json.loads(rec_path.read_text()))
            if wants and args.max_cycles and uploads >= args.max_cycles:
                continue                    # record syncs and retention still run for shipped cycles
            passed, uploaded = ship_cycle(cycle_dir, s3, args)
            ok = passed and ok
            uploads += int(uploaded)        # only a real upload spends the budget
        log.info("ship pass %d: %s", n, "clean" if ok else "RECORDED ERRORS")
        if args.once or (args.ticks and n >= args.ticks):
            return 0 if ok else 1
        try:
            pause(args.interval)
        except KeyboardInterrupt:
            return poll.EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
