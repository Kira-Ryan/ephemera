"""Caller-level tests for score/visibility.py: a synthetic cycle whose operator files are generated
from a known public element set with the same propagator must score at zero distance; a file shifted
by a known radial offset must report exactly that; missing, decayed and malformed inputs are counted
and surfaced, never skipped silently."""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ephem  # noqa: E402
import frames  # noqa: E402
import visibility  # noqa: E402

ISS = ("1 25544U 98067A   26245.50000000  .00016717  00000-0  10270-3 0  9005",
       "2 25544  51.6400 208.9000 0006700  90.0000 270.0000 15.50000000000000")
T0 = datetime(2026, 9, 2, 9, 10, 42, tzinfo=timezone.utc)


def checksum(line: str) -> str:
    s = sum(int(c) if c.isdigit() else 1 if c == "-" else 0 for c in line[:68])
    return line[:68] + str(s % 10)


def tle(norad_field: str, mean_motion: str = "15.50000000") -> tuple[str, str]:
    l1 = ISS[0][:2] + norad_field.rjust(5) + ISS[0][7:]
    l2 = ISS[1][:2] + norad_field.rjust(5) + ISS[1][7:52] + mean_motion + ISS[1][63:]
    return checksum(l1), checksum(l2)


def write_meme(files: Path, norad: int, name: str, line1: str, line2: str, hours: float = 3.0, shift=None) -> str:
    """Generate an operator-format file from the element set with Skyfield (GCRS positions), so the
    scorer's own propagation reproduces it exactly; `shift(pos, vel) -> pos` perturbs positions."""
    from skyfield.api import EarthSatellite, load
    ts = load.timescale()
    sat = EarthSatellite(line1, line2, name, ts)
    n = int(hours * 60) + 1
    epochs = [T0 + timedelta(seconds=60 * i) for i in range(n)]
    g = sat.at(ts.from_datetimes(epochs))
    xyz, vxyz = g.position.km, g.velocity.km_per_s
    out = ["created:2026-09-02 09:30:50 UTC",
           f"ephemeris_start:{T0:%Y-%m-%d %H:%M:%S} UTC ephemeris_stop:{epochs[-1]:%Y-%m-%d %H:%M:%S} UTC step_size:60",
           "ephemeris_source:blend", "UVW"]
    for i, e in enumerate(epochs):
        pos = (float(xyz[0][i]), float(xyz[1][i]), float(xyz[2][i]))
        vel = (float(vxyz[0][i]), float(vxyz[1][i]), float(vxyz[2][i]))
        if shift:
            pos = shift(pos, vel)
        doy = (e - datetime(e.year, 1, 1, tzinfo=timezone.utc)).days + 1
        out.append(f"{e.year}{doy:03d}{e:%H%M%S}.000 " + " ".join(f"{c:.10f}" for c in pos + vel))
        out += ["0.0 0.0 0.0 0.0 0.0 0.0 0.0"] * 3
    fname = f"MEME_{norad}_{name}_2450923_Operational_1472635440_UNCLASSIFIED.txt"
    files.mkdir(parents=True, exist_ok=True)
    with gzip.open(files / (fname + ".gz"), "wb") as gz:
        gz.write(("\n".join(out) + "\n").encode("ascii"))
    return fname


def make_cycle(spool: Path, names: list[str], cycle: str = "cycle_abcdef123456") -> Path:
    d = spool / cycle
    d.mkdir(parents=True, exist_ok=True)
    (d / "MANIFEST.txt").write_text("\n".join(names) + "\n")
    (d / "cycle.json").write_text(json.dumps({"status": "complete", "merkle_root": "ab" * 32, "manifest_sha256": "cd" * 32}))
    return d


def make_snapshot(spool: Path, rows: list[dict], stamp: str = "20260902T200733Z") -> Path:
    raw = json.dumps(rows).encode()
    sha = hashlib.sha256(raw).hexdigest()
    d = spool / "gp" / f"{stamp}_{sha[:12]}"
    d.mkdir(parents=True)
    with gzip.open(d / "gp.json.gz", "wb") as gz:
        gz.write(raw)
    (d / "record.json").write_text(json.dumps({"sha256": sha, "fetched_utc": "2026-09-02T20:07:33Z", "records": len(rows)}))
    return d


def gp_row(norad: int, name: str, l1: str, l2: str, epoch: str = "2026-09-02T12:00:00.000000", decay: str | None = None) -> dict:
    return {"NORAD_CAT_ID": str(norad), "OBJECT_NAME": name, "EPOCH": epoch, "TLE_LINE1": l1, "TLE_LINE2": l2, "DECAY_DATE": decay}


def run(spool: Path, cycle: str, *extra) -> tuple[int, dict]:
    """Runs the CLI with --rows and returns the report with the rows file's content attached."""
    out = spool / "out"
    rc = visibility.main(["--spool", str(spool), "--cycle", cycle, "--out", str(out), "--eval-step-min", "60", "--rows", *extra])
    reports = list(out.glob("visibility_*.json"))
    if not reports:
        return rc, {}
    rep = json.loads(reports[0].read_text())
    assert "rows" not in rep                                            # the summary stays small
    with gzip.open(out / rep["rows_file"], "rt", encoding="utf-8") as gz:
        rep["rows"] = json.load(gz)
    return rc, rep


def test_identical_inputs_score_zero_and_report_carries_inputs(tmp_path):
    spool = tmp_path / "spool"
    l1, l2 = tle("25544")
    m1, m2 = tle("A0224", "15.05000000")           # six-digit id 100224 in Alpha-5 form
    names = [write_meme(spool / "cycle_abcdef123456" / "files", 25544, "STARLINK-1", l1, l2),
             write_meme(spool / "cycle_abcdef123456" / "files", 100224, "STARLINK-6", m1, m2)]
    make_cycle(spool, names)
    snap = make_snapshot(spool, [gp_row(25544, "STARLINK-1", l1, l2), gp_row(100224, "STARLINK-6", m1, m2)])
    rc, rep = run(spool, "cycle_abcdef123456")
    assert rc == 0
    assert rep["counts"] == {"files": 2, "scored": 2, "no_public_set": 0, "decayed_set": 0, "propagation_failed": 0, "unreadable": 0}
    assert sorted(rep["satellites"]["scored"]) == [25544, 100224]
    assert len(rep["rows"]) == 2 * 4                                   # 3 h at 60 s step, sampled hourly: t=0,1,2,3
    assert max(r["dist_km"] for r in rep["rows"]) < 1e-6
    ages = {r["age_h"] for r in rep["rows"]}
    assert min(ages) < 0 < max(ages)                                    # element epoch 12:00 sits inside the 09:10-12:10 span
    assert rep["inputs"]["cycle"] == "cycle_abcdef123456" and rep["inputs"]["merkle_root"] == "ab" * 32
    assert rep["inputs"]["catalogue_snapshot"] == snap.name and rep["inputs"]["catalogue_sha256"] == json.loads((snap / "record.json").read_text())["sha256"]
    assert rep["as_of"].endswith("Z") and "SGP4" in rep["method"] and "planned trajectory changes" in rep["method"]
    ov = rep["summary"]["overall"]
    assert ov["n"] == 8 and ov["within_km"] == {"1": 1.0, "10": 1.0, "30": 1.0}
    assert {b["bin"] for b in rep["summary"]["by_age"]} == {"set newer than epoch", "0-6 h"}
    shells = {b["bin"] for b in rep["summary"]["by_shell"]}
    assert shells == {"400-500 km", "500-600 km"}                       # 15.5 rev/day flies at ~420 km, 15.05 at ~550 km


def test_radial_shift_is_reported_as_distance_and_radial_component(tmp_path):
    spool = tmp_path / "spool"
    l1, l2 = tle("25544")
    shift = lambda pos, vel: tuple(c + 5.0 * u for c, u in zip(pos, frames.unit(pos)))   # noqa: E731 - +5 km radial
    names = [write_meme(spool / "cycle_abcdef123456" / "files", 25544, "STARLINK-1", l1, l2, shift=shift)]
    make_cycle(spool, names)
    make_snapshot(spool, [gp_row(25544, "STARLINK-1", l1, l2)])
    rc, rep = run(spool, "cycle_abcdef123456")
    assert rc == 0
    for r in rep["rows"]:
        assert abs(r["dist_km"] - 5.0) < 1e-6
        assert abs(r["radial_km"] + 5.0) < 1e-6                        # public minus operator: operator sits 5 km further out
        assert abs(r["intrack_km"]) < 1e-6 and abs(r["cross_km"]) < 1e-6
    ov = rep["summary"]["overall"]
    assert ov["median_km"] == 5.0 and ov["within_km"] == {"1": 0.0, "10": 1.0, "30": 1.0}


def test_missing_decayed_and_malformed_are_counted_not_skipped(tmp_path, caplog):
    spool = tmp_path / "spool"
    l1, l2 = tle("25544")
    d1, d2 = tle("40000")
    files = spool / "cycle_abcdef123456" / "files"
    names = [write_meme(files, 25544, "STARLINK-1", l1, l2),
             write_meme(files, 40000, "STARLINK-2", d1, d2),
             write_meme(files, 41000, "STARLINK-3", l1, l2)]
    bad = files / (names[0] + ".gz")
    with gzip.open(bad, "rb") as gz:
        text = gz.read().decode()
    with gzip.open(bad, "wb") as gz:
        gz.write(text.replace("\n0.0 0.0 0.0 0.0 0.0 0.0 0.0\n", "\n0.0 0.0\n", 1).encode())   # one covariance line truncated
    make_cycle(spool, names)
    make_snapshot(spool, [gp_row(25544, "STARLINK-1", l1, l2), gp_row(40000, "STARLINK-2", d1, d2, decay="2026-08-01")])
    rc, rep = run(spool, "cycle_abcdef123456")
    assert rc == 1                                                      # an unreadable file fails the run
    assert rep["counts"] == {"files": 3, "scored": 0, "no_public_set": 1, "decayed_set": 1, "propagation_failed": 0, "unreadable": 1}
    assert rep["satellites"]["no_public_set"] == [41000] and rep["satellites"]["decayed_set"] == [40000]
    assert rep["satellites"]["unreadable"] == [names[0]]
    assert any("unreadable" in m and "covariance" in m for m in caplog.messages)
    assert rep["summary"]["overall"] is None and rep["rows"] == []


def test_limit_scores_only_the_first_manifest_entries(tmp_path):
    spool = tmp_path / "spool"
    l1, l2 = tle("25544")
    files = spool / "cycle_abcdef123456" / "files"
    names = [write_meme(files, 25544, "STARLINK-1", l1, l2), write_meme(files, 26000, "STARLINK-2", *tle("26000"))]
    make_cycle(spool, names)
    make_snapshot(spool, [gp_row(25544, "STARLINK-1", l1, l2), gp_row(26000, "STARLINK-2", *tle("26000"))])
    rc, rep = run(spool, "cycle_abcdef123456", "--limit", "1")
    assert rc == 0 and rep["counts"]["files"] == 1 and rep["counts"]["scored"] == 1 and rep["inputs"]["limit"] == 1


def test_parser_reads_real_layout_and_refuses_bad_shapes(tmp_path):
    l1, l2 = tle("25544")
    name = write_meme(tmp_path, 25544, "STARLINK-1", l1, l2, hours=0.1)   # 7 records
    e = ephem.read(tmp_path / (name + ".gz"))
    assert (e.norad, e.object_name, e.step_s, e.source, e.cov_frame, e.record_count) == (25544, "STARLINK-1", 60, "blend", "UVW", 7)
    assert e.start == T0 and e.records[0].epoch == T0 and e.records[-1].epoch == T0 + timedelta(minutes=6)
    assert len(e.records[0].cov) == 21
    sampled = ephem.read(tmp_path / (name + ".gz"), [0, 6])
    assert [r.epoch for r in sampled.records] == [T0, T0 + timedelta(minutes=6)]
    with pytest.raises(ValueError, match="outside"):
        ephem.read(tmp_path / (name + ".gz"), [7])
    assert ephem.parse_epoch("2026245091042.000") == T0
    assert ephem.parse_name("MEME_100001_STARLINK-38128_2450910_Operational_1472634660_UNCLASSIFIED.txt.gz") == (100001, "STARLINK-38128")
    with pytest.raises(ValueError):
        ephem.parse_name("MANIFEST.txt")
    bad = tmp_path / "MEME_1_X_1_Operational_1_UNCLASSIFIED.txt"
    bad.write_text("created:2026-09-02 09:30:50 UTC\nnonsense\nephemeris_source:blend\nUVW\n")
    with pytest.raises(ValueError, match="line 2"):
        ephem.read(bad)


def test_ric_components_by_hand():
    r, v = (7000.0, 0.0, 0.0), (0.0, 7.5, 0.0)
    assert frames.ric_components((5.0, 0.0, 0.0), r, v) == pytest.approx((5.0, 0.0, 0.0))
    assert frames.ric_components((0.0, 2.0, 0.0), r, v) == pytest.approx((0.0, 2.0, 0.0))
    assert frames.ric_components((0.0, 0.0, -3.0), r, v) == pytest.approx((0.0, 0.0, -3.0))
    assert visibility.eval_indices(4321, 60, 360) == list(range(0, 4321, 360))
    assert visibility.summarise([])["overall"] is None
