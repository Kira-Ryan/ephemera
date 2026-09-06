"""Caller-level tests for score/run.py and score/globe_pack.py: a pass scores the newest unscored
complete cycle against the right snapshot, writes the report, the rows and the globe pack, records
skips loudly, and does nothing twice."""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run  # noqa: E402
from test_visibility import T0, gp_row, make_cycle, make_snapshot, tle, write_meme  # noqa: E402


def utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


KEEP = object()


def set_first_seen(spool: Path, cycle: str, when: datetime, root=KEEP) -> None:
    """Stamp the first-seen time. The Merkle root is left exactly as make_cycle computed it unless a
    test asks for something else: the scorer verifies the record before scoring, so a fixture that
    overwrites the root with a constant is testing a record production could never produce."""
    p = spool / cycle / "cycle.json"
    rec = json.loads(p.read_text())
    rec["first_seen_utc"] = utc(when)
    if root is not KEEP:
        rec["merkle_root"] = root
    p.write_text(json.dumps(rec))


def test_pass_scores_newest_first_pairs_snapshot_and_builds_pack(tmp_path, caplog):
    spool = tmp_path / "spool"
    l1, l2 = tle("25544")
    m1, m2 = tle("26000", "15.05000000")
    old, new = "cycle_000000000001", "cycle_000000000002"
    make_cycle(spool, [write_meme(spool / old / "files", 25544, "STARLINK-1", l1, l2)], old)
    make_cycle(spool, [write_meme(spool / new / "files", 25544, "STARLINK-1", l1, l2),
                       write_meme(spool / new / "files", 26000, "STARLINK-2", m1, m2)], new)
    set_first_seen(spool, old, T0 - timedelta(hours=8))
    set_first_seen(spool, new, T0)
    gone = "cycle_000000000000"          # complete, with a root, but its files have been shipped away
    make_cycle(spool, [], gone)
    (spool / gone / "files").mkdir()
    set_first_seen(spool, gone, T0 - timedelta(hours=16), root="ab" * 32)
    gapped = "cycle_00000000000g"
    make_cycle(spool, [], gapped)
    set_first_seen(spool, gapped, T0 - timedelta(hours=24), root=None)
    rows = [gp_row(25544, "STARLINK-1", l1, l2), gp_row(26000, "STARLINK-2", m1, m2)]
    make_snapshot(spool, rows, stamp=utc(T0 - timedelta(hours=1)).replace("-", "").replace(":", ""))
    later = make_snapshot(spool, rows + [gp_row(27000, "X", *tle("27000"))], stamp=utc(T0 + timedelta(hours=1)).replace("-", "").replace(":", ""))
    (later / "record.json").write_text(json.dumps({**json.loads((later / "record.json").read_text()), "fetched_utc": utc(T0 + timedelta(hours=1))}))
    earlier = [p for p in (spool / "gp").iterdir() if p != later][0]
    (earlier / "record.json").write_text(json.dumps({**json.loads((earlier / "record.json").read_text()), "fetched_utc": utc(T0 - timedelta(hours=1))}))

    res = run.one_pass(spool, max_cycles=1, workers=1, eval_step_min=60)
    assert [s["cycle"] for s in res["scored"]] == [new]                       # newest first
    assert res["scored"][0]["snapshot"] == earlier.name and res["scored"][0]["relation"] == "before_cycle"
    assert res["pending"] == [old] and res["skipped_no_files"] == [gone] and res["skipped_no_root"] == [gapped]
    assert res["errors"] == []
    out = spool / "score"
    rep = json.loads((out / "visibility_000000000002.json").read_text())
    assert rep["inputs"]["snapshot_relation"] == "before_cycle" and rep["counts"]["scored"] == 2 and "rows" not in rep
    with gzip.open(out / rep["rows_file"], "rt") as gz:
        rows_out = json.load(gz)
    assert len(rows_out) == 2 * 4
    pack = json.loads((out / "globe_000000000002.json").read_text())
    assert pack["kind"] == "globe_pack_v0" and pack["step_s"] == 3600 and pack["base"] == utc(T0)
    assert [s["id"] for s in pack["sats"]] == [25544, 26000]
    s = pack["sats"][0]
    assert s["l1"] == l1 and s["l2"] == l2 and s["t0_s"] == 0 and len(s["ric_m"]) == 4 * 3 and max(map(abs, s["ric_m"])) == 0
    assert pack["inputs"]["cycle"] == new and pack["inputs"]["catalogue_snapshot"] == earlier.name
    assert "predictions" in pack["method"]
    assert json.loads((out / "run.json").read_text())["scored"][0]["cycle"] == new

    res2 = run.one_pass(spool, max_cycles=5, workers=1, eval_step_min=60)             # the rest, once
    assert [s["cycle"] for s in res2["scored"]] == [old] and res2["pending"] == []
    assert res2["scored"][0]["relation"] == "after_cycle"                  # no snapshot predates the old cycle
    res3 = run.one_pass(spool, max_cycles=5, workers=1, eval_step_min=60)
    assert res3["scored"] == [] and res3["pending"] == [] and res3["skipped_no_files"] == [gone]  # still listed, every pass


def test_cycle_older_than_every_snapshot_is_flagged_after_cycle(tmp_path):
    spool = tmp_path / "spool"
    l1, l2 = tle("25544")
    c = "cycle_000000000009"
    make_cycle(spool, [write_meme(spool / c / "files", 25544, "STARLINK-1", l1, l2)], c)
    set_first_seen(spool, c, T0 - timedelta(days=3))
    make_snapshot(spool, [gp_row(25544, "STARLINK-1", l1, l2)])
    res = run.one_pass(spool, max_cycles=1, workers=1, eval_step_min=60)
    assert res["scored"][0]["relation"] == "after_cycle"
    rep = json.loads((spool / "score" / "visibility_000000000009.json").read_text())
    assert rep["inputs"]["snapshot_relation"] == "after_cycle"


def test_no_snapshots_is_a_recorded_error_not_a_crash(tmp_path):
    spool = tmp_path / "spool"
    l1, l2 = tle("25544")
    c = "cycle_000000000009"
    make_cycle(spool, [write_meme(spool / c / "files", 25544, "STARLINK-1", l1, l2)], c)
    set_first_seen(spool, c, T0)
    res = run.one_pass(spool, max_cycles=1, workers=1, eval_step_min=60)
    assert res["errors"] == ["no catalogue snapshots"] and res["scored"] == [] and res["pending"] == [c]
    assert run.main(["--spool", str(spool), "--once"]) == 1


def test_workers_give_the_same_rows_as_one_process(tmp_path):
    spool = tmp_path / "spool"
    l1, l2 = tle("25544")
    m1, m2 = tle("26000", "15.05000000")
    c = "cycle_000000000002"
    make_cycle(spool, [write_meme(spool / c / "files", 25544, "STARLINK-1", l1, l2),
                       write_meme(spool / c / "files", 26000, "STARLINK-2", m1, m2)], c)
    set_first_seen(spool, c, T0)
    make_snapshot(spool, [gp_row(25544, "STARLINK-1", l1, l2), gp_row(26000, "STARLINK-2", m1, m2)])
    run.one_pass(spool, max_cycles=1, workers=2, eval_step_min=60)
    with gzip.open(spool / "score" / "visibility_000000000002_rows.json.gz", "rt") as gz:
        parallel = json.load(gz)
    (spool / "score" / "visibility_000000000002.json").unlink()
    run.one_pass(spool, max_cycles=1, workers=1, eval_step_min=60)
    with gzip.open(spool / "score" / "visibility_000000000002_rows.json.gz", "rt") as gz:
        serial = json.load(gz)
    assert parallel == serial and len(serial) == 8


def test_headline_lost_and_uncatalogued_are_computed_and_resummarise_rebuilds_them(tmp_path):
    """The at-file-start headline takes each satellite once at its own file's first epoch; a
    comparison beyond 1,000 km counts as lost; an operator file whose id the catalogue has no entry
    for is counted, and a pseudo id is additionally counted as uncatalogued. resummarise.py rebuilds
    all of that from stored rows without re-propagating."""
    import resummarise  # noqa: PLC0415
    import visibility  # noqa: PLC0415
    spool = tmp_path / "spool"
    l1, l2 = tle("25544")
    m1, m2 = tle("26000", "15.05000000")
    c = "cycle_000000000002"
    files = spool / c / "files"
    names = [write_meme(files, 25544, "STARLINK-1", l1, l2),
             write_meme(files, 26000, "STARLINK-2", m1, m2),
             write_meme(files, 799501581, "STARLINK-38229", l1, l2),   # pseudo id: not in the catalogue
             write_meme(files, 41000, "STARLINK-3", l1, l2)]           # real id, also not in the catalogue
    make_cycle(spool, names, c)
    set_first_seen(spool, c, T0)
    make_snapshot(spool, [gp_row(25544, "STARLINK-1", l1, l2), gp_row(26000, "STARLINK-2", m1, m2)])
    run.one_pass(spool, max_cycles=1, workers=1, eval_step_min=60)
    rp = spool / "score" / "visibility_000000000002.json"
    rep = json.loads(rp.read_text())

    assert rep["counts"]["no_public_set"] == 2 and rep["counts"]["uncatalogued"] == 1
    start = rep["summary"]["at_file_start"]
    assert start["satellites"] == 2                      # one row per satellite, not four rows
    assert start["median_km"] == 0.0 and start["lost"] == 0 and start["lost_fraction"] == 0.0
    assert rep["summary"]["overall"]["n"] == 8 and "median_age_h" in rep["summary"]["overall"]
    assert "lost:" in rep["method"] and "at_file_start" in rep["method"]

    # a satellite that is half an orbit away at every epoch counts as lost, once
    rows_path = spool / "score" / rep["rows_file"]
    with gzip.open(rows_path, "rt") as gz:
        rows = json.load(gz)
    for r in rows:
        if r["norad"] == 26000:
            r["dist_km"] = 6000.0
    with gzip.open(rows_path, "wt") as gz:
        json.dump(rows, gz)
    assert resummarise.main(["--spool", str(spool)]) == 0
    rebuilt = json.loads(rp.read_text())
    assert rebuilt["summary"]["at_file_start"]["lost"] == 1
    assert rebuilt["summary"]["at_file_start"]["lost_fraction"] == 0.5
    assert rebuilt["summary"]["overall"]["lost"] == 4
    assert rebuilt["inputs"] == rep["inputs"] and rebuilt["as_of"] == rep["as_of"]   # provenance untouched
    assert rebuilt["resummarised_utc"].endswith("Z")

    # a report whose rows file is gone is reported, not silently skipped
    rows_path.unlink()
    assert resummarise.main(["--spool", str(spool)]) == 1


def test_at_file_start_picks_the_earliest_epoch_per_satellite():
    import visibility  # noqa: PLC0415
    rows = [{"norad": 1, "epoch": "2026-09-02T12:00:00Z", "dist_km": 90.0, "age_h": 9.0, "alt_km": 500.0},
            {"norad": 1, "epoch": "2026-09-02T06:00:00Z", "dist_km": 2.0, "age_h": 3.0, "alt_km": 500.0},
            {"norad": 2, "epoch": "2026-09-02T06:00:00Z", "dist_km": 4.0, "age_h": 3.0, "alt_km": 500.0}]
    st = visibility.at_file_start(rows)
    assert st["satellites"] == 2 and st["median_km"] == 3.0        # 2.0 and 4.0, not the 90 km row
    assert visibility.at_file_start([]) is None


def test_pack_reconstruction_puts_the_satellite_back_on_its_orbit(tmp_path):
    """The globe rebuilds the operator position by rotating the packed deviation through the frame
    of the PUBLIC satellite, which is the only frame a browser holding just the element set can
    build. If the pack carried the deviation in the operator's own frame instead, the two frames
    would disagree once the predictions separate and the satellite would be drawn off its orbit.

    Mutation: change globe_pack to pack radial_km/intrack_km/cross_km and this fails by thousands of
    kilometres. Measured against the real archive before the fix: 15,616 km.
    """
    import math  # noqa: PLC0415
    import globe_pack  # noqa: PLC0415
    import frames  # noqa: PLC0415
    from skyfield.api import EarthSatellite, load  # noqa: PLC0415

    spool = tmp_path / "spool"
    l1, l2 = tle("25544")
    files = spool / "cycle_000000000002" / "files"
    # an operator file 400 km ahead along track: far enough that the two frames visibly disagree
    def shift(pos, vel):
        along = frames.unit(vel)
        return tuple(c + 400.0 * u for c, u in zip(pos, along))

    name = write_meme(files, 25544, "STARLINK-1", l1, l2, hours=3.0, shift=shift)
    make_cycle(spool, [name], "cycle_000000000002")
    set_first_seen(spool, "cycle_000000000002", T0)
    make_snapshot(spool, [gp_row(25544, "STARLINK-1", l1, l2)])
    run.one_pass(spool, max_cycles=1, workers=1, eval_step_min=60)
    pack = json.loads((spool / "score" / "globe_000000000002.json").read_text())
    s = pack["sats"][0]

    # replay exactly what web/globe/index.html does at a sample epoch
    ts = load.timescale()
    sat = EarthSatellite(s["l1"], s["l2"], s["name"], ts)
    base = datetime.strptime(pack["base"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    for k in range(len(s["ric_m"]) // 3):
        t = base + timedelta(seconds=s["t0_s"] + k * pack["step_s"])
        g = sat.at(ts.from_datetime(t))
        r = tuple(float(x) for x in g.position.km)
        v = tuple(float(x) for x in g.velocity.km_per_s)
        R = frames.unit(r)
        C = frames.unit(frames.cross(r, v))
        I = frames.cross(C, R)
        d = [s["ric_m"][3 * k + j] / 1000 for j in range(3)]
        dv = tuple(R[i] * d[0] + I[i] * d[1] + C[i] * d[2] for i in range(3))
        recon = tuple(r[i] - dv[i] for i in range(3))
        truth = shift(r, v)                       # the operator file was generated from this rule
        assert math.dist(recon, truth) < 1e-3, f"sample {k}: reconstruction is {math.dist(recon, truth):.1f} km out"
        assert abs(frames.norm(recon) - frames.norm(truth)) < 1e-3


def test_pack_refuses_rows_without_the_public_frame(tmp_path):
    """A pack built from rows scored before the frame fix would draw satellites off their orbits, so
    it must fail loudly rather than publish."""
    import globe_pack  # noqa: PLC0415
    import pytest  # noqa: PLC0415
    rows = [{"norad": 1, "epoch": "2026-09-02T06:00:00Z", "dist_km": 2.0, "age_h": 3.0, "alt_km": 500.0,
             "radial_km": 1.0, "intrack_km": 1.0, "cross_km": 1.0}]
    with pytest.raises(ValueError, match="public-frame decomposition"):
        globe_pack.build_pack({"eval_step_min": 60.0, "inputs": {}, "as_of": "", "method": "",
                               "counts": {}, "summary": {"overall": None}}, rows, None)


def test_a_failed_pack_leaves_the_cycle_pending_not_silently_done(tmp_path, monkeypatch):
    """The report file is the completion marker, and it was written before the globe pack was
    built. A pack failure therefore left the marker behind and the cycle was never retried: the
    next pass reported clean with nothing pending, for a cycle that has no pack.

    Mutation: write the report before building the pack and this goes red."""
    import globe_pack  # noqa: PLC0415
    spool = tmp_path / "spool"
    l1, l2 = tle("25544")
    c = "cycle_000000000002"
    make_cycle(spool, [write_meme(spool / c / "files", 25544, "STARLINK-1", l1, l2)], c)
    set_first_seen(spool, c, T0)
    make_snapshot(spool, [gp_row(25544, "STARLINK-1", l1, l2)])

    def boom(*a, **k):
        raise RuntimeError("simulated pack failure")

    monkeypatch.setattr(globe_pack, "build_pack", boom)
    res = run.one_pass(spool, max_cycles=1, workers=1, eval_step_min=60)
    assert res["errors"] and res["scored"] == []
    assert not (spool / "score" / "visibility_000000000002.json").exists(), \
        "a completion marker was left behind for a cycle that did not complete"

    monkeypatch.undo()
    res2 = run.one_pass(spool, max_cycles=1, workers=1, eval_step_min=60)
    assert [s["cycle"] for s in res2["scored"]] == [c], "the failed cycle was never retried"
    assert (spool / "score" / "globe_000000000002.json").exists()


def test_a_limited_run_never_writes_the_published_filename(tmp_path):
    """--limit scores a handful of files for development. It wrote the production filename, so a
    partial score could be picked up by the site build and published as the cycle's figures.

    Mutation: drop the partial_ prefix and this goes red."""
    spool = tmp_path / "spool"
    l1, l2 = tle("25544")
    m1, m2 = tle("26000", "15.05000000")
    c = "cycle_000000000002"
    files = spool / c / "files"
    names = [write_meme(files, 25544, "STARLINK-1", l1, l2), write_meme(files, 26000, "STARLINK-2", m1, m2)]
    make_cycle(spool, names, c)
    set_first_seen(spool, c, T0)
    make_snapshot(spool, [gp_row(25544, "STARLINK-1", l1, l2), gp_row(26000, "STARLINK-2", m1, m2)])
    run.one_pass(spool, max_cycles=1, workers=1, eval_step_min=60, limit=1)
    out = spool / "score"
    assert not (out / "visibility_000000000002.json").exists(), "a partial score took the published name"
    assert (out / "partial_visibility_000000000002.json").exists()
    # and the cycle is still owed a real score
    res = run.one_pass(spool, max_cycles=1, workers=1, eval_step_min=60)
    assert [s["cycle"] for s in res["scored"]] == [c]
    assert (out / "visibility_000000000002.json").exists()


def test_scoring_verifies_the_provenance_it_publishes(tmp_path):
    """Every report states the cycle's Merkle root, the manifest digest and the catalogue snapshot's
    SHA-256, and none of the three was checked before this. Mutating an input changed the numbers
    while the report went on claiming the same hashes, which is the one thing this project must
    never do.

    Mutation: drop verify_cycle_inputs() or the catalogue digest check and these go red."""
    import catalogue as cat  # noqa: PLC0415
    import pytest  # noqa: PLC0415

    def fresh(tag: str):
        spool = tmp_path / tag
        l1, l2 = tle("25544")
        c = "cycle_000000000002"
        make_cycle(spool, [write_meme(spool / c / "files", 25544, "STARLINK-1", l1, l2)], c)
        set_first_seen(spool, c, T0)
        snap = make_snapshot(spool, [gp_row(25544, "STARLINK-1", l1, l2)])
        return spool, c, snap

    spool, c, _ = fresh("healthy")
    assert run.one_pass(spool, max_cycles=1, workers=1, eval_step_min=60)["errors"] == []
    assert (spool / "score" / f"visibility_{c[6:]}.json").exists()

    # 1. the catalogue bytes no longer hash to what its own record.json says
    spool, c, snap = fresh("badcat")
    rows = json.load(gzip.open(snap / "gp.json.gz", "rb"))
    rows[0]["OBJECT_NAME"] = "TAMPERED"
    with gzip.open(snap / "gp.json.gz", "wb") as gz:
        gz.write(json.dumps(rows).encode())
    with pytest.raises(ValueError, match="does not match"):
        cat.load(snap)
    res = run.one_pass(spool, max_cycles=1, workers=1, eval_step_min=60)
    assert res["errors"] and not (spool / "score" / f"visibility_{c[6:]}.json").exists()

    # 2. the record's own digests no longer rebuild the root the report would publish
    spool, c, _ = fresh("badroot")
    rp = spool / c / "cycle.json"
    r = json.loads(rp.read_text())
    r["merkle_root"] = "ff" * 32
    rp.write_text(json.dumps(r))
    res = run.one_pass(spool, max_cycles=1, workers=1, eval_step_min=60)
    assert res["errors"] and not (spool / "score" / f"visibility_{c[6:]}.json").exists()

    # 3. MANIFEST.txt is not the manifest whose digest names the cycle
    spool, c, _ = fresh("badmanifest")
    (spool / c / "MANIFEST.txt").write_bytes(b"MEME_1_SOMETHING_ELSE.txt\n")
    res = run.one_pass(spool, max_cycles=1, workers=1, eval_step_min=60)
    assert res["errors"] and not (spool / "score" / f"visibility_{c[6:]}.json").exists()

    # 4. a stored ephemeris no longer hashes to what the record says: counted, never scored
    spool, c, _ = fresh("badfile")
    r = json.loads((spool / c / "cycle.json").read_text())
    gz = spool / c / "files" / (r["files"][0]["name"] + ".gz")
    gz.write_bytes(gzip.compress(gzip.decompress(gz.read_bytes()).replace(b"blend", b"BLEND")))
    res = run.one_pass(spool, max_cycles=1, workers=1, eval_step_min=60)
    rep = json.loads((spool / "score" / f"visibility_{c[6:]}.json").read_text())
    assert rep["counts"]["corrupt"] == 1 and rep["counts"]["scored"] == 0
    assert rep["satellites"]["corrupt"], "a file that no longer matches the record was scored anyway"


def test_a_hostile_catalogue_name_cannot_become_markup(tmp_path):
    """Object names come from an outside catalogue and are written into the globe page. They reached
    two innerHTML assignments unescaped, so a feed value could run script for every visitor.

    Defended twice on purpose: the pack constrains the name to the characters real ones use, and the
    page escapes what it is given anyway. Mutation: drop safe_name() and this goes red; drop the
    page's esc() and the browser test in web/tests goes red."""
    import globe_pack  # noqa: PLC0415
    spool = tmp_path / "spool"
    l1, l2 = tle("25544")
    c = "cycle_000000000002"
    make_cycle(spool, [write_meme(spool / c / "files", 25544, "STARLINK-1", l1, l2)], c)
    set_first_seen(spool, c, T0)
    hostile = '<img src=x onerror="alert(1)">'
    make_snapshot(spool, [gp_row(25544, hostile, l1, l2)])
    run.one_pass(spool, max_cycles=1, workers=1, eval_step_min=60)
    pack = json.loads((spool / "score" / "globe_000000000002.json").read_text())
    name = pack["sats"][0]["name"]
    assert "<" not in name and ">" not in name and '"' not in name, f"markup survived into the pack: {name!r}"
    assert globe_pack.safe_name("STARLINK-34600") == "STARLINK-34600"      # real names are untouched
    assert globe_pack.safe_name("A" * 200) == "A" * 64                     # and bounded
