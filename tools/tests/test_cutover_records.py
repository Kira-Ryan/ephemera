"""tools/cutover_records: the phase B ownership table as code, against two small spools. Every
refusal leaves the spool untouched; files/ is never touched; heartbeats are a union, never an
overwrite."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cutover_records as cr  # noqa: E402

ROOT_A = "a" * 64
ROOT_B = "b" * 64


def cycle(base: Path, name: str, root: str | None, *, shipped: bool | None, ots: bytes = b"proof",
          witness: str = "w", status: str = "complete") -> Path:
    d = base / f"cycle_{name}"
    d.mkdir(parents=True)
    rec = {"cycle": f"cycle_{name}", "status": status, "files_recorded": 3, "files_failed": 0,
           "manifest_anomalies": [], "merkle_root": root}
    (d / "cycle.json").write_text(json.dumps(rec))
    (d / "etag_cache.json").write_text("{}")
    (d / "MANIFEST.txt").write_text("m\n")
    if root:
        (d / "root.txt").write_text(root + "\n")
        (d / "root.txt.ots").write_bytes(ots)
        (d / "root.txt.ots.bak").write_bytes(ots + b".bak")
    (d / "witness.json").write_text(json.dumps({"who": witness}))
    if shipped is not None:
        (d / "ship.json").write_text(json.dumps({"shipped": {"key": "k"} if shipped else None, "records": {}}))
    return d


def snapshot(spool: Path) -> dict[str, bytes]:
    return {p.relative_to(spool).as_posix(): p.read_bytes() for p in spool.rglob("*") if p.is_file()}


@pytest.fixture
def hosts(tmp_path):
    staging, spool = tmp_path / "staging", tmp_path / "spool"
    staging.mkdir()
    spool.mkdir()
    return staging, spool


def test_a_cycle_only_windows_had_is_copied_whole(hosts):
    staging, spool = hosts
    cycle(staging, "aaaaaaaaaaaa", ROOT_A, shipped=True)
    acts = cr.plan(staging, spool)
    assert {a.verb for a in acts} == {"copy"} and len(acts) == 8
    cr.apply(acts, spool)
    assert sorted(p.name for p in (spool / "cycle_aaaaaaaaaaaa").iterdir()) == sorted(
        ["cycle.json", "etag_cache.json", "MANIFEST.txt", "root.txt", "root.txt.ots", "root.txt.ots.bak", "ship.json", "witness.json"])
    assert (spool / "cycle_aaaaaaaaaaaa" / "root.txt.ots").read_bytes() == b"proof"


def test_a_cycle_on_both_hosts_keeps_the_vps_record_and_takes_windows_proof_and_captures(hosts):
    staging, spool = hosts
    cycle(staging, "bbbbbbbbbbbb", ROOT_B, shipped=True, ots=b"windows-earlier-proof", witness="windows")
    cycle(spool, "bbbbbbbbbbbb", ROOT_B, shipped=True, ots=b"vps-later-proof", witness="vps")
    (spool / "cycle_bbbbbbbbbbbb" / "cycle.json").write_text('{"cycle": "cycle_bbbbbbbbbbbb", "status": "complete", "merkle_root": "' + ROOT_B + '", "vps": true}')
    before = snapshot(spool)
    acts = cr.plan(staging, spool)
    cr.apply(acts, spool)
    after = snapshot(spool)
    for kept in ("cycle.json", "etag_cache.json", "MANIFEST.txt", "root.txt"):
        assert after[f"cycle_bbbbbbbbbbbb/{kept}"] == before[f"cycle_bbbbbbbbbbbb/{kept}"], kept
    assert after["cycle_bbbbbbbbbbbb/root.txt.ots"] == b"windows-earlier-proof"
    assert after["cycle_bbbbbbbbbbbb/root.txt.ots.bak"] == b"windows-earlier-proof.bak"
    assert json.loads(after["cycle_bbbbbbbbbbbb/witness.json"]) == {"who": "windows"}
    assert json.loads(after["cycle_bbbbbbbbbbbb/ship.json"])["shipped"] == {"key": "k"}


def test_ship_json_is_taken_from_windows_only_if_windows_shipped(hosts):
    staging, spool = hosts
    cycle(staging, "cccccccccccc", ROOT_A, shipped=False)
    cycle(spool, "cccccccccccc", ROOT_A, shipped=True)
    (spool / "cycle_cccccccccccc" / "ship.json").write_text('{"shipped": {"key": "vps"}, "records": {}}')
    cr.apply(cr.plan(staging, spool), spool)
    assert json.loads((spool / "cycle_cccccccccccc" / "ship.json").read_text())["shipped"] == {"key": "vps"}


def test_a_first_hand_upload_record_on_the_vps_is_kept_over_windows_adoption_of_it(hosts):
    """Three of the four overlap cycles of 26 to 27 Sep: the VPS uploaded, Windows adopted. Both
    ship.json records say shipped; the VPS's is the first-hand one (etag, digest, upload time of
    its own put) and stays. Mutation: drop the adopted_from_remote_utc test and Windows's copy wins."""
    staging, spool = hosts
    cycle(staging, "aaaaaaaaaaaa", ROOT_A, shipped=True)
    (staging / "cycle_aaaaaaaaaaaa" / "ship.json").write_text(json.dumps(
        {"shipped": {"key": "k", "adopted_from_remote_utc": "2026-09-26T21:06:53Z"}, "records": {}}))
    cycle(spool, "aaaaaaaaaaaa", ROOT_A, shipped=True)
    (spool / "cycle_aaaaaaaaaaaa" / "ship.json").write_text(json.dumps(
        {"shipped": {"key": "k", "uploaded_utc": "2026-09-26T20:33:23Z", "etag": "e"}, "records": {}, "local_files_deleted_utc": "2026-09-27T20:33:00Z"}))
    acts = cr.plan(staging, spool)
    ship = [a for a in acts if a.src and a.src.name == "ship.json"][0]
    assert ship.verb == "keep" and "first-hand" in ship.why
    cr.apply(acts, spool)
    state = json.loads((spool / "cycle_aaaaaaaaaaaa" / "ship.json").read_text())
    assert state["shipped"]["etag"] == "e" and state["local_files_deleted_utc"]
    # the other way round, Windows uploaded and the VPS adopted: Windows's record wins
    (staging / "cycle_aaaaaaaaaaaa" / "ship.json").write_text(json.dumps({"shipped": {"key": "k", "etag": "w"}, "records": {}}))
    (spool / "cycle_aaaaaaaaaaaa" / "ship.json").write_text(json.dumps(
        {"shipped": {"key": "k", "adopted_from_remote_utc": "2026-09-26T14:23:02Z"}, "records": {}}))
    acts = cr.plan(staging, spool)
    assert [a.verb for a in acts if a.src and a.src.name == "ship.json"] == ["copy"]


def test_a_root_that_differs_between_hosts_stops_everything_and_writes_nothing(hosts):
    """Mutation: drop the same_bytes comparison in plan_cycle and this passes the wrong root through."""
    staging, spool = hosts
    cycle(staging, "dddddddddddd", ROOT_A, shipped=True)
    cycle(spool, "dddddddddddd", ROOT_B, shipped=True)
    cycle(staging, "eeeeeeeeeeee", ROOT_A, shipped=True)      # a fine cycle in the same batch
    before = snapshot(spool)
    acts = cr.plan(staging, spool)
    stops = [a for a in acts if a.verb == "stop"]
    assert len(stops) == 1 and "root.txt differs" in stops[0].why and "status=complete" in stops[0].why
    with pytest.raises(SystemExit, match="nothing was written"):
        cr.apply(acts, spool)
    assert snapshot(spool) == before
    assert not (spool / "cycle_eeeeeeeeeeee").exists()


def test_a_root_only_one_host_has_stops_too(hosts):
    staging, spool = hosts
    cycle(staging, "ffffffffffff", ROOT_A, shipped=True)
    cycle(spool, "ffffffffffff", None, shipped=None, status="interrupted")
    stops = [a for a in cr.plan(staging, spool) if a.verb == "stop"]
    assert len(stops) == 1 and "only Windows has a root" in stops[0].why and "status=interrupted" in stops[0].why


def test_staging_that_holds_raw_files_is_refused_outright(hosts):
    staging, spool = hosts
    d = cycle(staging, "aaaaaaaaaaaa", ROOT_A, shipped=True)
    (d / "files").mkdir()
    (d / "files" / "x.gz").write_bytes(b"raw")
    with pytest.raises(SystemExit, match="files/"):
        cr.plan(staging, spool)


def test_an_unknown_record_file_stops(hosts):
    staging, spool = hosts
    d = cycle(staging, "aaaaaaaaaaaa", ROOT_A, shipped=True)
    (d / "notes.txt").write_text("?")
    stops = [a for a in cr.plan(staging, spool) if a.verb == "stop"]
    assert len(stops) == 1 and "unknown record file" in stops[0].why


def test_daily_gp_score_are_copied_whole_and_a_different_existing_file_stops(hosts):
    staging, spool = hosts
    for sub, rel in (("daily", "2026-09-01/root.txt"), ("gp", "20260901_abcdefabcdef/record.json"), ("score", "visibility_abcdefabcdef.json")):
        p = staging / sub / rel
        p.parent.mkdir(parents=True)
        p.write_text(sub)
    (spool / "score").mkdir()
    (spool / "score" / "visibility_abcdefabcdef.json").write_text("score")     # identical: fine
    acts = cr.plan(staging, spool)
    assert [a.verb for a in acts if a.src and a.src.parent.parent.name in ("daily", "gp", "score") or (a.src and a.src.parent.name == "score")] \
        == ["copy", "copy", "keep"]
    cr.apply(acts, spool)
    assert (spool / "daily" / "2026-09-01" / "root.txt").read_text() == "daily"
    assert (spool / "gp" / "20260901_abcdefabcdef" / "record.json").read_text() == "gp"
    (spool / "score" / "visibility_abcdefabcdef.json").write_text("different")
    stops = [a for a in cr.plan(staging, spool) if a.verb == "stop"]
    assert len(stops) == 1 and "different score/ file" in stops[0].why


def test_heartbeats_are_a_union_ordered_by_utc_never_an_overwrite(hosts):
    staging, spool = hosts
    w = [{"utc": "2026-09-26T10:00:00Z", "host": "win"}, {"utc": "2026-09-26T12:00:00Z", "host": "win"}]
    v = [{"utc": "2026-09-26T12:00:00Z", "host": "win"}, {"utc": "2026-09-26T13:00:00Z", "host": "vps"}]
    (staging / "heartbeats.jsonl").write_text("\n".join(json.dumps(x) for x in w) + "\n")
    (spool / "heartbeats.jsonl").write_text("\n".join(json.dumps(x) for x in v) + "\n")
    acts = cr.plan(staging, spool)
    assert [a.verb for a in acts] == ["merge"]
    cr.apply(acts, spool)
    lines = [json.loads(l) for l in (spool / "heartbeats.jsonl").read_text().splitlines()]
    assert [l["utc"] for l in lines] == ["2026-09-26T10:00:00Z", "2026-09-26T12:00:00Z", "2026-09-26T13:00:00Z"]
    assert cr.check(staging, spool) == []


def test_check_names_what_is_missing(hosts):
    staging, spool = hosts
    cycle(spool, "aaaaaaaaaaaa", ROOT_A, shipped=False)
    (spool / "cycle_aaaaaaaaaaaa" / "root.txt.ots").unlink()
    (staging / "daily" / "2026-09-01").mkdir(parents=True)
    (staging / "daily" / "2026-09-01" / "root.txt").write_text("r")
    problems = cr.check(staging, spool)
    assert any("root.txt without root.txt.ots" in p for p in problems)
    assert any("does not record shipped" in p for p in problems)
    assert any("missing from the spool" in p for p in problems)
    assert any(p.startswith("daily:") for p in problems)


def test_main_plan_is_read_only_and_apply_writes(hosts, capsys):
    staging, spool = hosts
    cycle(staging, "aaaaaaaaaaaa", ROOT_A, shipped=True)
    assert cr.main(["plan", str(staging), str(spool)]) == 0
    assert not (spool / "cycle_aaaaaaaaaaaa").exists()
    assert cr.main(["apply", str(staging), str(spool)]) == 0
    assert (spool / "cycle_aaaaaaaaaaaa" / "witness.json").exists()
    assert "check: 0 problem(s)" in capsys.readouterr().out
