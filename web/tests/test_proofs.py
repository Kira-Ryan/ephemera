"""The roots and proofs the site publishes (D22), the block it prints beside them, the steps a reader
is told to run, and the Wayback copies found after the fact (probe P10)."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "archive"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "probes" / "p10_outage_captures"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402
import check_captures  # noqa: E402
import witness  # noqa: E402
from test_build import fake_proof, write_root  # noqa: E402
from test_build_visibility import (NOW, _with_failing_copies, add_catalogue, add_score, build_site, make_spool,  # noqa: E402
                                   page_at, text)

REPO = Path(__file__).resolve().parents[2]
SHA_A = "aaaaaaaaaaaa"


def built_from(spool: Path, tmp_path: Path) -> tuple[dict, Path]:
    out = tmp_path / "dist"
    assert build.main(["--spool", str(spool), "--out", str(out)]) == 0
    return json.loads((out / "ledger.json").read_text(encoding="utf-8")), out


def scored_spool(tmp_path: Path) -> Path:
    spool = make_spool(tmp_path, NOW)
    add_catalogue(spool)
    add_score(spool)
    return spool


def row_of(page: str, row_id: str) -> str:
    return re.search(rf'<tr[^>]*id="{row_id}".*?</tr>', page, re.S).group(0)


def cycle_in(ledger: dict, sha: str) -> dict:
    return next(c for c in ledger["cycles"] if c["cycle"] == f"cycle_{sha}")


def test_the_block_reader_reads_a_real_proof():
    """The fake proofs in these tests are only as good as the reader's agreement with a real one. The
    P2 proof is a real OpenTimestamps file whose three calendars landed in three different blocks.

    Mutation: read the height without skipping its length byte and this fails."""
    assert build.proof_blocks((REPO / "probes/p2_witnessing/evidence/root.txt.ots").read_bytes()) == [964641, 964667, 964715]


def test_a_proof_with_no_attestation_names_no_block():
    assert build.proof_blocks(fake_proof()) == []
    assert build.proof_blocks(fake_proof(964904, 964903, 964904)) == [964903, 964904]


def test_every_proof_is_in_the_site_byte_for_byte_and_linked_from_its_row(tmp_path):
    """Publishing a proof means a stranger can fetch the same bytes the root was stamped over.

    Mutation: delete the publish_proofs call from build.main, or the proof_link in archive_row or the
    daily table, and this fails."""
    ledger, _, out = build_site(tmp_path)
    spool = tmp_path / "spool"
    for name in ("root.txt", "root.txt.ots"):
        assert (out / "proofs" / SHA_A / name).read_bytes() == (spool / f"cycle_{SHA_A}" / name).read_bytes(), name
    assert cycle_in(ledger, SHA_A)["ots"]["proof"] == f"proofs/{SHA_A}/root.txt.ots"
    archive = page_at(out, "archive")
    # `ots verify` needs both files, so a row links both
    assert f'<a href="../proofs/{SHA_A}/root.txt.ots">block 964904</a>' in row_of(archive, f"c-{SHA_A}")
    assert f'<a href="../proofs/{SHA_A}/root.txt">a1a1a1a1a1a1</a>' in row_of(archive, f"c-{SHA_A}")
    day = (NOW - timedelta(hours=30)).strftime("%Y-%m-%d")
    for name in ("root.txt", "root.txt.ots"):
        assert (out / "proofs" / "daily" / day / name).read_bytes() == (spool / "daily" / day / name).read_bytes(), name
    assert f'<a href="../proofs/daily/{day}/root.txt.ots">block 964950</a>' in archive
    assert f'<a href="../proofs/daily/{day}/root.txt">d4d4d4d4d4d4</a>' in archive
    # a cycle still waiting for its block has its stamp said in words and no block to link
    assert "stamped, attestation pending" in row_of(archive, "c-cccccccccccc")


def test_the_page_prints_the_block_a_reader_will_see(tmp_path):
    """`ots verify` reports the lowest block in a proof holding several. The witness recorded whichever
    `ots info` printed first, which was a later block on 44 of 210 cycles on 5 Nov 2026.

    Mutation: return recorded_block instead of blocks[0] from build.proof_state and this fails."""
    spool = scored_spool(tmp_path)
    write_root(spool / f"cycle_{SHA_A}", "a1" * 32, 964904, 964903)       # witness.json still says 964904
    ledger, out = built_from(spool, tmp_path)
    assert cycle_in(ledger, SHA_A)["ots"]["attested_block"] == 964903
    assert "block 964903" in row_of(page_at(out, "archive"), f"c-{SHA_A}")
    assert "this root is in block 964903" in text((out / "index.html").read_text(encoding="utf-8"))
    assert "committed in block 964903" in text(page_at(out, "check"))


def test_a_proof_in_a_new_state_decides_over_the_record(tmp_path):
    """A proof upgraded since the witness last wrote its record is still the thing being published."""
    spool = scored_spool(tmp_path)
    write_root(spool / "cycle_cccccccccccc", "c3" * 32, 965000)           # witness.json has no attestation yet
    ledger, _ = built_from(spool, tmp_path)
    assert cycle_in(ledger, "cccccccccccc")["ots"]["attested_block"] == 965000
    assert ledger["totals"]["attested"] == 2


def test_a_root_file_that_is_not_the_recorded_root_is_not_published(tmp_path, capsys):
    """A proof that proves some other root must not sit beside this cycle's row, and the build says why
    rather than publishing it or stopping the whole site.

    Mutation: drop the comparison with the recorded root in build.proof_state and this fails."""
    spool = scored_spool(tmp_path)
    (spool / f"cycle_{SHA_A}" / "root.txt").write_bytes(b"f" * 64 + b"\n")
    ledger, out = built_from(spool, tmp_path)
    assert not (out / "proofs" / SHA_A).exists()
    assert cycle_in(ledger, SHA_A)["ots"]["proof"] is None
    assert f"cycle_{SHA_A}: root.txt is not the recorded root" in capsys.readouterr().err
    assert "block 964904" in row_of(page_at(out, "archive"), f"c-{SHA_A}")
    assert f'proofs/{SHA_A}' not in page_at(out, "archive")


def test_a_proof_that_does_not_commit_to_the_root_is_not_published(tmp_path, capsys):
    """A root that changed before the witness repaired its proof leaves a root file matching the record
    beside a proof of something else, and the page's own command would then fail. Found in review.

    Mutation: drop the digest check in build.proof_state and this fails."""
    spool = scored_spool(tmp_path)
    (spool / f"cycle_{SHA_A}" / "root.txt.ots").write_bytes(fake_proof(964800))
    ledger, out = built_from(spool, tmp_path)
    c = cycle_in(ledger, SHA_A)
    assert c["ots"]["proof"] is None and c["ots"]["attested_block"] == 964904   # the record, not the stray proof
    assert not (out / "proofs" / SHA_A).exists()
    assert f"cycle_{SHA_A}: root.txt.ots does not commit to root.txt" in capsys.readouterr().err


def test_a_pending_proof_is_not_printed_as_attested(tmp_path, capsys):
    """The published file decides. If the witness recorded a block and the proof beside it holds none, a
    reader cannot see that block, so the row says pending and the build says why. Found in review.

    Mutation: fall back to the recorded block in build.proof_state and this fails."""
    spool = scored_spool(tmp_path)
    write_root(spool / f"cycle_{SHA_A}", "a1" * 32)                       # witness.json still says 964904
    ledger, out = built_from(spool, tmp_path)
    c = cycle_in(ledger, SHA_A)
    assert c["ots"]["attested_block"] is None and c["ots"]["proof"] == f"proofs/{SHA_A}/root.txt.ots"
    assert ledger["totals"]["attested"] == 0
    assert "stamped, attestation pending" in row_of(page_at(out, "archive"), f"c-{SHA_A}")
    assert "Three things you can run right now" not in text((out / "index.html").read_text(encoding="utf-8"))
    assert f"cycle_{SHA_A}: the record names block 964904 but its proof holds none" in capsys.readouterr().err


def test_a_root_file_with_a_windows_line_ending_is_refused(tmp_path):
    """D12: the proof commits to the exact bytes, so a root file that is not 64 hex and one LF would
    not verify against the printed root even if the digits agree."""
    spool = scored_spool(tmp_path)
    (spool / f"cycle_{SHA_A}" / "root.txt").write_bytes(b"a1" * 32 + b"\r\n")
    ledger, _ = built_from(spool, tmp_path)
    assert cycle_in(ledger, SHA_A)["ots"]["proof"] is None


def test_a_proof_the_build_did_not_write_is_removed(tmp_path):
    """Mutation: drop the prune in build.publish_proofs and this fails."""
    spool = scored_spool(tmp_path)
    out = tmp_path / "dist"
    stale = out / "proofs" / "000000000000" / "root.txt.ots"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale")
    built_from(spool, tmp_path)
    assert not stale.exists()
    assert (out / "proofs" / SHA_A / "root.txt.ots").exists()


def test_the_worked_example_is_always_a_cycle_with_a_proof_to_fetch(tmp_path):
    """Step 3 tells the reader to run a file, so the example cycle has to have one.

    Mutation: drop the proof condition from pages.verify_kit and this fails."""
    spool = scored_spool(tmp_path)
    (spool / f"cycle_{SHA_A}" / "root.txt.ots").unlink()
    _, out = built_from(spool, tmp_path)
    front = text((out / "index.html").read_text(encoding="utf-8"))
    assert "Three things you can run right now" not in front
    assert "No cycle yet has a Bitcoin attestation, a published proof and an independent copy" in front
    assert "No cycle yet has a Bitcoin attestation, a published proof and an independent copy" in text(page_at(out, "check"))


def test_the_steps_on_the_page_can_actually_be_followed(tmp_path):
    """The page that opens "None of this is worth anything if you have to take my word for it" said
    "k from 0 to 9" (nine names on cycle a435fa5f0103), "download it, hash it" (plain curl hashes the
    gzip, not the list) and "ots verify root.txt.ots" with no file to run it on.

    Mutation: restore any of those sentences, or drop either proof link, and this fails."""
    _, _, out = build_site(tmp_path)
    front_raw, check_raw = (out / "index.html").read_text(encoding="utf-8"), page_at(out, "check")
    front, check = text(front_raw), text(check_raw)
    for doc in (front, check):
        assert "--compressed" in doc
        assert "k = 0, 1, 2 and on" in doc and "from 0 to 9" not in doc
        assert "ots verify root.txt.ots" in doc
        assert "data release" not in doc
    assert "counting files from zero" in front and "counting from zero" in check
    assert "skipping repeats until there are ten" in front and "Skip any repeat until you have ten" in check
    assert "wc -l reads one short" in check
    assert f'href="proofs/{SHA_A}/root.txt"' in front_raw and f'href="proofs/{SHA_A}/root.txt.ots"' in front_raw
    assert f'href="../proofs/{SHA_A}/root.txt"' in check_raw and f'href="../proofs/{SHA_A}/root.txt.ots"' in check_raw
    assert "The root file is 64 lowercase hexadecimal characters and one line feed, 65 bytes" in check


def test_the_sample_rule_as_written_gives_what_the_witness_chose():
    """The rule on the page, taken word for word, against the code that chose the files, on a root and
    list size where k = 0 to 9 repeats an index, which is the case the old wording got wrong.

    Mutation: stop skipping repeats in this rule, or in witness.sample_indices, and this fails."""
    n = 40
    root = next(r for r in (f"{i:064x}" for i in range(1000))
                if len({int(hashlib.sha256(f"{r}:{k}".encode()).hexdigest(), 16) % n for k in range(10)}) < 10)
    picked, k = [], 0
    while len(picked) < 10:
        i = int(hashlib.sha256(f"{root}:{k}".encode()).hexdigest(), 16) % n
        if i not in picked:
            picked.append(i)
        k += 1
    assert k > 10
    assert sorted(picked) == witness.sample_indices(root, n, 10)


# ---------------------------------------------------------------- copies found after the fact


def late_file(tmp_path: Path, monkeypatch, cycle: str, sample_names: list[str]) -> None:
    path = tmp_path / "late.json"
    path.write_text(json.dumps({"method": "probes/p10_outage_captures", "cycles": {
        cycle: {"checked_utc": "2026-11-08T19:00:00Z",
                "manifest": {"timestamp": "20260913053025", "sha256_of_copy": "ab" * 32,
                             "id_url": "https://web.archive.org/web/20260913053025id_/https://example.invalid/MANIFEST.txt"},
                "samples": {n: {"timestamp": "20260913053100", "sha256_of_copy": "cd" * 32,
                                "id_url": f"https://web.archive.org/web/20260913053100id_/https://example.invalid/{n}"}
                            for n in sample_names}}}}), encoding="utf-8")
    monkeypatch.setattr(build, "LATE_COPIES", path)


def test_a_copy_found_later_changes_the_row_and_the_count(tmp_path, monkeypatch):
    """The witness asked Save Page Now, got an HTTP 500 and recorded no copy, and the row said NEVER
    CAPTURED for years of readers while the Wayback Machine held the copy.

    Mutation: delete the with_late_copies call from build.load_cycles and this fails."""
    spool = scored_spool(tmp_path)
    sha = _with_failing_copies(spool, 1)[0]
    before = build.build_ledger(spool, NOW)["totals"]["witness_defects"]
    late_file(tmp_path, monkeypatch, f"cycle_{sha}", [f"f{k}" for k in range(10)])
    ledger, out = built_from(spool, tmp_path)
    assert ledger["totals"]["witness_defects"] == before - 1
    wb = cycle_in(ledger, sha)["wayback"]
    assert wb["manifest_verified"] and wb["found_later"] == "2026-11-08" and wb["losses"] == 0
    assert wb["manifest_copy_url"].startswith("https://web.archive.org/web/20260913053025id_/")
    assert all(s["verified"] and s["copy_url"] for s in wb["samples"])
    archive = page_at(out, "archive")
    row = row_of(archive, f"c-{sha}")
    assert "manifest ok, 10/10 samples verified, found later" in row and "NO COPY FOUND" not in row
    assert 'href="https://web.archive.org/web/20260913053025id_/' in row
    assert "Save Page Now answered with an error at the time" in text(archive)


def test_a_sample_with_no_copy_found_stays_a_loss(tmp_path, monkeypatch):
    """Finding some copies must not read as finding them all.

    Mutation: count every sample as verified in build.with_late_copies and this fails."""
    spool = scored_spool(tmp_path)
    sha = _with_failing_copies(spool, 1)[0]
    before = build.build_ledger(spool, NOW)["totals"]["witness_defects"]
    late_file(tmp_path, monkeypatch, f"cycle_{sha}", [f"f{k}" for k in range(9)])
    ledger, out = built_from(spool, tmp_path)
    assert ledger["totals"]["witness_defects"] == before
    assert "manifest ok, 9/10 samples verified, 1 lost, found later" in row_of(page_at(out, "archive"), f"c-{sha}")


def test_a_late_entry_never_overrides_a_copy_the_witness_verified(tmp_path, monkeypatch):
    """Mutation: drop the record check in build.load_cycles and this fails."""
    spool = scored_spool(tmp_path)
    late_file(tmp_path, monkeypatch, f"cycle_{SHA_A}", ["f0"])
    ledger, out = built_from(spool, tmp_path)
    wb = cycle_in(ledger, SHA_A)["wayback"]
    assert "found_later" not in wb and "20260831060000id_" in wb["manifest_copy_url"]
    assert "Save Page Now answered with an error" not in text(page_at(out, "archive"))


def test_no_late_copies_file_leaves_every_row_as_recorded(tmp_path, monkeypatch):
    """The build has to work on a checkout without the file, and a witness record is unchanged by it."""
    monkeypatch.setattr(build, "LATE_COPIES", tmp_path / "absent.json")
    spool = scored_spool(tmp_path)
    sha = _with_failing_copies(spool, 1)[0]
    ledger, out = built_from(spool, tmp_path)
    assert "manifest: NO COPY FOUND" in row_of(page_at(out, "archive"), f"c-{sha}")
    assert "found_later" not in cycle_in(ledger, sha)["wayback"]


def test_rerunning_the_probe_keeps_what_it_already_found(tmp_path, monkeypatch):
    """A copy found earlier is verified in the ledger by the next run, so the probe does not look at it
    again, and writing only what the new run found would erase it and put the row back to a defect.
    Found in review, through the probe's own documented command.

    Mutation: write only this run's findings in check_captures.main and this fails."""
    url = "https://web.archive.org/web/20260913053025id_/https://api.starlink.com/public-files/ephemerides/MANIFEST.txt?cycle="
    late_path = tmp_path / "late.json"
    late_path.write_text(json.dumps({"method": "probes/p10_outage_captures", "cycles": {
        "cycle_111111111111": {"checked_utc": "2026-11-08T19:05:55Z", "samples": {},
                               "manifest": {"timestamp": "20260913053025", "id_url": url + "111111111111", "sha256_of_copy": "ab" * 32}}}}),
        encoding="utf-8")
    ledger_path, cdx_path = tmp_path / "ledger.json", tmp_path / "cdx.json"
    raw = b"file one\nfile two"
    digest = hashlib.sha256(raw).hexdigest()
    ledger_path.write_text(json.dumps({"cycles": [
        {"cycle": "cycle_111111111111", "first_seen_utc": "2026-09-13T04:00:00Z", "manifest_sha256": "ab" * 32,
         "wayback": {"attempted": True, "skipped": None, "manifest_verified": True, "manifest_captured": True, "samples": []}},
        {"cycle": "cycle_222222222222", "first_seen_utc": "2026-09-14T04:00:00Z", "manifest_sha256": digest,
         "wayback": {"attempted": True, "skipped": None, "manifest_verified": False, "manifest_captured": False, "samples": []}}]}),
        encoding="utf-8")
    cdx_path.write_text(json.dumps([["timestamp", "original"], ["20260914050000", check_captures.FOLDER + "MANIFEST.txt?cycle=222222222222"]]),
                        encoding="utf-8")
    spool = tmp_path / "spool" / "cycle_222222222222"
    spool.mkdir(parents=True)
    (spool / "cycle.json").write_text(json.dumps({"files": []}), encoding="utf-8")
    monkeypatch.setattr(check_captures, "fetch_raw", lambda _s, _u: (200, raw))
    monkeypatch.setattr(sys, "argv", ["check_captures.py", "--ledger", str(ledger_path), "--cdx", str(cdx_path),
                                      "--spool", str(tmp_path / "spool"), "--out", str(tmp_path / "out.json"), "--late", str(late_path)])
    assert check_captures.main() == 0
    late = json.loads(late_path.read_text(encoding="utf-8"))["cycles"]
    assert set(late) == {"cycle_111111111111", "cycle_222222222222"}
    assert late["cycle_111111111111"]["checked_utc"] == "2026-11-08T19:05:55Z"        # untouched, with its own date
    assert late["cycle_222222222222"]["manifest"]["sha256_of_copy"] == digest
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", late["cycle_222222222222"]["checked_utc"])


def test_a_rerun_that_hits_a_passing_404_keeps_the_copy_it_had(tmp_path, monkeypatch):
    """A copy can answer 404 for days and come back, so a rerun on a saved ledger must not turn a sample
    already matched into a loss, and the entry keeps the date it was found. Found in review.

    Mutation: replace an entry wholesale in check_captures.merged_late and this fails."""
    folder = check_captures.FOLDER
    raw = b"manifest bytes"
    digest = hashlib.sha256(raw).hexdigest()
    seen = {"timestamp": "20260914050000", "id_url": f"https://web.archive.org/web/20260914050000id_/{folder}a.txt", "sha256_of_copy": "cd" * 32}
    late_path = tmp_path / "late.json"
    late_path.write_text(json.dumps({"method": "probes/p10_outage_captures", "cycles": {"cycle_222222222222": {
        "checked_utc": "2026-11-08T19:05:55Z", "samples": {"a.txt": seen},
        "manifest": {"timestamp": "20260914050000", "id_url": f"https://web.archive.org/web/20260914050000id_/{folder}MANIFEST.txt?cycle=222222222222",
                     "sha256_of_copy": digest}}}}), encoding="utf-8")
    ledger_path, cdx_path = tmp_path / "ledger.json", tmp_path / "cdx.json"
    ledger_path.write_text(json.dumps({"cycles": [
        {"cycle": "cycle_222222222222", "first_seen_utc": "2026-09-14T04:00:00Z", "manifest_sha256": digest,
         "wayback": {"attempted": True, "skipped": None, "manifest_verified": False, "manifest_captured": False,
                     "samples": [{"name": "a.txt"}, {"name": "b.txt"}]}}]}), encoding="utf-8")
    cdx_path.write_text(json.dumps([["timestamp", "original"], ["20260914050000", folder + "MANIFEST.txt?cycle=222222222222"],
                                    ["20260914050000", folder + "a.txt"], ["20260914050000", folder + "b.txt"]]), encoding="utf-8")
    spool = tmp_path / "spool" / "cycle_222222222222"
    spool.mkdir(parents=True)
    b_raw = b"sample b"
    (spool / "cycle.json").write_text(json.dumps({"files": [{"name": "a.txt", "sha256": "cd" * 32},
                                                            {"name": "b.txt", "sha256": hashlib.sha256(b_raw).hexdigest()}]}), encoding="utf-8")

    def fetch(_session, url):
        return (404, b"") if url.endswith("a.txt") else (200, b_raw if url.endswith("b.txt") else raw)

    monkeypatch.setattr(check_captures, "fetch_raw", fetch)
    monkeypatch.setattr(sys, "argv", ["check_captures.py", "--ledger", str(ledger_path), "--cdx", str(cdx_path),
                                      "--spool", str(tmp_path / "spool"), "--out", str(tmp_path / "out.json"), "--late", str(late_path)])
    assert check_captures.main() == 0
    entry = json.loads(late_path.read_text(encoding="utf-8"))["cycles"]["cycle_222222222222"]
    assert set(entry["samples"]) == {"a.txt", "b.txt"}
    assert entry["samples"]["a.txt"] == seen and entry["checked_utc"] == "2026-11-08T19:05:55Z"


def test_the_late_copies_file_in_the_repository_is_sound():
    """Anything in the published file is a claim on the archive page. Each URL must be a dated copy on
    the Wayback Machine, each digest a real SHA-256, and no raw file or path is carried."""
    path = REPO / "archive" / "late_copies.json"
    late = json.loads(path.read_text(encoding="utf-8"))
    assert late["cycles"], "the file exists but lists nothing"
    for cycle, entry in late["cycles"].items():
        assert re.fullmatch(r"cycle_[0-9a-f]{12}", cycle)
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", entry["checked_utc"])
        for copy in (entry["manifest"], *entry["samples"].values()):
            assert re.fullmatch(r"https://web\.archive\.org/web/\d{14}id_/https://api\.starlink\.com/public-files/ephemerides/.+",
                                copy["id_url"]), copy["id_url"]
            assert copy["timestamp"] in copy["id_url"]
            assert re.fullmatch(r"[0-9a-f]{64}", copy["sha256_of_copy"])
