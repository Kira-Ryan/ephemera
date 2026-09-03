#!/usr/bin/env python3
"""Catalogue visibility, v0 (concept, scoreboard 2): how far the public element set, propagated with
SGP4, sits from the operator-published trajectory at common epochs.

For every file in an archived cycle: the matching public element set (same NORAD id) from a
catalogue snapshot is propagated with Skyfield (python-sgp4 underneath, TEME to GCRS by Skyfield;
GCRS is J2000 to within a metre here, probe P6) to the file's own record epochs every
`--eval-step-min` minutes, and differenced against the file position (EME2000). Each row carries
the distance in km, its radial / in-track / cross-track components in the operator's frame, the
operator's geocentric altitude, and the signed element age (evaluation epoch minus element-set
epoch). The summary bins rows by element age and by altitude shell and reports, per bin, the
median and 90th-percentile distance and the share of rows within each threshold - the catalogue
visibility fraction at 1, 10 and 30 km.

What it is not: it is not an error of the satellite, and it is not a statement about which side is
right. Both inputs are predictions. The operator's contains planned trajectory changes the public
set cannot know about. The report says so in its `method` field and every number carries the
inputs it came from: cycle id and root, snapshot id and hash, as-of time.

Input is the archive only (spool); nothing here talks to a live feed. Files that cannot be parsed
are counted under `unreadable`, logged with the parser's message, and make the run exit 1. A file
with no public set, or whose set is marked decayed, is counted, not scored. Output is
`visibility_<sha12>.json` (summary, no rows) and, with `--rows`, `visibility_<sha12>_rows.json.gz`.
`--workers N` parses and propagates files in N processes; results are identical to one process.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import math
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalogue as cat  # noqa: E402
import ephem  # noqa: E402
import frames  # noqa: E402

SCHEMA = 1
EARTH_RADIUS_KM = 6378.137
THRESHOLDS_KM = (1.0, 10.0, 30.0)
AGE_BINS_H = ((None, 0.0, "set newer than epoch"), (0.0, 6.0, "0-6 h"), (6.0, 12.0, "6-12 h"),
              (12.0, 24.0, "12-24 h"), (24.0, 48.0, "24-48 h"), (48.0, 72.0, "48-72 h"), (72.0, None, "over 72 h"))
SHELLS_KM = ((None, 400.0, "under 400 km"), (400.0, 500.0, "400-500 km"), (500.0, 600.0, "500-600 km"),
             (600.0, None, "over 600 km"))

log = logging.getLogger("ephemera.score.visibility")
_TS = None


def timescale():
    global _TS
    if _TS is None:
        from skyfield.api import load  # noqa: PLC0415 - heavy import kept out of module load
        _TS = load.timescale()
    return _TS


def eval_indices(record_count: int, step_s: int, eval_step_min: float) -> list[int]:
    every = max(1, int(round(eval_step_min * 60 / step_s)))
    return list(range(0, record_count, every))


def score_file(eph: ephem.Ephemeris, es: cat.ElementSet, ts, earth_satellite_cls) -> list[dict]:
    sat = earth_satellite_cls(es.line1, es.line2, es.name, ts)
    t = ts.from_datetimes([r.epoch for r in eph.records])
    xyz = sat.at(t).position.km
    rows = []
    for k, rec in enumerate(eph.records):
        p = (float(xyz[0][k]), float(xyz[1][k]), float(xyz[2][k]))
        if any(math.isnan(c) for c in p):
            raise ArithmeticError(f"SGP4 returned NaN for {es.norad} at {rec.epoch.isoformat()}")
        d = frames.sub(p, rec.pos)
        radial, intrack, cross = frames.ric_components(d, rec.pos, rec.vel)
        rows.append({"norad": eph.norad, "epoch": rec.epoch.strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "age_h": round((rec.epoch - es.epoch).total_seconds() / 3600, 3),
                     "alt_km": round(frames.norm(rec.pos) - EARTH_RADIUS_KM, 3),
                     "dist_km": round(frames.norm(d), 6), "radial_km": round(radial, 6),
                     "intrack_km": round(intrack, 6), "cross_km": round(cross, 6)})
    return rows


def score_one(task: tuple) -> tuple:
    """One file, in whatever process this runs in: ('scored', norad, rows) | ('unreadable', name, msg)
    | ('propagation_failed', norad, msg)."""
    path, name, es_fields, eval_step_min = task
    es = cat.ElementSet(*es_fields)
    try:
        lines = ephem.read_lines(Path(path))
        n = ephem.record_count(lines)
        step = int(lines[1].rsplit("step_size:", 1)[1])
        eph = ephem.read(Path(path), eval_indices(n, step, eval_step_min))
    except (ValueError, OSError, IndexError) as e:
        return ("unreadable", name, str(e))
    try:
        from skyfield.api import EarthSatellite  # noqa: PLC0415
        return ("scored", es.norad, score_file(eph, es, timescale(), EarthSatellite))
    except (ArithmeticError, ValueError) as e:
        return ("propagation_failed", es.norad, str(e))


def _bin(value: float, bins) -> str:
    for lo, hi, label in bins:
        if (lo is None or value >= lo) and (hi is None or value < hi):
            return label
    raise ValueError(f"{value} fits no bin")


def _stats(rows: list[dict]) -> dict:
    ds = sorted(r["dist_km"] for r in rows)
    n = len(ds)
    return {"n": n, "median_km": round(statistics.median(ds), 3),
            "p90_km": round(ds[min(n - 1, int(math.ceil(0.9 * n)) - 1)], 3),
            "mean_age_h": round(sum(r["age_h"] for r in rows) / n, 2),
            "within_km": {str(int(t)): round(sum(1 for d in ds if d <= t) / n, 4) for t in THRESHOLDS_KM}}


def summarise(rows: list[dict]) -> dict:
    if not rows:
        return {"overall": None, "by_age": [], "by_shell": []}
    by_age = {label: [] for _, _, label in AGE_BINS_H}
    by_shell = {label: [] for _, _, label in SHELLS_KM}
    for r in rows:
        by_age[_bin(r["age_h"], AGE_BINS_H)].append(r)
        by_shell[_bin(r["alt_km"], SHELLS_KM)].append(r)
    return {"overall": _stats(rows),
            "by_age": [{"bin": k, **_stats(v)} for k, v in by_age.items() if v],
            "by_shell": [{"bin": k, **_stats(v)} for k, v in by_shell.items() if v]}


def score_cycle(cycle_dir: Path, catalogue: cat.Catalogue, eval_step_min: float, limit: int = 0,
                workers: int = 1) -> tuple[dict, list[dict], dict]:
    names = (cycle_dir / "MANIFEST.txt").read_text().split()
    if limit:
        names = names[:limit]
    counts = {"files": len(names), "scored": 0, "no_public_set": 0, "decayed_set": 0, "propagation_failed": 0, "unreadable": 0}
    satellites = {"scored": [], "no_public_set": [], "decayed_set": [], "propagation_failed": [], "unreadable": []}
    rows: list[dict] = []
    tasks = []
    for name in names:
        path = cycle_dir / "files" / (name + ".gz")
        if not path.exists():
            path = cycle_dir / "files" / name
        try:
            norad, _ = ephem.parse_name(name)
        except ValueError as e:
            log.error("%s", e)
            counts["unreadable"] += 1
            satellites["unreadable"].append(name)
            continue
        es = catalogue.sets.get(norad)
        if es is None:
            counts["no_public_set"] += 1
            satellites["no_public_set"].append(norad)
            continue
        if es.decay_date:
            counts["decayed_set"] += 1
            satellites["decayed_set"].append(norad)
            continue
        tasks.append((str(path), name, (es.norad, es.name, es.epoch, es.line1, es.line2, es.decay_date), eval_step_min))
    if workers > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(score_one, tasks, chunksize=32))
    else:
        results = [score_one(t) for t in tasks]
    for kind, key, payload in results:
        if kind == "scored":
            rows.extend(payload)
        else:
            log.error("%s %s: %s", kind.replace("_", " "), key, payload)
        counts[kind] += 1
        satellites[kind].append(key)
    return counts, rows, satellites


def build_report(cycle_dir: Path, catalogue: cat.Catalogue, eval_step_min: float, limit: int = 0,
                 workers: int = 1, extra_inputs: dict | None = None) -> tuple[dict, list[dict]]:
    import sgp4  # noqa: PLC0415
    import skyfield  # noqa: PLC0415
    rec = json.loads((cycle_dir / "cycle.json").read_text())
    counts, rows, satellites = score_cycle(cycle_dir, catalogue, eval_step_min, limit, workers)
    report = {
        "schema": SCHEMA, "kind": "catalogue_visibility_v0",
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": ("Public element set (Space-Track gp snapshot) propagated with SGP4 "
                   f"(skyfield {skyfield.__version__}, python-sgp4 {sgp4.__version__}; TEME to GCRS by Skyfield, "
                   "taken as J2000) and differenced against the operator-published trajectory (EME2000) at the "
                   f"file's own record epochs every {eval_step_min:g} min. Distance in km; components in the "
                   "operator's radial/in-track/cross-track frame; altitude is geocentric radius minus 6378.137 km; "
                   "element age is evaluation epoch minus element-set epoch, signed. Both inputs are predictions; "
                   "the operator's includes planned trajectory changes the public set cannot know about."),
        "inputs": {"cycle": cycle_dir.name, "first_seen_utc": rec.get("first_seen_utc"),
                   "merkle_root": rec.get("merkle_root"), "manifest_sha256": rec.get("manifest_sha256"),
                   "catalogue_snapshot": catalogue.snapshot_id, "catalogue_sha256": catalogue.sha256,
                   "catalogue_fetched_utc": catalogue.fetched_utc, "catalogue_sets": len(catalogue.sets),
                   "limit": limit or None, **(extra_inputs or {})},
        "eval_step_min": eval_step_min, "thresholds_km": list(THRESHOLDS_KM),
        "counts": counts, "summary": summarise(rows), "satellites": satellites,
    }
    return report, rows


def write_outputs(report: dict, rows: list[dict], out_dir: Path, keep_rows: bool) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    sha12 = report["inputs"]["cycle"].removeprefix("cycle_")
    out = out_dir / f"visibility_{sha12}.json"
    if keep_rows:
        with gzip.open(out_dir / f"visibility_{sha12}_rows.json.gz", "wt", encoding="utf-8") as gz:
            json.dump(rows, gz)
        report = {**report, "rows_file": f"visibility_{sha12}_rows.json.gz"}
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return out


def log_summary(report: dict, rows: list[dict], out: Path) -> None:
    c = report["counts"]
    log.info("%s vs %s: %d files, %d scored (%d rows), %d without a public set, %d decayed sets, %d propagation failures, %d unreadable -> %s",
             report["inputs"]["cycle"], report["inputs"]["catalogue_snapshot"], c["files"], c["scored"], len(rows),
             c["no_public_set"], c["decayed_set"], c["propagation_failed"], c["unreadable"], out)
    if report["summary"]["overall"]:
        for b in report["summary"]["by_age"]:
            log.info("  age %-22s n=%-6d median %8.3f km  p90 %9.3f km  within 1/10/30 km: %s", b["bin"], b["n"], b["median_km"], b["p90_km"],
                     " / ".join(f"{b['within_km'][k]:.3f}" for k in ("1", "10", "30")))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spool", type=Path, required=True)
    ap.add_argument("--cycle", required=True, help="cycle directory name under the spool, e.g. cycle_f5112bb77a2a")
    ap.add_argument("--gp", default="latest", help="catalogue snapshot directory name under <spool>/gp, or 'latest'")
    ap.add_argument("--out", type=Path, required=True, help="output directory; writes visibility_<cycle sha12>.json")
    ap.add_argument("--eval-step-min", type=float, default=360.0)
    ap.add_argument("--limit", type=int, default=0, help="score only the first N manifest entries (development)")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--rows", action="store_true", help="also write every scored row, gzipped, beside the report")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cycle_dir = args.spool / args.cycle
    if not (cycle_dir / "MANIFEST.txt").exists():
        log.error("no MANIFEST.txt in %s", cycle_dir)
        return 2
    snap = cat.latest_snapshot(args.spool) if args.gp == "latest" else args.spool / "gp" / args.gp
    catalogue = cat.load(snap)
    report, rows = build_report(cycle_dir, catalogue, args.eval_step_min, args.limit, args.workers)
    out = write_outputs(report, rows, args.out, args.rows)
    log_summary(report, rows, out)
    return 1 if report["counts"]["unreadable"] else 0


if __name__ == "__main__":
    sys.exit(main())
