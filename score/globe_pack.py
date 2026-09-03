#!/usr/bin/env python3
"""Globe pack: the small per-cycle file the Cesium page draws from (DOCS/globe-vision.md, idea 1).

Per satellite it carries the public element set (the two element lines, so the browser can run
SGP4 itself) and the scored deviation, public minus operator, as radial / in-track / cross-track
integers in metres at the scorer's evaluation epochs (every `step_min` minutes from the
satellite's own first epoch, given as `t0_s` seconds after the pack's `base`). The browser
propagates the public set for the ghost and subtracts the interpolated deviation for the operator
position, so an 11,000-satellite cycle fits in a few megabytes instead of the 22 GB of files.

The deviation is decomposed in the PUBLIC satellite's frame, not the operator's. The browser only
has the public element set, so that is the only frame it can rebuild; rotating out of the operator's
frame instead was measured at 15,616 km of error on a satellite whose predictions were far apart,
which drew it off its orbit entirely.

The pack is derived from a visibility report and its rows file, never from live feeds, and
carries the same inputs (cycle id and root, snapshot id and hash) plus its own as-of time.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalogue as cat  # noqa: E402

SCHEMA = 1


def parse_utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def build_pack(report: dict, rows: list[dict], catalogue: cat.Catalogue) -> dict:
    by_sat: dict[int, list[dict]] = {}
    for r in rows:
        by_sat.setdefault(r["norad"], []).append(r)
    if not by_sat:
        raise ValueError("no rows to pack")
    missing = next((n for n, rs in by_sat.items() if "g_radial_km" not in rs[0]), None)
    if missing is not None:
        raise ValueError(
            f"rows for {missing} carry no public-frame decomposition, so a pack built from them would "
            "draw satellites off their orbits; rescore this cycle with the current score/visibility.py")
    base = min(parse_utc(rs[0]["epoch"]) for rs in by_sat.values())
    step_s = int(report["eval_step_min"] * 60)
    sats = []
    for norad, rs in sorted(by_sat.items()):
        es = catalogue.sets[norad]
        t0 = parse_utc(rs[0]["epoch"])
        for k, r in enumerate(rs):
            expect = t0.timestamp() + k * step_s
            if abs(parse_utc(r["epoch"]).timestamp() - expect) > 1.0:
                raise ValueError(f"{norad}: rows are not evenly spaced at {step_s} s (row {k})")
        sats.append({
            "id": norad, "name": es.name, "l1": es.line1, "l2": es.line2,
            "set_epoch": es.epoch.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "t0_s": int(round((t0 - base).total_seconds())),
            "alt_km": round(rs[0]["alt_km"], 1),
            "max_km": round(max(r["dist_km"] for r in rs), 3),
            "ric_m": [int(round(1000 * r[key])) for r in rs
                      for key in ("g_radial_km", "g_intrack_km", "g_cross_km")],
        })
    return {
        "schema": SCHEMA, "kind": "globe_pack_v0",
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": report["inputs"], "scored_as_of": report["as_of"],
        "method": ("Per satellite: the public element set from the catalogue snapshot, and the scored deviation "
                   "(public minus operator, radial/in-track/cross-track, metres) at the scorer's evaluation epochs. "
                   "The browser propagates the element set with SGP4 for the public position and subtracts the "
                   "deviation, interpolated linearly between evaluation epochs, for the operator position. The "
                   "deviation is given in the public satellite's radial/in-track/cross-track frame, which is the "
                   "frame the browser can rebuild exactly. The operator position is therefore a reconstruction: "
                   "measured against the archived files it lands within about a kilometre of the published "
                   "trajectory at ordinary separations, and within a few hundred kilometres for the satellites "
                   "whose predictions are thousands of kilometres apart. Both are "
                   "predictions; the operator's includes planned trajectory changes the public set cannot know about. "
                   + report["method"]),
        "base": base.strftime("%Y-%m-%dT%H:%M:%SZ"), "step_s": step_s,
        "counts": report["counts"], "summary_overall": report["summary"]["overall"],
        "sats": sats,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--rows", type=Path, required=True, help="the report's gzipped rows file")
    ap.add_argument("--spool", type=Path, required=True, help="to find the catalogue snapshot the report names")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    with gzip.open(args.rows, "rt", encoding="utf-8") as gz:
        rows = json.load(gz)
    catalogue = cat.load(args.spool / "gp" / report["inputs"]["catalogue_snapshot"])
    pack = build_pack(report, rows, catalogue)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(pack, separators=(",", ":")), encoding="utf-8")
    print(f"{args.out}: {len(pack['sats'])} satellites, {args.out.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
