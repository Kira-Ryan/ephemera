#!/usr/bin/env python3
"""Ephemera poller: pull one cycle of the public Starlink ephemerides and record it.

One run = one cycle. It fetches MANIFEST.txt, downloads every listed file with a bounded worker
pool, stores each file gzipped under a cycle directory named by the manifest's SHA-256, records the
raw SHA-256, ETag, Last-Modified and size per file, and writes a cycle record carrying a Merkle
root over the raw hashes in manifest order. Failures are counted, listed and cause a non-zero exit;
they are never silently retried into an "installed" cycle with holes.

Exit codes:
  0  complete - every listed file recorded, root.txt written
  2  gaps - some listed files failed, or the manifest had unusable entries; record kept, no root
  3  partial - a --limit test slice; written under <spool>/partial/, never gets a root
  4  interrupted - SIGINT/SIGTERM; record written with what was recorded so far, no root
  5  refused before any download - no contact address, disk below the floor, manifest empty,
     unreachable or undecodable
An unexpected error inside the download loop (for example the spool volume filling up) stops the
worker pool, writes the record with `status: error`, and re-raises, so the process exits non-zero
with a traceback rather than leaving workers downloading with nobody collecting.

Clean-room: standard library plus `requests`. No other project's code was consulted (D02).

Merkle construction (D09 - do not change silently, it alters every subsequent root): leaves are
the raw SHA-256 digests in manifest order; each layer pairs adjacent nodes with
SHA-256(left || right); an odd trailing node is paired with a copy of itself.

Cycle identity (D10, D11): directory `cycle_<manifest sha256[:12]>` with no wall-clock component,
so a resume across midnight and a second poller on the same manifest share one identity.
root.txt (D12): exactly 64 lowercase hex characters followed by a single LF; written atomically,
and removed again if a later run of the same cycle ends without a root.
"""
from __future__ import annotations

import _thread
import argparse
import gzip
import hashlib
import json
import logging
import os
import re
import shutil
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DEFAULT = "https://api.starlink.com/public-files/ephemerides"
RETRIES = 3
BACKOFF_S = 2.0
TIMEOUT_S = 120
FLUSH_EVERY = 200          # completions between atomic rewrites of the ETag cache
RECORD_SCHEMA = 2          # bump when any field meaning or the Merkle construction changes (D09)
NAME_OK = re.compile(r"[A-Za-z0-9._-]+")

EXIT_OK, EXIT_GAPS, EXIT_PARTIAL, EXIT_INTERRUPTED, EXIT_REFUSED = 0, 2, 3, 4, 5

log = logging.getLogger("ephemera.poll")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def user_agent(contact: str) -> str:
    return f"ephemera-poller/0.2 (+archive of published ephemerides; contact: {contact})"


def merkle_root(hex_leaves: list[str]) -> str | None:
    layer = [bytes.fromhex(h) for h in hex_leaves]
    if not layer:
        return None
    while len(layer) > 1:
        if len(layer) % 2:
            layer.append(layer[-1])
        layer = [hashlib.sha256(layer[i] + layer[i + 1]).digest() for i in range(0, len(layer), 2)]
    return layer[0].hex()


def name_problem(name: str) -> str | None:
    """Why a manifest entry cannot be used as a file name under files/, or None if it can."""
    if not name or name in (".", ".."):
        return "empty or dot entry"
    if "/" in name or "\\" in name:
        return "path separator"
    if ":" in name or any(ord(c) < 32 for c in name):
        return "drive or control character"
    if len(name) > 200:
        return "name longer than 200 characters"
    if not NAME_OK.fullmatch(name):
        return "character outside [A-Za-z0-9._-]"
    return None


def parse_manifest(content: bytes) -> list[str]:
    """Lines of MANIFEST.txt as listed. A UTF-8 BOM is dropped; only LF ends a line (a stray CR or
    other control character inside a line stays in the entry so name_problem() rejects it)."""
    text = content.decode("utf-8-sig", "strict")
    return [ln.strip(" \t\r") for ln in text.split("\n") if ln.strip(" \t\r")]


def classify_manifest(listed: list[str]) -> tuple[list[str], list[dict]]:
    """Split the listed entries into pullable names (first occurrence, manifest order) and
    anomalies - one per offending LINE, so counts always sum to the listed total. Duplicates are
    detected case-insensitively because the spool may sit on a case-insensitive filesystem."""
    names: list[str] = []
    anomalies: list[dict] = []
    seen: dict[str, str] = {}
    for i, entry in enumerate(listed, 1):
        problem = name_problem(entry)
        if problem is None:
            key = entry.lower()
            if key in seen:
                problem = "duplicate manifest entry" if seen[key] == entry else "duplicate manifest entry (case-insensitive)"
            else:
                seen[key] = entry
                names.append(entry)
                continue
        anomalies.append({"line": i, "entry": entry, "reason": problem})
    return names, anomalies


def fetch_manifest(session: requests.Session, base: str) -> tuple[bytes, list[str], dict]:
    r = session.get(f"{base}/MANIFEST.txt", timeout=TIMEOUT_S)
    r.raise_for_status()
    headers = {"etag": r.headers.get("ETag"), "last_modified": r.headers.get("Last-Modified")}
    return r.content, parse_manifest(r.content), headers


def write_json_atomic(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1))
    os.replace(tmp, path)


def write_bytes_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def fetch_one(session: requests.Session, base: str, name: str, dest: Path,
              etag_cache: dict, cache_lock: threading.Lock, stop: threading.Event) -> dict:
    """Download one file, gzip it to dest, return its record. Raises on final failure."""
    url = f"{base}/{name}"
    headers = {}
    with cache_lock:
        cached = dict(etag_cache.get(name) or {})
    if cached and dest.exists():
        # Resume: the live feed honours If-None-Match (verified, P1); If-Modified-Since is the
        # fallback should ETags ever disappear, and is what plain servers honour.
        if cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        if cached.get("last_modified"):
            headers["If-Modified-Since"] = cached["last_modified"]
    last_err: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        if stop.is_set():
            raise RuntimeError(f"{name}: interrupted before attempt {attempt}")
        try:
            r = session.get(url, headers=headers, timeout=TIMEOUT_S)
            if r.status_code == 304:
                if headers and cached and dest.exists():
                    return {**cached, "name": name, "status": "unchanged-304", "attempts": attempt}
                raise RuntimeError("304 Not Modified to a request that sent no validator")
            r.raise_for_status()
            raw = r.content
            if len(raw) < 1000 or not raw.startswith(b"created:"):
                raise RuntimeError(f"unexpected body: {len(raw)} bytes, head={raw[:40]!r}")
            digest = sha256_bytes(raw)
            tmp = dest.with_suffix(dest.suffix + ".part")
            with gzip.open(tmp, "wb", compresslevel=6) as gz:
                gz.write(raw)
            os.replace(tmp, dest)
            rec = {
                "name": name,
                "sha256": digest,
                "bytes": len(raw),
                "etag": r.headers.get("ETag"),
                "last_modified": r.headers.get("Last-Modified"),
                "fetched_utc": utc_now(),
                "status": "fetched",
                "attempts": attempt,
            }
            with cache_lock:
                etag_cache[name] = {k: rec[k] for k in ("sha256", "bytes", "etag", "last_modified", "fetched_utc")}
            return rec
        except Exception as e:  # noqa: BLE001 - every failure is logged and re-raised after RETRIES
            last_err = e
            log.warning("attempt %d/%d failed for %s: %s", attempt, RETRIES, name, e)
            if attempt < RETRIES and not stop.is_set():
                time.sleep(BACKOFF_S * attempt)
    raise RuntimeError(f"{name}: failed after {RETRIES} attempts: {last_err}")


def _install_sigterm_as_interrupt() -> None:
    """Make SIGTERM behave like Ctrl-C so systemd stop produces an 'interrupted' record."""
    if threading.current_thread() is not threading.main_thread():
        return
    try:
        signal.signal(signal.SIGTERM, lambda *_: _thread.interrupt_main())
    except (ValueError, AttributeError, OSError):  # not available on this platform/thread
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default=BASE_DEFAULT)
    ap.add_argument("--spool", type=Path, required=True, help="root directory for cycle folders")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0,
                    help="pull only the first N files as a test slice (written under <spool>/partial/, no root)")
    ap.add_argument("--contact", default=os.environ.get("EPHEMERA_CONTACT"),
                    help="contact address sent in the User-Agent (or env EPHEMERA_CONTACT); required")
    ap.add_argument("--min-free-gb", type=float, default=25.0,
                    help="refuse to start a cycle when the spool volume has less free space than this")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    _install_sigterm_as_interrupt()

    if not args.contact or "@" not in args.contact:
        log.error("refusing to poll without a contact address (--contact or EPHEMERA_CONTACT)")
        return EXIT_REFUSED
    args.spool.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(args.spool).free / 1e9
    if free_gb < args.min_free_gb:
        log.error("refusing to start: %.1f GB free on the spool volume, floor is %.1f GB", free_gb, args.min_free_gb)
        return EXIT_REFUSED

    session = requests.Session()
    session.headers["User-Agent"] = user_agent(args.contact)
    # requests defaults to a 10-connection pool per host; size it to the worker count so 16 workers
    # do not thrash the pool (observed as "Connection pool is full" warnings in the first test run).
    adapter = requests.adapters.HTTPAdapter(pool_connections=args.workers, pool_maxsize=args.workers)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    started = utc_now()
    t0 = time.monotonic()

    try:
        manifest_bytes, listed, manifest_headers = fetch_manifest(session, args.base)
    except (requests.RequestException, UnicodeDecodeError) as e:
        log.error("refusing to start: MANIFEST.txt unavailable or undecodable: %s", e)
        return EXIT_REFUSED
    if not listed:
        log.error("MANIFEST.txt is empty - refusing to record an empty cycle")
        return EXIT_REFUSED
    manifest_sha = sha256_bytes(manifest_bytes)
    names, anomalies = classify_manifest(listed)   # anomalies are gaps (D09): loud, no root

    partial = {"limit": args.limit} if args.limit else None
    to_pull = names[: args.limit] if args.limit else names
    root_dir = args.spool / "partial" if partial else args.spool
    cycle_dir = root_dir / f"cycle_{manifest_sha[:12]}"
    files_dir = cycle_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    (cycle_dir / "MANIFEST.txt").write_bytes(manifest_bytes)
    record_path = cycle_dir / "cycle.json"
    root_path = cycle_dir / "root.txt"
    prior = json.loads(record_path.read_text()) if record_path.exists() else {}
    first_seen = prior.get("first_seen_utc") or started
    log.info("cycle %s: manifest sha256=%s listed=%d pulling=%d anomalies=%d%s",
             cycle_dir.name, manifest_sha, len(listed), len(to_pull), len(anomalies),
             f" (--limit {args.limit}: partial slice, no root)" if partial else "")

    cache_path = cycle_dir / "etag_cache.json"
    etag_cache: dict = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    cache_lock = threading.Lock()
    stop = threading.Event()

    def flush_cache() -> None:
        with cache_lock:
            snapshot = dict(etag_cache)
        write_json_atomic(cache_path, snapshot)

    records: dict[str, dict] = {}
    failures: dict[str, str] = {}          # download failures by name; anomalies are listed separately
    summary: dict = {
        "schema": RECORD_SCHEMA,
        "cycle": cycle_dir.name,
        "base": args.base,
        "manifest_sha256": manifest_sha,
        "manifest_headers": manifest_headers,
        "first_seen_utc": first_seen,
        "started_utc": started,
        "finished_utc": None,
        "status": "in-progress",
        "wall_seconds": None,
        "files_listed": len(listed),
        "files_recorded": 0,
        "files_failed": len(anomalies),
        "files_not_attempted": len(names),
        "bytes_raw": 0,
        "merkle_root": None,
        "merkle_note": "root is present only when every listed line is a distinct valid name and every file "
                       "was recorded in this or a resumed run; partial, interrupted and gapped cycles have no root",
        "partial": partial,
        "manifest_changed_during_pull": None,
        "manifest_anomalies": anomalies,
        "poller": user_agent(args.contact),
        "error": None,
        "failures": failures,
        "files": [],
    }
    write_json_atomic(record_path, summary)

    def finish(status: str, **extra) -> None:
        ordered = [records[n] for n in names if n in records]
        not_attempted = [n for n in names if n not in records and n not in failures]
        summary.update({
            "finished_utc": utc_now(),
            "status": status,
            "wall_seconds": round(time.monotonic() - t0, 1),
            "files_recorded": len(ordered),
            "files_failed": len(failures) + len(anomalies),
            "files_not_attempted": len(not_attempted),
            "bytes_raw": sum(r["bytes"] for r in ordered),
            "failures": failures,
            "files": ordered,
            **extra,
        })

    interrupted = False
    abort: BaseException | None = None
    pool = ThreadPoolExecutor(max_workers=args.workers)
    pending = {pool.submit(fetch_one, session, args.base, n, files_dir / f"{n}.gz", etag_cache, cache_lock, stop): n
               for n in to_pull}
    done = 0
    try:
        for fut in as_completed(list(pending)):
            n = pending.pop(fut)
            try:
                records[n] = fut.result()
            except Exception as e:  # noqa: BLE001
                failures[n] = str(e)
                log.error("FAILED %s", e)
            done += 1
            if done % FLUSH_EVERY == 0:
                flush_cache()
            if done % 500 == 0 or done == len(to_pull):
                log.info("progress %d/%d (%d failed) %.0fs", done, len(to_pull), len(failures), time.monotonic() - t0)
        pool.shutdown(wait=True)
    except BaseException as e:  # noqa: BLE001 - stop the pool on ANY exit from the loop, then decide
        stop.set()
        interrupted = isinstance(e, KeyboardInterrupt)
        if interrupted:
            log.error("interrupted: cancelling queued downloads and waiting for in-flight ones")
        else:
            abort = e
            log.error("download loop aborted by %s: %s - stopping workers", type(e).__name__, e)
        try:
            pool.shutdown(wait=True, cancel_futures=True)
        except KeyboardInterrupt:
            log.error("second interrupt: not waiting for in-flight downloads")
            pool.shutdown(wait=False, cancel_futures=True)
        for fut, n in pending.items():
            if fut.done() and not fut.cancelled():
                try:
                    records[n] = fut.result()
                except Exception as e2:  # noqa: BLE001
                    failures[n] = str(e2)
    try:
        flush_cache()
    except OSError as e:
        log.error("could not write etag_cache.json: %s", e)
        summary["cache_flush_error"] = str(e)

    if abort is not None:
        finish("error", error=f"{type(abort).__name__}: {abort}")
        try:
            write_json_atomic(record_path, summary)
        except OSError as e:
            log.error("could not write the error record either: %s", e)
        raise abort

    end_manifest = None
    if not interrupted:
        try:
            end_bytes, _, _ = fetch_manifest(session, args.base)
            end_sha = sha256_bytes(end_bytes)
            if end_sha != manifest_sha:
                end_manifest = {"end_sha256": end_sha, "checked_utc": utc_now()}
                log.warning("manifest changed during the pull: start %s end %s", manifest_sha[:12], end_sha[:12])
        except KeyboardInterrupt:
            interrupted = True
            log.error("interrupted during the end-of-pull manifest check")
        except Exception as e:  # noqa: BLE001 - the re-check explains gaps; its own failure is recorded, not fatal
            end_manifest = {"recheck_error": str(e), "checked_utc": utc_now()}
            log.warning("manifest re-check failed: %s", e)

    complete = (not partial and not interrupted and not anomalies and not failures
                and all(n in records for n in names))
    root = merkle_root([records[n]["sha256"] for n in names]) if complete else None
    status = "interrupted" if interrupted else "partial" if partial else "complete" if root else "gaps"
    finish(status, merkle_root=root, manifest_changed_during_pull=end_manifest)
    write_json_atomic(record_path, summary)
    if root:
        write_bytes_atomic(root_path, (root + "\n").encode("ascii"))
    elif root_path.exists():
        root_path.unlink()
        log.warning("removed stale root.txt: this run of %s ended as %s", cycle_dir.name, status)
    log.info("done: %s %d/%d files, %d failed, %d not attempted, %.1f MB raw, root=%s, %.0fs",
             status, summary["files_recorded"], len(listed), summary["files_failed"],
             summary["files_not_attempted"], summary["bytes_raw"] / 1e6, root, summary["wall_seconds"])
    if interrupted:
        log.error("cycle recorded as INTERRUPTED - no Merkle root; re-run resumes via conditional requests")
        return EXIT_INTERRUPTED
    if partial:
        log.warning("partial slice recorded under %s - no Merkle root by design", cycle_dir)
        return EXIT_PARTIAL
    if not root:
        log.error("cycle recorded WITH %d GAPS - no Merkle root written; see failures and manifest_anomalies "
                  "in cycle.json", summary["files_failed"])
        return EXIT_GAPS
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
