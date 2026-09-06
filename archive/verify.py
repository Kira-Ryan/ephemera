#!/usr/bin/env python3
"""Ephemera verifier: re-check one archived cycle from its stored artefacts, trusting nothing
but them. This is the sceptic's tool (D07): it deliberately RE-IMPLEMENTS the Merkle construction
from the one documented paragraph (D09) instead of importing the poller's function, so a passing
root is agreement between two independent codings, not one function agreeing with itself.

Checks, in order:
  1. the cycle's identity: MANIFEST.txt hashes to the manifest digest the record claims, and the
     directory is named from that digest (D10). Without this the rest verifies an unnamed pile of
     bytes rather than this cycle;
  2. the names: every file the record holds is named by the manifest, in the manifest's order.
     The Merkle root commits ordered content hashes and nothing else, so a manifest naming one file
     beside a record naming another used to satisfy every other check here;
  3. every stored files/<name>.gz decompresses to bytes whose SHA-256 and length match the record
     (--sample N spot-checks N evenly spaced files instead of all of them);
  4. the recorded per-file hashes, in record order, rebuild the recorded Merkle root;
  5. root.txt is exactly the root + one LF (65 bytes, D12) when the record has a root, and is
     absent when it does not;
  6. the record's counts are internally consistent and match MANIFEST.txt's line count;
  7. the OpenTimestamps proof is bound to THIS root: witness.json records the root it stamped, and
     the proof file contains the SHA-256 of root.txt. An attestation for some earlier root is not
     evidence about this one, and used to be reported as though it were;
  8. with --wayback: the captured manifest is re-fetched and must hash to the cycle's own identity,
     and every verified sample is re-fetched and re-hashed (gunzipping when the copy is the
     origin's transfer encoding, P2b). A witness with nothing to fetch fails rather than passing
     silently.

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


def check_identity(cycle: Path, rec: dict) -> None:
    """The cycle is its manifest: the digest names it, and the directory is named from the digest."""
    manifest = cycle / "MANIFEST.txt"
    claimed = rec.get("manifest_sha256")
    if not manifest.exists() or not claimed:
        report(False, "MANIFEST.txt and a recorded manifest_sha256 are both present")
        return
    got = hashlib.sha256(manifest.read_bytes()).hexdigest()
    report(got == claimed, f"MANIFEST.txt hashes to the manifest digest the record claims "
                           f"({got[:12]}... == {claimed[:12]}...)")
    expected_dir = f"cycle_{claimed[:12]}"
    report(cycle.resolve().name == expected_dir,
           f"the directory is named from that digest (D10: {cycle.resolve().name} == {expected_dir})")


def check_names(cycle: Path, rec: dict) -> None:
    """The record's files are named by the manifest, in the manifest's order.

    The Merkle root binds content and order, not names. Without this check a manifest listing one
    set of files and a record listing another passes everything else, and the archive's claim about
    WHAT it holds is unverified."""
    manifest = [ln.strip() for ln in (cycle / "MANIFEST.txt").read_bytes().decode("utf-8-sig").splitlines()
                if ln.strip(" \t\r")]
    recorded = [f["name"] for f in rec.get("files") or []]
    listed = set(manifest)
    unknown = [n for n in recorded if n not in listed]
    report(not unknown, f"every recorded file is named by the manifest "
                        f"({len(recorded)} recorded, {len(unknown)} not in the manifest"
                        + (f", first {unknown[0]}" if unknown else "") + ")")
    order = [n for n in manifest if n in set(recorded)]
    report(order == recorded, "the record's files are in the manifest's order (the order the root commits)")


def check_ots(cycle: Path, rec: dict, witness: dict) -> None:
    """A proof that is present must be a proof of THIS root.

    Witnessing follows the pull, so a cycle that has not been stamped yet is pending, not wrong,
    and says so. What must never pass is a proof or an attestation that belongs to some other root
    being reported as though it applied to this one."""
    ots = cycle / "root.txt.ots"
    root_txt = cycle / "root.txt"
    if not rec.get("merkle_root"):
        report(not ots.exists(), "a cycle with no root has no OpenTimestamps proof either")
        return
    claimed = witness.get("merkle_root")
    attested = (witness.get("ots") or {}).get("attested")
    if not ots.exists() and not claimed and not attested:
        print("note  OpenTimestamps: not stamped yet (witnessing follows the pull)")
        return
    if claimed is not None or attested:
        report(claimed == rec["merkle_root"],
               f"witness.json stamped this cycle's root ({str(claimed)[:12]}... == {rec['merkle_root'][:12]}...)")
    if not ots.exists():
        report(not attested, "an attestation is claimed but root.txt.ots is missing")
        return
    if not root_txt.exists():
        report(False, "root.txt is present for a cycle that has a proof")
        return
    digest = hashlib.sha256(root_txt.read_bytes()).digest()
    report(digest in ots.read_bytes(),
           "root.txt.ots is a proof of these exact root.txt bytes (its SHA-256 appears in the proof)")


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
    wb = witness.get("wayback") or {}
    samples = wb.get("samples") or {}

    # The manifest copy is the one that matters most: it is the independent evidence of which files
    # the cycle claimed, and nothing here used to look at it.
    man = wb.get("manifest") or {}
    if man.get("id_url") and rec.get("manifest_sha256"):
        body = requests.get(man["id_url"], timeout=120).content
        try:
            got = hashlib.sha256(gzip.decompress(body)).hexdigest()
        except (OSError, gzip.BadGzipFile):
            got = hashlib.sha256(body).hexdigest()
        report(got == rec["manifest_sha256"],
               "the archived manifest copy hashes to this cycle's identity")
    else:
        report(False, "witness.json records an archived manifest copy to re-fetch")

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
    # Nothing fetched is not a pass. A cycle whose witnessing never completed has no independent
    # copy, and reporting that as a clean verification is the opposite of what this tool is for.
    report(checked > 0 and bad == 0,
           f"Wayback id_ copies re-hash to the recorded SHA-256s ({checked} fetched, {bad} bad)"
           + ("" if checked else " - nothing was fetched, so nothing was verified"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cycle", type=Path, help="a cycle directory (contains cycle.json)")
    ap.add_argument("--sample", type=int, default=0, help="spot-check N files instead of all of them")
    ap.add_argument("--wayback", action="store_true", help="also re-fetch the witnessed Wayback copies")
    args = ap.parse_args(argv)

    rec = json.loads((args.cycle / "cycle.json").read_text())
    print(f"cycle {rec['cycle']}  status={rec['status']}  files={rec['files_recorded']}/{rec['files_listed']}")
    w_path = args.cycle / "witness.json"
    witness = json.loads(w_path.read_text()) if w_path.exists() else {}

    check_identity(args.cycle, rec)
    check_names(args.cycle, rec)
    check_files(args.cycle, rec, args.sample)
    check_root(args.cycle, rec)
    check_counts(args.cycle, rec)
    check_ots(args.cycle, rec, witness)
    if args.wayback:
        check_wayback(rec, witness)
    att = (witness.get("ots") or {}).get("attested")
    # Reported, not trusted: check_ots() above is what decides whether it applies to this root.
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
