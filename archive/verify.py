#!/usr/bin/env python3
"""Ephemera verifier: re-check one archived cycle from its stored artefacts, trusting nothing
but them. This is the sceptic's tool (D07): it deliberately RE-IMPLEMENTS the Merkle construction
from the one documented paragraph (D09) instead of importing the poller's function, so a passing
root is agreement between two independent codings, not one function agreeing with itself.

Checks, in order:
  1. every stored files/<name>.gz decompresses to bytes whose SHA-256 and length match the record
     (--sample N spot-checks N evenly spaced files instead of all of them);
  2. the recorded per-file hashes, in record order, rebuild the recorded Merkle root;
  3. root.txt is exactly the root + one LF (65 bytes, D12) when the record has a root, and is
     absent when it does not;
  4. the record's counts are internally consistent and match MANIFEST.txt's line count;
  5. with --wayback: every verified sample in witness.json is fetched back from the Wayback
     Machine and re-hashed (gunzipping when the copy is the origin's transfer encoding, P2b);
  6. the OpenTimestamps state is reported with instructions for checking it independently
     (`ots verify` needs a Bitcoin node; without one, compare the proof's block merkle root
     against any block explorer).

Exit 0 when every performed check passes (a gapped cycle with a consistent record and no root is
a pass - the gap is recorded truth); exit 1 on any mismatch.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

FAILS = 0


def report(ok: bool, what: str) -> None:
    global FAILS
    print(("PASS  " if ok else "FAIL  ") + what)
    if not ok:
        FAILS += 1


def merkle_from_the_documented_paragraph(hex_leaves: list[str]) -> str | None:
    """D09: leaves are the raw SHA-256 digests in manifest order; each layer hashes adjacent pairs
    as SHA-256(left || right); an odd trailing node is paired with a copy of itself."""
    nodes = [bytes.fromhex(h) for h in hex_leaves]
    if not nodes:
        return None
    while len(nodes) > 1:
        if len(nodes) % 2 == 1:
            nodes = nodes + [nodes[-1]]
        nodes = [hashlib.sha256(nodes[i] + nodes[i + 1]).digest() for i in range(0, len(nodes), 2)]
    return nodes[0].hex()


def check_files(cycle: Path, rec: dict, sample: int) -> None:
    files = rec["files"]
    if sample and sample < len(files):
        step = len(files) / sample
        picked = [files[int(i * step)] for i in range(sample)]
        print(f"      (spot-checking {len(picked)} of {len(files)} stored files)")
    else:
        picked = files
    bad = 0
    for f in picked:
        gz = cycle / "files" / (f["name"] + ".gz")
        try:
            raw = gzip.decompress(gz.read_bytes())
        except OSError as e:
            print(f"      {f['name']}: unreadable ({e})")
            bad += 1
            continue
        if hashlib.sha256(raw).hexdigest() != f["sha256"] or len(raw) != f["bytes"]:
            print(f"      {f['name']}: stored bytes do not match the record")
            bad += 1
    report(bad == 0, f"stored files re-hash to the recorded SHA-256s ({len(picked)} checked, {bad} bad)")


def check_root(cycle: Path, rec: dict) -> None:
    rebuilt = merkle_from_the_documented_paragraph([f["sha256"] for f in rec["files"]])
    root = rec.get("merkle_root")
    root_txt = cycle / "root.txt"
    if root:
        report(rebuilt == root, "recorded hashes rebuild the recorded Merkle root (independent construction)")
        b = root_txt.read_bytes() if root_txt.exists() else b""
        report(b == (root + "\n").encode("ascii"),
               "root.txt is exactly the 64 hex characters + LF the record claims (D12)")
    else:
        report(not root_txt.exists(), "record has no root and no root.txt exists (a recorded gap, not a silent one)")


def check_counts(cycle: Path, rec: dict) -> None:
    listed = rec["files_listed"]
    summed = rec["files_recorded"] + rec["files_failed"] + rec["files_not_attempted"]
    report(summed == listed, f"counts sum: recorded+failed+not_attempted == files_listed ({summed} == {listed})")
    manifest_lines = len([ln for ln in (cycle / "MANIFEST.txt").read_bytes().decode("utf-8-sig").split("\n")
                          if ln.strip(" \t\r")])
    report(manifest_lines == listed, f"MANIFEST.txt line count matches files_listed ({manifest_lines} == {listed})")
    report(len(rec["files"]) == rec["files_recorded"],
           f"files array length matches files_recorded ({len(rec['files'])} == {rec['files_recorded']})")


def check_wayback(rec: dict, witness: dict) -> None:
    import requests  # only needed for the online check

    by_name = {f["name"]: f for f in rec["files"]}
    samples = (witness.get("wayback") or {}).get("samples") or {}
    checked = bad = 0
    for s in samples.values():
        if not s.get("verified"):
            continue
        checked += 1
        body = requests.get(s["id_url"], timeout=120).content
        try:
            got = hashlib.sha256(gzip.decompress(body)).hexdigest()
        except (OSError, gzip.BadGzipFile):
            got = hashlib.sha256(body).hexdigest()
        if got != by_name[s["name"]]["sha256"]:
            print(f"      {s['name']}: Wayback copy no longer matches the record")
            bad += 1
    report(bad == 0, f"Wayback id_ copies re-hash to the recorded SHA-256s ({checked} fetched, {bad} bad)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cycle", type=Path, help="a cycle directory (contains cycle.json)")
    ap.add_argument("--sample", type=int, default=0, help="spot-check N files instead of all of them")
    ap.add_argument("--wayback", action="store_true", help="also re-fetch the witnessed Wayback copies")
    args = ap.parse_args(argv)

    rec = json.loads((args.cycle / "cycle.json").read_text())
    print(f"cycle {rec['cycle']}  status={rec['status']}  files={rec['files_recorded']}/{rec['files_listed']}")
    check_files(args.cycle, rec, args.sample)
    check_root(args.cycle, rec)
    check_counts(args.cycle, rec)

    w_path = args.cycle / "witness.json"
    witness = json.loads(w_path.read_text()) if w_path.exists() else {}
    if args.wayback:
        check_wayback(rec, witness)
    att = (witness.get("ots") or {}).get("attested")
    if att:
        print(f"note  OpenTimestamps: attested at Bitcoin block {att['block_height']}. Independent check: "
              f"`ots verify root.txt.ots` against a Bitcoin node, or compare the proof's block merkle "
              f"root (`ots info root.txt.ots`) with block {att['block_height']} on any explorer.")
    elif (witness.get("ots") or {}).get("stamped_utc"):
        print("note  OpenTimestamps: stamped, Bitcoin attestation still pending upgrade.")

    print("VERDICT:", "PASS" if FAILS == 0 else f"FAIL ({FAILS} check(s) failed)")
    return 0 if FAILS == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
