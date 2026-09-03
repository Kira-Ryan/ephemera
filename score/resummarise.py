#!/usr/bin/env python3
"""Recompute the summary of existing visibility reports from their stored rows, without
re-propagating anything.

The rows are the measurement; the summary is a view of them. When the summary gains a cut (a new
bin, the at-file-start headline, the lost count), every report already on disk can be brought to
the new shape in seconds instead of re-running SGP4 over eleven thousand files. The inputs, method
and as-of time of the original run are preserved exactly, and a `resummarised_utc` field records
that the view was rebuilt and when. A report whose rows file is missing is listed and left alone.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import visibility  # noqa: E402

log = logging.getLogger("ephemera.score.resummarise")


def resummarise_one(report_path: Path) -> tuple[bool, str]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows_name = report.get("rows_file")
    if not rows_name:
        return False, "no rows_file recorded"
    rows_path = report_path.parent / rows_name
    if not rows_path.exists():
        return False, f"rows file missing: {rows_name}"
    with gzip.open(rows_path, "rt", encoding="utf-8") as gz:
        rows = json.load(gz)
    report["summary"] = visibility.summarise(rows, report["inputs"].get("catalogue_fetched_utc"))
    report["resummarised_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    start = report["summary"]["at_file_start"]
    return True, ("no rows" if start is None else
                  f"{start['satellites']:,} satellites at file start, median {start['median_km']:.2f} km, "
                  f"{100 * start['within_km']['10']:.0f}% within 10 km, {start['lost']} lost")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spool", type=Path, required=True)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    reports = sorted((args.spool / "score").glob("visibility_*.json"))
    if not reports:
        log.error("no visibility reports under %s", args.spool / "score")
        return 2
    failures = 0
    for rp in reports:
        ok, note = resummarise_one(rp)
        log.info("%s %s: %s", "rebuilt" if ok else "SKIPPED", rp.name, note)
        failures += 0 if ok else 1
    log.info("resummarised %d of %d reports", len(reports) - failures, len(reports))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
