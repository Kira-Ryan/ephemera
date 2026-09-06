"""Behavioural tests for archive/verify.py, driven through main() over real cycles built by
poll.main. The verifier must pass a sound cycle, fail on any tampering, accept a consistent
gapped record, and re-check Wayback copies when asked."""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import poll  # noqa: E402
import verify  # noqa: E402
import witness  # noqa: E402
from test_poll import CONTACT, Feed, build_site, run  # noqa: E402
from test_witness import FakeWayback, StubOts, set_current  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_fail_counter():
    verify.FAILS = 0
    yield


@pytest.fixture
def cycle(tmp_path):
    site, names = build_site(tmp_path)
    feed = Feed(site, names)
    spool = tmp_path / "spool"
    rc, rec, cyc = run(feed, spool)
    assert rc == 0
    yield feed, spool, rec, cyc
    feed.close()


def test_a_sound_cycle_passes(cycle):
    """Mutation: change the verifier's independent Merkle coding (pair order, duplication rule) ->
    a perfectly good cycle fails, red."""
    _, _, _, cyc = cycle
    assert verify.main([str(cyc)]) == 0


def test_sample_flag_passes_on_a_sound_cycle(cycle):
    _, _, _, cyc = cycle
    assert verify.main([str(cyc), "--sample", "2"]) == 0


def test_corrupted_stored_file_fails(cycle):
    _, _, rec, cyc = cycle
    victim = cyc / "files" / (rec["files"][1]["name"] + ".gz")
    victim.write_bytes(gzip.compress(b"created:not the real bytes" + b"x" * 2000))
    assert verify.main([str(cyc)]) == 1


def test_tampered_record_hash_fails(cycle):
    _, _, rec, cyc = cycle
    rec["files"][0]["sha256"] = "0" * 64
    (cyc / "cycle.json").write_text(json.dumps(rec))
    assert verify.main([str(cyc)]) == 1


def test_tampered_root_txt_fails(cycle):
    _, _, _, cyc = cycle
    b = bytearray((cyc / "root.txt").read_bytes())
    b[0] = ord("0") if b[0] != ord("0") else ord("1")
    (cyc / "root.txt").write_bytes(bytes(b))
    assert verify.main([str(cyc)]) == 1


def test_consistent_gapped_cycle_passes_but_a_stray_root_fails(tmp_path, monkeypatch):
    site, names = build_site(tmp_path)
    feed = Feed(site, names)
    try:
        (site / "MANIFEST.txt").write_text("\n".join(names + ["MEME_0_GONE_0_Operational_0_UNCLASSIFIED.txt"]) + "\n")
        monkeypatch.setattr(poll, "BACKOFF_S", 0.0)
        spool = tmp_path / "spool"
        rc, rec, cyc = run(feed, spool)
        assert rc == 2
        assert verify.main([str(cyc)]) == 0          # a recorded gap is truth, not a failure
        verify.FAILS = 0
        (cyc / "root.txt").write_bytes(b"a" * 64 + b"\n")  # a root that should not exist
        assert verify.main([str(cyc)]) == 1
    finally:
        feed.close()


def test_wayback_recheck_passes_then_catches_drift(cycle, monkeypatch):
    feed, spool, rec, cyc = cycle
    origin = {f"{feed.base}/MANIFEST.txt": (feed.site / "MANIFEST.txt").read_bytes(),
              **{f"{feed.base}/{n}": (feed.site / n).read_bytes() for n in feed.names}}
    wb = FakeWayback(origin)
    try:
        stub = StubOts()
        monkeypatch.setattr(witness, "make_ots_runner", lambda mode: stub)
        set_current(spool, rec["manifest_sha256"])
        assert witness.main(["--spool", str(spool), "--base", feed.base, "--wayback", wb.base,
                             "--contact", CONTACT, "--samples", "3", "--capture-gap", "0", "--once"]) == 0
        assert verify.main([str(cyc), "--wayback"]) == 0
        verify.FAILS = 0
        wb.corrupt.add(feed.names[0])               # the archived copy starts answering wrong bytes
        assert verify.main([str(cyc), "--wayback"]) == 1
    finally:
        wb.close()


# --------------------------------------------------------------- audit, 6 Sep 2026


def test_names_are_bound_to_the_cycle_not_just_content(cycle):
    """The Merkle root commits ordered content hashes and nothing else, and the counts check only
    compared MANIFEST.txt's line count. So a manifest naming one file and a record naming another
    passed every check: the archive would say it holds A while holding B.

    Mutation: drop the manifest-digest and name checks and this goes red."""
    _, spool, rec, cyc = cycle
    names = (cyc / "MANIFEST.txt").read_text().split()
    swapped = ["MEME_999_STARLINK-999_1_Operational_1_UNCLASSIFIED.txt"] + names[1:]
    (cyc / "MANIFEST.txt").write_text("\n".join(swapped) + "\n")
    assert verify.main([str(cyc)]) == 1, "a manifest that names different files passed"


def test_the_manifest_digest_that_names_the_cycle_is_checked(cycle):
    """A cycle's identity is the SHA-256 of its manifest (D10), and the directory is named from the
    first 48 bits of it. Neither the digest nor the name was ever recomputed.

    Mutation: drop check_identity() and this goes red."""
    _, spool, rec, cyc = cycle
    r = json.loads((cyc / "cycle.json").read_text())
    r["manifest_sha256"] = "de" * 32
    (cyc / "cycle.json").write_text(json.dumps(r))
    assert verify.main([str(cyc)]) == 1, "a record claiming the wrong manifest digest passed"


def test_wayback_check_fails_when_there_is_nothing_to_check(cycle, monkeypatch):
    """--wayback passed when zero samples were fetched, so a cycle with no independent copy at all
    reported a clean Wayback verification. It also never looked at the captured manifest, which is
    the one copy that proves which files the cycle claimed.

    Mutation: report(bad == 0, ...) without requiring a fetch and this goes red."""
    _, spool, rec, cyc = cycle
    (cyc / "witness.json").write_text(json.dumps({"ots": {}, "wayback": {"samples": {}}}))
    assert verify.main([str(cyc), "--wayback"]) == 1, "an empty witness passed the Wayback check"


def test_opentimestamps_state_is_bound_to_the_current_root(cycle):
    """The verifier echoed witness.json's attested block without checking that the proof on disk is
    a proof of the root the record now claims. A re-rooted cycle kept its old attestation and the
    verifier repeated it as though it still applied.

    Mutation: print the attestation without comparing root.txt and this goes red."""
    _, spool, rec, cyc = cycle
    (cyc / "witness.json").write_text(json.dumps({
        "root": "cc" * 32,
        "ots": {"stamped_utc": "2026-09-01T00:00:00Z", "attested": {"block_height": 964904}},
        "wayback": {}}))
    assert verify.main([str(cyc)]) == 1, "an attestation for a different root was reported as this cycle's"
