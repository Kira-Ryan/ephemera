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
