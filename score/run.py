#!/usr/bin/env python3
"""Score the archive's cycles one by one and build each one's globe pack (run by the
Ephemera-Score scheduled task, pythonw, no console; also by hand).

Each pass: list complete cycles (a Merkle root) whose local files are still present and that have
no report yet, newest first, and score up to `--max-cycles` of them against their paired
catalogue snapshot. Pairing: the latest snapshot fetched at or before the cycle's first-seen time
("before_cycle"); if none exists, because the cycle predates the catalogue feed, the earliest
snapshot, flagged "after_cycle" so the age bins are read accordingly. Cycles whose files are gone
(shipped to cold storage and deleted locally before they were scored) are listed in run.json under
`skipped_no_files` every pass; nothing is skipped silently. Outputs go to `<spool>/score/`:
`visibility_<sha12>.json`, `visibility_<sha12>_rows.json.gz`, `globe_<sha12>.json`, `run.json`.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import catalogue as cat  # noqa: E402
import globe_pack  # noqa: E402
import visibility  # noqa: E402

log = logging.getLogger("ephemera.score.run")


def parse_utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def snapshots(spool: Path) -> list[tuple[datetime, Path]]:
    out = []
    for rec in sorted((spool / "gp").glob("*/record.json")):
        out.append((parse_utc(json.loads(rec.read_text())["fetched_utc"]), rec.parent))
    return sorted(out)


def pair_snapshot(snaps: list[tuple[datetime, Path]], first_seen: datetime) -> tuple[Path, str]:
    before = [p for t, p in snaps if t <= first_seen]
    if before:
        return before[-1], "before_cycle"
    return snaps[0][1], "after_cycle"


def candidates(spool: Path, out_dir: Path) -> tuple[list[tuple[datetime, Path]], list[str], list[str]]:
    """(scoreable newest-first, skipped_no_files, skipped_no_root)"""
    todo, no_files, no_root = [], [], []
    for cdir in sorted(spool.glob("cycle_*")):
        rec_path = cdir / "cycle.json"
        if not rec_path.exists():
            continue
        rec = json.loads(rec_path.read_text())
        if not rec.get("merkle_root"):
            no_root.append(cdir.name)
            continue
        if (out_dir / f"visibility_{cdir.name.removeprefix('cycle_')}.json").exists():
            continue        # a partial_ report is development output and never counts as done
        if not (cdir / "files").exists() or not any((cdir / "files").iterdir()):
            no_files.append(cdir.name)
            continue
        todo.append((parse_utc(rec["first_seen_utc"]), cdir))
    todo.sort(reverse=True)
    return todo, no_files, no_root


def one_pass(spool: Path, max_cycles: int, workers: int, eval_step_min: float, limit: int = 0) -> dict:
    out_dir = spool / "score"
    out_dir.mkdir(parents=True, exist_ok=True)
    snaps = snapshots(spool)
    todo, no_files, no_root = candidates(spool, out_dir)
    result = {"as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "scored": [], "errors": [],
              "skipped_no_files": no_files, "skipped_no_root": no_root, "pending": [c.name for _, c in todo]}
    if not snaps:
        log.error("no catalogue snapshots under %s - nothing can be scored", spool / "gp")
        result["errors"].append("no catalogue snapshots")
    for first_seen, cdir in ([] if not snaps else todo[:max_cycles]):
        snap, relation = pair_snapshot(snaps, first_seen)
        t0 = time.monotonic()
        log.info("scoring %s (first seen %s) against %s (%s), %d workers", cdir.name, first_seen.strftime("%Y-%m-%dT%H:%MZ"),
                 snap.name, relation, workers)
        try:
            catalogue = cat.load(snap)
            report, rows = visibility.build_report(cdir, catalogue, eval_step_min, limit, workers,
                                                   {"snapshot_relation": relation})
            # The report file is what candidates() reads as "this cycle is done", so it is written
            # last. Building the pack first means a pack failure leaves the cycle pending and it is
            # retried, rather than being marked complete with no pack and never looked at again.
            # The pack is built before the report is written, because the report file is what
            # candidates() reads as "this cycle is done": a pack failure must leave the cycle
            # pending and retried, not marked complete with no pack and never looked at again.
            pack = globe_pack.build_pack(report, rows, catalogue) if rows else None
            out = visibility.write_outputs(report, rows, out_dir, keep_rows=True)
            visibility.log_summary(report, rows, out)
            pack_path = out_dir / f"globe_{cdir.name.removeprefix('cycle_')}.json"
            if pack is None:
                # Nothing scored. The report still gets written, because a cycle that produced no
                # comparison is a result the page has to be able to show, not a silence.
                log.error("%s: nothing could be scored, so no globe pack was built", cdir.name)
            else:
                pack_path.write_text(json.dumps(pack, separators=(",", ":")), encoding="utf-8")
                log.info("%s: pack %s (%d satellites, %.1f MB) in %.0f s", cdir.name, pack_path.name,
                         len(pack["sats"]), pack_path.stat().st_size / 1e6, time.monotonic() - t0)
            result["scored"].append({"cycle": cdir.name, "snapshot": snap.name, "relation": relation,
                                     "counts": report["counts"], "seconds": round(time.monotonic() - t0)})
            result["pending"].remove(cdir.name)
        except Exception as e:  # noqa: BLE001 - recorded loudly in run.json and the log, next cycle continues
            log.exception("scoring %s failed", cdir.name)
            result["errors"].append({"cycle": cdir.name, "error": f"{type(e).__name__}: {e}"})
    (out_dir / "run.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    log.info("score pass: %d scored, %d errors, %d pending, %d without files, %d without root",
             len(result["scored"]), len(result["errors"]), len(result["pending"]), len(no_files), len(no_root))
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spool", type=Path, required=True)
    ap.add_argument("--max-cycles", type=int, default=1)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--eval-step-min", type=float, default=360.0)
    ap.add_argument("--limit", type=int, default=0, help="score only the first N files per cycle (development)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=1800.0)
    ap.add_argument("--log-file", type=Path, default=None)
    args = ap.parse_args(argv)
    handlers = [logging.FileHandler(args.log_file, encoding="utf-8")] if args.log_file else None
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    while True:
        result = one_pass(args.spool, args.max_cycles, args.workers, args.eval_step_min, args.limit)
        if args.once:
            return 1 if result["errors"] else 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
