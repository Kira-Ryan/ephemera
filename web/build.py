#!/usr/bin/env python3
"""Build the public site from the spool's records (D08: all computation at build time, the output
is static files; D18: the ledger is one record per poller per cycle, gaps and disagreement
published, never suppressed).

  python web/build.py --spool Z:/ephemera/spool

Writes the six pages of D20 (the front page, finding/, scored/, archive/, check/, and the globe with
its pack), 404.html, ledger.json and the brand assets into web/dist, and removes any HTML under
web/dist that this build did not write, so a retired page cannot ship with a frozen build stamp.
Every figure carries the build's as-of time and the method note; a gapped cycle renders as a loud
row, not a missing one, and a cycle whose independent copy failed renders amber even though its own
pull succeeded. The committed dist/ is the publication of record, so every figure that was ever
public is in git history. The pages themselves are rendered by web/pages.py from the ledger this
module assembles.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brand  # noqa: E402
import pages  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SCHEMA = 2
COVERAGE_WINDOW_H = 24
HEARTBEAT_FRESH_S = 600          # D18: a minute is covered while a heartbeat is under ten minutes old
CADENCE_HOLD_H = 9.0             # a manifest held longer than this counts as a cadence hold
LOST_KM = pages.LOST_KM


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- reading the spool


def load_cycles(spool: Path) -> list[dict]:
    cycles = []
    for cdir in sorted(spool.glob("cycle_*")):
        rec_path = cdir / "cycle.json"
        if not rec_path.exists():
            continue
        rec = json.loads(rec_path.read_text())
        w_path = cdir / "witness.json"
        w = json.loads(w_path.read_text()) if w_path.exists() else {}
        wb = w.get("wayback") or {}
        samples = wb.get("samples") or {}
        man = wb.get("manifest") or {}
        ship_path = cdir / "ship.json"
        ship = json.loads(ship_path.read_text()) if ship_path.exists() else {}
        shipped = ship.get("shipped") or {}
        files_dir = cdir / "files"
        cycles.append({
            "cycle": rec["cycle"],
            "manifest_sha256": rec["manifest_sha256"],
            "first_seen_utc": rec.get("first_seen_utc"),
            "status": rec["status"],
            "files_listed": rec["files_listed"],
            "files_recorded": rec["files_recorded"],
            "files_failed": rec["files_failed"],
            "bytes_raw": rec.get("bytes_raw", 0),
            "wall_seconds": rec.get("wall_seconds"),
            "merkle_root": rec.get("merkle_root"),
            "ots": {"stamped": bool((w.get("ots") or {}).get("stamped_utc")),
                    "attested_block": ((w.get("ots") or {}).get("attested") or {}).get("block_height")},
            "wayback": {
                "attempted": bool(w),
                # A capture that exists but hashes to another cycle's manifest is not "missing": it is
                # Wayback de-duplicating an unchanged URL. The two states are different failures and
                # the page must not spell them the same way.
                "manifest_verified": bool(man.get("verified")),
                "manifest_captured": bool(man.get("timestamp")),
                "manifest_error": man.get("error"),
                "samples_verified": sum(1 for s in samples.values() if s.get("verified")),
                "samples_total": len(samples),
                "losses": sum(1 for s in samples.values() if s.get("gave_up")),
                "skipped": wb.get("skipped"),
                # what a reader needs to re-run the check themselves
                "manifest_copy_url": man.get("id_url"),
                "manifest_copy_sha256": man.get("sha256_of_copy"),
                "samples": [{"name": v.get("name"), "copy_url": v.get("id_url"),
                             "sha256_of_copy": v.get("sha256_of_copy"), "verified": bool(v.get("verified"))}
                            for _, v in sorted(samples.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0)],
            },
            "storage": {"bytes_stored": shipped.get("bytes") or 0,
                        "storage_class": shipped.get("storage_class"),
                        "local_files": files_dir.is_dir() and any(files_dir.iterdir()),
                        "deleted_locally_utc": ship.get("local_files_deleted_utc")},
        })
    cycles.sort(key=lambda c: c["first_seen_utc"] or "", reverse=True)
    return cycles


def load_dailies(spool: Path, cycles: list[dict]) -> list[dict]:
    """Each daily root with its leaf count and, computed rather than asserted, the cycles first seen
    that day which are under no daily root at all."""
    dailies = []
    for ddir in sorted(spool.glob("daily/*")):
        d_path = ddir / "daily.json"
        if not d_path.exists():
            continue
        d = json.loads(d_path.read_text())
        leaves = [c["cycle"] if isinstance(c, dict) else c for c in d["cycles"]]
        built = d.get("built_utc")
        excluded = []
        for c in cycles:
            if (c["first_seen_utc"] or "")[:10] != d["date"] or c["cycle"] in leaves:
                continue
            if not c["merkle_root"]:
                why = "incomplete pull, no root"
            elif built and c["first_seen_utc"] and parse_utc(c["first_seen_utc"]) < parse_utc(built):
                why = "still pulling when the root was built"
            else:
                why = "not under this root"
            excluded.append((c["cycle"], why))
        dailies.append({"date": d["date"], "merkle_root": d["merkle_root"], "built_utc": built,
                        "leaves": len(leaves), "excluded": excluded,
                        "attested_block": ((d.get("ots") or {}).get("attested") or {}).get("block_height")})
    dailies.sort(key=lambda d: d["date"], reverse=True)
    return dailies


def load_scores(spool: Path) -> list[dict]:
    """One entry per scored cycle, newest first: inputs, counts and the summary cuts the page shows."""
    out = []
    for rp in sorted((spool / "score").glob("visibility_*.json")):
        r = json.loads(rp.read_text(encoding="utf-8"))
        sha12 = rp.stem.removeprefix("visibility_")
        pack = spool / "score" / f"globe_{sha12}.json"
        s = r["summary"]
        out.append({"cycle": r["inputs"]["cycle"], "first_seen_utc": r["inputs"].get("first_seen_utc"),
                    "as_of": r["as_of"], "method": r["method"], "eval_step_min": r["eval_step_min"],
                    "snapshot": r["inputs"]["catalogue_snapshot"],
                    "snapshot_fetched_utc": r["inputs"]["catalogue_fetched_utc"],
                    "snapshot_relation": r["inputs"].get("snapshot_relation"),
                    "catalogue_sets": r["inputs"].get("catalogue_sets"),
                    "counts": r["counts"], "overall": s["overall"], "at_file_start": s.get("at_file_start"),
                    "catalogue_age": s.get("catalogue_age"), "by_age": s["by_age"], "by_shell": s.get("by_shell", []),
                    "pack": str(pack) if pack.exists() else None})
    out.sort(key=lambda x: x["first_seen_utc"] or "", reverse=True)
    return out


def load_catalogue(spool: Path) -> list[dict]:
    out = []
    for rp in sorted((spool / "gp").glob("*/record.json")):
        r = json.loads(rp.read_text(encoding="utf-8"))
        out.append({"fetched_utc": r["fetched_utc"], "records": r["records"], "sha12": r["sha256"][:12]})
    out.sort(key=lambda x: x["fetched_utc"], reverse=True)
    return out


def load_spool(spool: Path) -> dict:
    cycles = load_cycles(spool)
    ticks = []
    hb_hist = spool / "heartbeats.jsonl"
    if hb_hist.exists():
        for line in hb_hist.read_text(encoding="utf-8").splitlines():
            try:
                ticks.append(parse_utc(json.loads(line)["utc"]))
            except (ValueError, KeyError):
                continue
    return {"cycles": cycles, "dailies": load_dailies(spool, cycles), "ticks": ticks,
            "scores": load_scores(spool), "catalogue": load_catalogue(spool)}


def coverage_24h(ticks: list[datetime], now: datetime) -> float | None:
    """D18: the fraction of the window's minutes with at least one heartbeat under ten minutes
    old. None when the history is shorter than the window (published as 'not yet measured', not
    as a flattering partial figure)."""
    if not ticks or min(ticks) > now - timedelta(hours=COVERAGE_WINDOW_H):
        return None
    start = now - timedelta(hours=COVERAGE_WINDOW_H)
    recent = sorted(t for t in ticks if t >= start - timedelta(seconds=HEARTBEAT_FRESH_S))
    covered = 0
    minutes = int(COVERAGE_WINDOW_H * 60)
    j = 0
    for m in range(minutes):
        t = start + timedelta(minutes=m)
        while j < len(recent) and recent[j] <= t:
            j += 1
        last = recent[j - 1] if j > 0 else None
        if last is not None and (t - last).total_seconds() < HEARTBEAT_FRESH_S:
            covered += 1
    return covered / minutes


def cadence_holds(cycles: list[dict]) -> int:
    seen = sorted(parse_utc(c["first_seen_utc"]) for c in cycles if c["first_seen_utc"])
    return sum(1 for a, b in zip(seen, seen[1:]) if (b - a).total_seconds() > CADENCE_HOLD_H * 3600)


def witness_defect(c: dict) -> str | None:
    """What went wrong with the independent copy, or None. The pull itself can be perfect while
    this fails, so it is a separate state from a gap. Witnessing that has not run yet is not a
    defect: it follows the pull."""
    wb = c["wayback"]
    if not wb.get("attempted"):
        return None
    if wb["skipped"]:
        return "no independent copy was made"
    # verified implies captured, so ask that first: an older witness record may carry the verdict
    # without the capture timestamp, and that is not a missing capture.
    if not wb["manifest_verified"]:
        return ("the manifest was never captured" if not wb["manifest_captured"]
                else "the archived manifest copy is another cycle's file")
    if wb["losses"]:
        return f"{wb['losses']} of {wb['samples_total']} sample captures were lost"
    if wb["samples_total"] and wb["samples_verified"] < wb["samples_total"]:
        return f"only {wb['samples_verified']} of {wb['samples_total']} samples verified"
    return None


def build_ledger(spool: Path, now: datetime) -> dict:
    data = load_spool(spool)
    cycles = data["cycles"]
    complete = [c for c in cycles if c["merkle_root"]]
    stored = sum(c["storage"]["bytes_stored"] for c in cycles)
    local = sum(c["storage"]["bytes_stored"] for c in cycles if c["storage"]["local_files"])
    return {
        "schema": SCHEMA,
        "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "poller": "home (Cape Town, residential; single poller until poller A exists)",
        "method": "built from each cycle's cycle.json, witness.json and ship.json in the poller's "
                  "spool; coverage is the fraction of the last 24 h's minutes with a watcher "
                  "heartbeat under 10 minutes old (D18); a cadence hold is a manifest first-seen "
                  "gap over 9 h; source bytes are the responses as served, stored bytes are the "
                  "gzipped archive objects the shipper recorded",
        "totals": {
            "cycles": len(cycles),
            "complete": len(complete),
            "attested": sum(1 for c in complete if c["ots"]["attested_block"]),
            "witness_defects": sum(1 for c in cycles if witness_defect(c)),
            "bytes_raw": sum(c["bytes_raw"] for c in cycles),
            "bytes_stored": stored,
            "bytes_stored_local": local,
            "bytes_stored_cold_only": stored - local,
            "files": sum(c["files_recorded"] for c in cycles),
            "cadence_holds": cadence_holds(cycles),
        },
        "coverage_24h": coverage_24h(data["ticks"], now),
        "visibility": {"reports": data["scores"], "latest": data["scores"][0]["cycle"] if data["scores"] else None},
        "catalogue_snapshots": len(data["catalogue"]),
        "catalogue": data["catalogue"][:12],
        "cycles": cycles,
        "daily_roots": data["dailies"],
    }


# ---------------------------------------------------------------- rendering

# The page renderers live in web/pages.py; these names are re-exported because the tests and the
# publisher reach them through this module.
esc = pages.esc
headline_report = pages.headline_report
render_site = pages.render_site


def render(ledger: dict) -> str:
    """The front page alone, for callers that only want one page."""
    return pages.home(ledger, None)


def inject_globe_chrome(source: str, ledger: dict, pack_bytes: int | None) -> str:
    """The globe page keeps its own full-screen layout and borrows the masthead and tab bar through
    a marker comment, so the tab list has one source. The source file keeps working standalone
    because the marker is a comment."""
    block, status = pages.globe_chrome(ledger, pack_bytes)
    out = source.replace("<!-- ephemera:chrome -->", block, 1)
    # The source file's own link home is for the standalone page; with the tab bar present it
    # would print "front page" twice in the same small panel.
    out = out.replace(' <a href="../">front page</a>', "", 1)
    return out.replace("Loading the latest globe pack.", status, 1)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spool", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=REPO / "web" / "dist")
    args = ap.parse_args(argv)
    if not args.spool.is_dir():
        # A missing spool must not become an empty site. glob() over a path that is not there
        # returns nothing, and nothing renders as "the archive holds 0 cycles", which is a lie.
        print(f"build: spool {args.spool} is not a directory - refusing to build an empty site", file=sys.stderr)
        return 2
    ledger = build_ledger(args.spool, utc_now())
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "ledger.json").write_text(json.dumps(ledger, indent=1), encoding="utf-8")
    brand.write_all(args.out, "An archive of the public Starlink\nephemerides, kept and witnessed.",
                    "Hashed per cycle, anchored in Bitcoin, measured daily.")

    # The globe shows the cycle the page describes, not whichever pack is newest, or the text and
    # the picture are about different cycles. When there is nothing to publish the previous pack is
    # removed rather than left serving figures the page no longer stands behind.
    globe_out = args.out / "globe"
    globe_out.mkdir(exist_ok=True)
    head = headline_report(ledger["visibility"]["reports"])
    pack = head["pack"] if head else None
    published = globe_out / "pack.json"
    if pack:
        shutil.copyfile(pack, published)
    elif published.exists():
        published.unlink()
    pack_bytes = published.stat().st_size if published.exists() else None

    written = set()
    for rel, html_text in render_site(ledger, pack_bytes).items():
        target = args.out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_text, encoding="utf-8")
        written.add(target.resolve())
    globe_src = (REPO / "web" / "globe" / "index.html").read_text(encoding="utf-8")
    (globe_out / "index.html").write_text(inject_globe_chrome(globe_src, ledger, pack_bytes), encoding="utf-8")
    written.add((globe_out / "index.html").resolve())
    shutil.copyfile(args.out / "icon.svg", globe_out / "icon.svg")

    # Prune: any page this build did not write would otherwise ship forever with a frozen stamp.
    for stale in sorted(args.out.rglob("*.html")):
        if stale.resolve() not in written and not stale.name.startswith("probe"):
            stale.unlink()

    t = ledger["totals"]
    print(f"built: {t['cycles']} cycles ({t['complete']} complete, {t['attested']} attested, "
          f"{t['witness_defects']} witness defects), coverage={ledger['coverage_24h']}, "
          f"holds={t['cadence_holds']}, scored={len(ledger['visibility']['reports'])}, "
          f"pages={len(written)} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
