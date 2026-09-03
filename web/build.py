#!/usr/bin/env python3
"""Build the public site from the spool's records (D08: all computation at build time, the output
is static files; D18: the ledger is one record per poller per cycle, gaps and disagreement
published, never suppressed).

  python web/build.py --spool Z:/ephemera/spool

Writes web/dist/index.html, ledger.json, the brand assets, and the globe page with its pack. Every
number the page shows carries the build's as-of time and the method note; a gapped cycle renders as
a loud row, not a missing one, and a cycle whose independent copy failed renders amber even though
its own pull succeeded. The committed dist/ is the publication of record, so every figure that was
ever public is in git history.

The page leads with the finding and follows with the proof. Charts are inline SVG built from the
same ledger the tables use, so there is no second source of truth and no client-side rendering.
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

REPO = Path(__file__).resolve().parents[1]
SCHEMA = 2
COVERAGE_WINDOW_H = 24
HEARTBEAT_FRESH_S = 600          # D18: a minute is covered while a heartbeat is under ten minutes old
CADENCE_HOLD_H = 9.0             # a manifest held longer than this counts as a cadence hold
RECENT_CYCLES = 12               # the home page shows this many, plus every cycle with a defect
RECENT_SCORES = 8
LOST_KM = 1000
CONTACT_NAME = "Kira Ryan"
CONTACT_MAIL = "KiraRyan27@gmail.com"
CONTACT_LINKEDIN = "https://www.linkedin.com/in/kira-ryan/"


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


def esc(x) -> str:
    return html.escape(str(x))


def _utc_min(s: str | None) -> str:
    return (s or "?")[:16].replace("T", " ")


def pct(x: float) -> str:
    """A share as a percentage. Small shares keep a decimal: 41 of 11,090 is 0.4 percent, and
    printing that as 0% would say the opposite of what the number means."""
    v = 100 * x
    if 0 < v < 1:
        return f"{v:.1f}%"
    return f"{v:.0f}%"


def gb(n: int) -> str:
    return f"{n / 1e9:,.0f}"


CSS = """
  :root {
    --bg: #090c17; --surface: #111629; --surface-2: #171d33;
    --rule: #3d4a75; --rule-soft: #283152;
    --ink: #eceada; --ink-soft: #b9b7c6; --ink-faint: #8f8da0;
    --accent: #ffb347; --accent-lit: #ffcd80; --accent-rule: #9d7034;
    --held: #6fd39a; --warn: #ffb347; --bad: #ff7a7a;
    --km-1: #7fd4ff; --km-10: #ffe08a; --km-30: #ff8c42; --km-far: #ff4d5e;
    --serif: Georgia, 'Iowan Old Style', Charter, 'Palatino Linotype', 'Times New Roman', serif;
    --mono: ui-monospace, 'Cascadia Mono', 'SF Mono', Menlo, Consolas, 'DejaVu Sans Mono', monospace;
    --t-cap: .8125rem; --t-fine: .875rem; --t-lead: 1.25rem; --t-h2: 1.4rem;
    --s1: .25rem; --s2: .5rem; --s3: .75rem; --s4: 1rem; --s5: 1.5rem;
    --s6: 2rem; --s7: 3rem; --s8: 4rem;
    --measure: 60ch;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html { scroll-behavior: smooth; }
  body { background: var(--bg); color: var(--ink); font: 1rem/1.62 var(--serif);
         font-variant-numeric: tabular-nums lining-nums;
         padding: var(--s6) var(--s4) var(--s8); display: flex; justify-content: center;
         -webkit-text-size-adjust: 100%; }
  /* min-width 0 or the wide tables set this flex item's minimum and the whole page overflows */
  main { max-width: 60rem; width: 100%; min-width: 0; }
  p { margin-bottom: var(--s3); max-width: var(--measure); }
  a { color: var(--accent); text-decoration: underline; text-decoration-thickness: 1px;
      text-underline-offset: .18em; text-decoration-color: var(--accent-rule); }
  a:hover { color: var(--accent-lit); text-decoration-color: var(--accent-lit); }
  a:focus-visible, summary:focus-visible { outline: 2px solid var(--accent-lit); outline-offset: 3px; }
  b, strong { font-weight: 700; color: var(--ink); }

  .skip { position: absolute; left: -9999px; }
  .skip:focus { left: var(--s4); top: var(--s4); background: var(--surface-2); padding: var(--s3); z-index: 9; }

  .masthead { display: flex; align-items: center; gap: var(--s4); flex-wrap: wrap;
              border-bottom: 2px solid var(--rule); padding-bottom: var(--s4); margin-bottom: var(--s4); }
  .mark { flex: none; }
  .masthead h1 { font: 400 clamp(1.35rem, 4.4vw, 2rem)/1 var(--mono); letter-spacing: .26em;
                 margin-right: -.26em; color: var(--accent); text-transform: uppercase; }
  .masthead .where { margin-left: auto; flex: none; font: var(--t-cap)/1.4 var(--mono); letter-spacing: .12em;
                     color: var(--ink-faint); text-transform: uppercase; text-align: right; }
  nav { font: var(--t-cap)/1.9 var(--mono); color: var(--ink-faint); margin-bottom: var(--s6);
        text-transform: uppercase; letter-spacing: .08em; }
  nav a { text-decoration: none; }
  nav a:hover { text-decoration: underline; }
  nav span { opacity: .45; margin: 0 var(--s2); }

  .tag { font: var(--t-lead)/1.5 var(--serif); max-width: 46ch; margin-bottom: var(--s4); }
  .tag strong { color: var(--accent); }
  .dim { color: var(--ink-soft); font-size: var(--t-fine); }
  .fine { color: var(--ink-faint); font-size: var(--t-fine); line-height: 1.6; }

  .stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: 1px; background: var(--rule-soft);
           border: 1px solid var(--rule-soft); margin: var(--s5) 0 var(--s4); }
  @media (min-width: 46rem) { .stats { grid-template-columns: repeat(4, 1fr); } }
  .stat { background: var(--surface); padding: var(--s4); }
  .stat b { display: block; font: 400 clamp(1.6rem, 4vw, 2.3rem)/1 var(--mono);
            letter-spacing: -.02em; color: var(--ink); white-space: nowrap; }
  .stat .held { color: var(--held); }
  .stat span { display: block; margin-top: var(--s2); font: var(--t-cap)/1.35 var(--mono);
               text-transform: uppercase; letter-spacing: .06em; color: var(--ink-faint); }

  h2 { font: 400 var(--t-h2)/1.25 var(--mono); color: var(--ink); margin: var(--s8) 0 var(--s4);
       padding-bottom: var(--s3); border-bottom: 1px solid var(--rule);
       display: flex; align-items: baseline; gap: var(--s3); }
  h2::before { content: ""; flex: none; width: .5rem; height: .5rem; background: var(--accent);
               transform: translateY(-.1em); }
  h3 { font: 400 var(--t-cap)/1.4 var(--mono); text-transform: uppercase; letter-spacing: .1em;
       color: var(--ink-faint); margin: var(--s6) 0 var(--s3); }

  .lede { font: var(--t-lead)/1.5 var(--serif); max-width: 52ch; margin-bottom: var(--s4); }
  .lede b { color: var(--accent); }

  figure { margin: var(--s5) 0 var(--s4); }
  figure svg { display: block; width: 100%; height: auto; }
  figcaption { margin-top: var(--s3); color: var(--ink-faint); font-size: var(--t-fine);
               line-height: 1.6; max-width: var(--measure); }
  .strip .kept { fill: var(--held); } .strip .warn { fill: var(--warn); } .strip .miss { fill: var(--bad); }
  .strip .pending { fill: var(--ink-faint); }
  .strip text, .curve text { font: 11px var(--mono); fill: var(--ink-faint); }
  .curve .grid { stroke: var(--rule-soft); }
  .curve .line { fill: none; stroke: var(--accent); stroke-width: 2; }
  .curve .dot { fill: var(--accent); }
  .curve .val { fill: var(--ink); }

  .tablewrap { overflow-x: auto; min-width: 0; margin: var(--s4) 0 var(--s3); border: 1px solid var(--rule);
               background: var(--surface); scrollbar-color: var(--rule) transparent; scrollbar-width: thin; }
  table { border-collapse: collapse; width: 100%; min-width: 42rem;
          font: var(--t-cap)/1.45 var(--mono); font-variant-numeric: tabular-nums lining-nums; }
  caption { text-align: left; padding: var(--s3) var(--s4); color: var(--ink-faint);
            font: var(--t-cap)/1.5 var(--mono); border-bottom: 1px solid var(--rule); }
  th, td { padding: .42rem .7rem; border-bottom: 1px solid var(--rule-soft);
           vertical-align: baseline; white-space: nowrap; text-align: left; }
  thead th { background: var(--surface-2); color: var(--ink-faint); font-weight: 400;
             font-size: .75rem; text-transform: uppercase; letter-spacing: .05em;
             border-bottom: 1px solid var(--rule); position: sticky; top: 0; }
  td.wrap { white-space: normal; min-width: 18rem; }
  tbody tr:last-child td { border-bottom: 0; }
  tbody tr:hover td { background: var(--surface-2); }
  .num { text-align: right; }
  td.mono { color: var(--ink-soft); }
  tr.gap td { color: var(--bad); background: rgba(255,122,122,.07); font-weight: 700; }
  tr.warn td.state { color: var(--warn); }
  .held { color: var(--held); } .bad { color: var(--bad); } .warnk { color: var(--warn); }

  details { border: 1px solid var(--rule-soft); background: var(--surface); padding: var(--s3) var(--s4);
            margin: var(--s4) 0; }
  summary { cursor: pointer; font: var(--t-cap)/1.5 var(--mono); text-transform: uppercase;
            letter-spacing: .08em; color: var(--ink-faint); }
  details[open] summary { margin-bottom: var(--s3); }
  details p { font-size: var(--t-fine); color: var(--ink-soft); }
  code { font: .85em var(--mono); color: var(--accent-lit); word-break: break-all; }

  ul { margin: 0 0 var(--s3) 1.1rem; max-width: var(--measure); }
  li { margin-bottom: var(--s2); }

  footer { margin-top: var(--s8); padding-top: var(--s4); border-top: 1px solid var(--rule);
           color: var(--ink-faint); font: var(--t-fine)/1.65 var(--mono); }
  footer p { max-width: var(--measure); }

  @media print {
    body { background: #fff; color: #000; padding: 0; display: block; }
    :root { --ink: #000; --ink-soft: #333; --ink-faint: #444; --accent: #7a4a00;
            --surface: #fff; --surface-2: #f2f2f2; --rule: #999; --rule-soft: #ccc; }
    nav, .skip { display: none; }
    .tablewrap { overflow: visible; } table { min-width: 0; font-size: 9pt; }
    a { text-decoration: none; } h2 { break-after: avoid; }
  }
"""


def stat_band(ledger: dict) -> str:
    t = ledger["totals"]
    reports = ledger["visibility"]["reports"]
    head = headline_report(reports)
    start = head["at_file_start"] if head else None
    tiles = []
    if start:
        tiles.append((pct(start["within_km"]["10"]), "within 10 km at file start", False))
        tiles.append((f"{start['median_km']:.1f} km", "median miss at file start", False))
    tiles.append((f"{t['cycles']}", "cycles kept", False))
    tiles.append((f"{t['attested']} of {t['complete']}", "anchored in bitcoin", True))
    if not start:
        tiles.append((f"{gb(t['bytes_raw'])} GB", "source bytes archived", False))
    cells = "".join(f'<div class="stat"><b{" class=held" if held else ""}>{esc(v)}</b><span>{esc(lab)}</span></div>'
                    for v, lab, held in tiles[:4])
    return f'<div class="stats">{cells}</div>'


def cycle_strip(ledger: dict) -> str:
    """One block per cycle on a real time axis. The uneven spacing is the cadence, drawn rather
    than described, and a defective cycle is a different colour in the same row."""
    cycles = [c for c in ledger["cycles"] if c["first_seen_utc"]]
    if len(cycles) < 2:
        return ""
    times = sorted(parse_utc(c["first_seen_utc"]) for c in cycles)
    t0, t1 = times[0], times[-1]
    span = max((t1 - t0).total_seconds(), 1.0)
    W, H, top, bot = 1000.0, 74.0, 8.0, 26.0
    bars = []
    for c in cycles:
        x = 6 + (parse_utc(c["first_seen_utc"]) - t0).total_seconds() / span * (W - 18)
        if not c["merkle_root"]:
            cls = "miss"
        elif witness_defect(c):
            cls = "warn"
        elif not c["wayback"].get("attempted") or not c["wayback"]["samples_total"]:
            cls = "pending"      # complete, but the independent copy has not been made yet
        else:
            cls = "kept"
        title = (f"{c['cycle'][6:]} first seen {_utc_min(c['first_seen_utc'])} UTC, "
                 f"{c['files_recorded']:,} files" + (f", {witness_defect(c)}" if witness_defect(c) else ""))
        bars.append(f'<rect class="{cls}" x="{x:.1f}" y="{top}" width="7" height="{H - top - bot:.0f}" rx="1">'
                    f"<title>{esc(title)}</title></rect>")
    ticks = []
    day = t0.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= t1:
        if day >= t0:
            x = 6 + (day - t0).total_seconds() / span * (W - 18)
            ticks.append(f'<line class="grid" x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{H - bot + 4:.0f}" '
                         f'stroke="#283152"/><text x="{x:.1f}" y="{H - 8:.0f}" text-anchor="middle">'
                         f"{day:%d %b}</text>")
        day += timedelta(days=1)
    return (f'<figure class="strip"><svg viewBox="-6 0 {W + 12:.0f} {H:.0f}" role="img" '
            f'aria-label="Every archived cycle on a time axis, one block each, coloured by state.">'
            f'{"".join(ticks)}{"".join(bars)}</svg>'
            f'<figcaption>Every cycle kept, on a time axis. Green is complete and independently copied, '
            f'grey is complete with the copy still pending, amber is complete but the independent copy failed, '
            f'red is an incomplete pull. '
            f'Gaps in the spacing are the feed\'s own cadence. As of {esc(_utc_min(ledger["generated_utc"]))} UTC.'
            f"</figcaption></figure>")


def visibility_curve(report: dict) -> str:
    """Median separation against element age, log y. Built from the same by_age list as the table."""
    bins = [b for b in report["by_age"] if b["n"] >= 50]
    if len(bins) < 3:
        return ""
    W, H, L, R, T, B = 1000.0, 300.0, 54.0, 46.0, 18.0, 44.0   # R leaves room for the last x label
    lo, hi = 0.5, max(60.0, max(b["median_km"] for b in bins) * 1.3)

    def y(v: float) -> float:
        return T + (H - T - B) * (1 - (math.log10(max(v, lo)) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)))

    step = (W - L - R) / (len(bins) - 1)
    pts = [(L + i * step, y(b["median_km"])) for i, b in enumerate(bins)]
    grid = "".join(f'<line class="grid" x1="{L}" y1="{y(v):.1f}" x2="{W - R:.0f}" y2="{y(v):.1f}"/>'
                   f'<text x="{L - 8:.0f}" y="{y(v) + 4:.1f}" text-anchor="end">{v:g} km</text>'
                   for v in (1, 3, 10, 30))
    line = '<polyline class="line" points="' + " ".join(f"{x:.1f},{yy:.1f}" for x, yy in pts) + '"/>'
    dots = "".join(f'<circle class="dot" cx="{x:.1f}" cy="{yy:.1f}" r="4"/>'
                   f'<text class="val" x="{x:.1f}" y="{yy - 12:.1f}" text-anchor="middle">{b["median_km"]:.1f}</text>'
                   f'<text x="{x:.1f}" y="{H - 22:.0f}" text-anchor="middle">{esc(b["bin"])}</text>'
                   f'<text x="{x:.1f}" y="{H - 8:.0f}" text-anchor="middle" opacity=".7">{b["n"]:,}</text>'
                   for (x, yy), b in zip(pts, bins))
    return (f'<figure class="curve"><svg viewBox="0 0 {W:.0f} {H:.0f}" role="img" '
            f'aria-label="Median separation between the public and operator predictions, rising with element age.">'
            f'{grid}{line}{dots}</svg><figcaption>Median separation between the two predictions, by how old the '
            f"public catalogue's information was. Log scale; the second line under each point is how many "
            f'comparisons it holds. Cycle {esc(report["cycle"][6:])}, scored {esc(_utc_min(report["as_of"]))} UTC.'
            f"</figcaption></figure>")


def headline_report(reports: list[dict]) -> dict | None:
    """The newest report whose catalogue snapshot was fetched before the cycle, with rows scored.

    A cycle paired with a later snapshot is scored with hindsight: the element set already knows what
    the satellite did during the file. Those numbers are not comparable and must never become the
    headline, however recent the report is."""
    return next((r for r in reports
                 if r["snapshot_relation"] == "before_cycle" and r["at_file_start"]), None)


def render_visibility(ledger: dict) -> str:
    vis = ledger["visibility"]
    reports = vis["reports"]
    if not reports:
        return ('<h2 id="finding">What the public catalogue can see</h2>\n'
                '<p class="dim">No cycle has been scored yet. Scoring starts once the public catalogue feed has a '
                "snapshot to pair with an archived cycle.</p>")
    latest = headline_report(reports) or reports[0]
    c, o, start, cage = latest["counts"], latest["overall"], latest["at_file_start"], latest["catalogue_age"]
    far = next((b for b in latest["by_age"] if b["bin"] == "48-72 h"), None)

    hero = ""
    if start:
        hero = (f'<p class="lede">At the first instant of each operator file, the public catalogue puts '
                f'<b>{pct(start["within_km"]["10"])}</b> of the scored Starlink satellites within 10 km of where '
                f'the operator says they are. The middle satellite is <b>{start["median_km"]:.1f} km</b> away, with '
                f'the public information a median of {start["median_age_h"]:.0f} hours old'
                + (f". Where the public information is two to three days old, the two predictions are about "
                   f"<b>{far['median_km']:.0f} km</b> apart" if far else "")
                + ". Both sides are predictions, and most of that spread is planned trajectory changes the public "
                "catalogue cannot know about.</p>")

    lost_line = ""
    if start and start["lost"]:
        lost_line = (f'<p class="dim"><b class="warnk">{start["lost"]}</b> satellites '
                     f'({pct(start["lost_fraction"])}) are more than {LOST_KM:,} km from the public prediction at '
                     f"publication, which is a large part of an orbit. For those the public element set is not on the "
                     f"operator's trajectory at all. Ephemera does not label any separation as a manoeuvre; that needs "
                     f"a detector this project has not built.</p>")

    uncat = c.get("uncatalogued", 0)
    age_note = (f'Averaged over every comparison, which run out to three days into the operator file, element '
                f'age is {o["mean_age_h"]:.1f} h: the difference is the file\'s own prediction horizon, not '
                f"catalogue staleness. " if o else "No comparison was made for this cycle. ")
    health = (f'<p class="fine"><b>Feed health for this cycle.</b> '
              f'{c["scored"]:,} of {c["files"]:,} operator files scored. '
              f'{c["no_public_set"]:,} have no entry in the public catalogue'
              + (f", of which {uncat:,} are new satellites the catalogue has not numbered yet" if uncat else "")
              + f'; {c["decayed_set"]:,} marked decayed; {c["propagation_failed"]:,} failed to propagate; '
              f'{c["unreadable"]:,} unreadable. '
              + (f'Public element sets were a mean of <b>{cage["mean_h"]:.1f} h</b> old when the snapshot was taken '
                 f'(median {cage["median_h"]:.1f} h, 90th percentile {cage["p90_h"]:.1f} h, {cage["over_72h"]} over '
                 f"72 h). " if cage else "")
              + age_note
              + f"Space-Track: {ledger['catalogue_snapshots']} snapshots held, last fetched "
              f"{esc(_utc_min(ledger['catalogue'][0]['fetched_utc'])) if ledger['catalogue'] else 'none'} UTC"
              + (f" with {ledger['catalogue'][0]['records']:,} element sets" if ledger["catalogue"] else "")
              + f'. Poller heartbeat coverage over the last 24 h: '
              + (f"{100 * ledger['coverage_24h']:.1f}%" if ledger["coverage_24h"] is not None else "not yet measured")
              + ".</p>")

    age_rows = "".join(
        f'<tr><td>{esc(b["bin"])}</td><td class="num">{b["n"]:,}</td><td class="num">{b["median_km"]:.1f}</td>'
        f'<td class="num">{b["p90_km"]:.1f}</td><td class="num">{pct(b["within_km"]["10"])}</td>'
        f'<td class="num">{pct(b["within_km"]["30"])}</td></tr>' for b in latest["by_age"])

    shell_rows = "".join(
        f'<tr><td>{esc(b["bin"])}</td><td class="num">{b["n"]:,}</td><td class="num">{b["median_km"]:.1f}</td>'
        f'<td class="num">{pct(b["within_km"]["10"])}</td></tr>' for b in latest["by_shell"])
    shells = ("" if not shell_rows else
              f'<h3>By altitude shell</h3><div class="tablewrap"><table>'
              f'<caption>Same comparisons, split by where the satellite is. The lowest shell is where satellites are '
              f'being raised and lowered, so its spread is the widest.</caption>'
              f'<thead><tr><th scope="col">shell</th><th scope="col" class="num">comparisons</th>'
              f'<th scope="col" class="num">median km</th><th scope="col" class="num">within 10 km</th></tr></thead>'
              f"<tbody>{shell_rows}</tbody></table></div>")

    shown = reports[:RECENT_SCORES]
    cyc_rows = []
    for r in shown:
        ro, rs = r["overall"], r["at_file_start"]
        comparable = r["snapshot_relation"] == "before_cycle"
        rel = ("scored live" if comparable else
               ("scored with hindsight" if r["snapshot_relation"] == "after_cycle" else "pairing not recorded"))
        if ro is not None and rs is None:
            # A report written before the comparable headline existed. Say so rather than crashing
            # the build or, worse, printing the old incomparable figure as if it were the new one.
            cyc_rows.append(f'<tr class="warn"><td>{esc(_utc_min(r["first_seen_utc"]))}</td>'
                            f'<td class="mono">{esc(r["cycle"][6:])}</td>'
                            f'<td class="num">{r["counts"]["scored"]:,}</td>'
                            f'<td class="state" colspan="5">scored before the comparable headline existed; '
                            f"rerun score/resummarise.py to fill it in</td></tr>")
            continue
        if ro is None:
            cyc_rows.append(f'<tr class="gap"><td>{esc(_utc_min(r["first_seen_utc"]))}</td>'
                            f'<td class="mono">{esc(r["cycle"][6:])}</td>'
                            f'<td class="num">{r["counts"]["scored"]:,}</td>'
                            f'<td colspan="5">NOTHING SCORED: {r["counts"]["unreadable"]:,} unreadable</td></tr>')
            continue
        cyc_rows.append(
            f'<tr><td>{esc(_utc_min(r["first_seen_utc"]))}</td><td class="mono">{esc(r["cycle"][6:])}</td>'
            f'<td class="num">{r["counts"]["scored"]:,}</td>'
            f'<td class="{"" if comparable else "warnk"}">{esc(rel)}</td>'
            f'<td class="num">{rs["median_age_h"]:.1f}</td>'
            f'<td class="num">{rs["median_km"]:.1f}</td>'
            f'<td class="num">{pct(rs["within_km"]["10"])}</td>'
            f'<td class="num">{rs["lost"]:,}</td></tr>')
    hindsight = sum(1 for r in reports if r["snapshot_relation"] == "after_cycle")
    more = len(reports) - len(shown)

    globe = ('<a href="globe/">See it on the globe</a>: every satellite drawn twice, the operator trajectory and '
             "the public catalogue's ghost." if latest["pack"] else "")

    return f"""<h2 id="finding">What the public catalogue can see</h2>
  {hero}
  <p>Everyone outside SpaceX sees Starlink through the public catalogue of orbital elements. Ephemera takes
  that public element set for each satellite, propagates it with SGP4, and compares it against the operator's
  own published trajectory for the same satellite at the same instants. The distance between the two is what
  this section measures. It is not an error of the satellite, and it is not a statement about which side is
  right.</p>
  {lost_line}
  <p class="fine">Latest scored cycle <span class="mono">{esc(latest["cycle"][6:])}</span>, first seen
  {esc(_utc_min(latest["first_seen_utc"]))} UTC, scored {esc(_utc_min(latest["as_of"]))} UTC against the public
  catalogue snapshot fetched {esc(_utc_min(latest["snapshot_fetched_utc"]))} UTC
  ({esc(f"{latest['catalogue_sets']:,}") if latest["catalogue_sets"] else "?"} element sets). {globe}</p>
  {visibility_curve(latest)}
  <div class="tablewrap"><table>
    <caption>The same curve as numbers, for cycle {esc(latest["cycle"][6:])}.</caption>
    <thead><tr><th scope="col">element age</th><th scope="col" class="num">comparisons</th>
      <th scope="col" class="num">median km</th><th scope="col" class="num">90th pct km</th>
      <th scope="col" class="num">within 10 km</th><th scope="col" class="num">within 30 km</th></tr></thead>
    <tbody>{age_rows}</tbody>
  </table></div>
  <p class="fine">Element age is how old the public catalogue's information was at the instant compared. It runs
  larger than catalogue staleness because a single operator file predicts three days ahead, so a comparison late
  in the file is both further ahead and matched against an older element set. The two effects are not separated
  within one cycle, which is why the headline above uses only the first instant of each file.</p>
  {shells}
  {health}
  <h3>Every scored cycle</h3>
  <div class="tablewrap"><table>
    <caption>One row per cycle, measured at the first instant of each file so the rows are comparable.
    Newest first.</caption>
    <thead><tr><th scope="col">cycle first seen</th><th scope="col">cycle</th>
      <th scope="col" class="num">scored</th><th scope="col">pairing</th>
      <th scope="col" class="num">median age h</th><th scope="col" class="num">median km</th>
      <th scope="col" class="num">within 10 km</th><th scope="col" class="num">lost</th></tr></thead>
    <tbody>{"".join(cyc_rows)}</tbody>
  </table></div>
  <p class="fine">{"Showing the " + str(len(shown)) + " most recent of " + str(len(reports)) + " scored cycles; the rest are in ledger.json. " if more else ""}
  A cycle marked <b class="warnk">scored with hindsight</b> was matched against a catalogue snapshot fetched
  after it, because the cycle predates this project's catalogue feed. Its element sets already know what the
  satellite did during the file, so its numbers look better than they should and are not comparable with the
  rest. {hindsight} of {len(reports)} scored cycles are in that state, and the count only falls from here.</p>
  <details><summary>How this was measured</summary>
    <p>{esc(latest["method"])}</p>
    <p>Snapshot <span class="mono">{esc(latest["snapshot"])}</span>. Evaluation every
    {latest["eval_step_min"]:g} minutes across each file's own record epochs. Public element sets come from
    Space-Track.org and are redistributed under Space-Track's blanket approval for basic space situational
    awareness data, with citation.</p>
  </details>"""


def daily_note(d: dict) -> str:
    """Why a cycle first seen that day sits under no daily root. The reason is derived from the
    cycle's own state, because a root built at midnight excludes an unfinished pull and a gapped
    pull for different reasons and the page must not spell them the same way."""
    if not d["excluded"]:
        return "none"
    parts = []
    for name, reason in d["excluded"]:
        parts.append(f"{esc(name[6:])} ({esc(reason)})")
    return "excluded " + ", ".join(parts)


def render_archive(ledger: dict) -> str:
    t = ledger["totals"]
    cov = (f"{100 * ledger['coverage_24h']:.1f}%" if ledger["coverage_24h"] is not None
           else "not yet measured, the heartbeat history is shorter than 24 hours")
    cycles = ledger["cycles"]
    keep = {c["cycle"] for c in cycles[:RECENT_CYCLES]}
    keep |= {c["cycle"] for c in cycles if not c["merkle_root"] or witness_defect(c)}
    shown = [c for c in cycles if c["cycle"] in keep]
    rows = []
    for c in shown:
        in_progress = c["status"] == "in-progress"
        gap = c["merkle_root"] is None and not in_progress
        defect = witness_defect(c)
        wb = c["wayback"]
        if not wb.get("attempted"):
            state = "follows the pull" if in_progress else "pending"
        elif wb["skipped"]:
            state = f"no independent copy: {esc(wb['skipped'])}"
        elif not wb["manifest_verified"]:
            state = ((f"manifest NEVER CAPTURED" if not wb["manifest_captured"]
                      else "manifest COPY DOES NOT MATCH (the archived copy is another cycle's manifest)")
                     + f", {wb['samples_verified']}/{wb['samples_total']} samples verified")
            if wb["losses"]:
                state += f", {wb['losses']} lost"
        elif wb["samples_total"]:
            state = f"manifest ok, {wb['samples_verified']}/{wb['samples_total']} samples verified"
            if wb["losses"]:
                state += f", {wb['losses']} lost"
        else:
            state = "pending"
        ots = (f"block {c['ots']['attested_block']}" if c["ots"]["attested_block"] else
               ("stamped, attestation pending" if c["ots"]["stamped"] else
                ("follows the pull" if in_progress else "pending")))
        if in_progress:
            files = f"pulling now: {c['files_recorded']:,} of {c['files_listed']:,} so far"
        elif gap:
            files = f"INCOMPLETE: {c['files_failed']:,} of {c['files_listed']:,} missing, recorded"
        else:
            files = f"{c['files_recorded']:,}"
        where = ("spool and cold storage" if c["storage"]["local_files"] and c["storage"]["bytes_stored"]
                 else ("cold storage only" if c["storage"]["bytes_stored"] else "spool only"))
        cls = "gap" if gap else ("warn" if defect else "")
        rows.append(
            f'<tr class="{cls}"><td>{esc(_utc_min(c["first_seen_utc"]))}</td>'
            f'<td class="mono">{esc(c["cycle"][6:])}</td><td class="num">{files}</td>'
            f'<td class="num">{c["bytes_raw"] / 1e9:.1f}</td>'
            f'<td class="mono">{esc((c["merkle_root"] or "none")[:12])}</td>'
            f'<td>{esc(ots)}</td><td class="state wrap">{state}</td><td>{esc(where)}</td></tr>')

    droots = "".join(
        f'<tr><td>{esc(d["date"])}</td><td class="mono">{esc(d["merkle_root"][:12])}</td>'
        f'<td class="num">{d["leaves"]}</td>'
        f'<td>{("block " + str(d["attested_block"])) if d["attested_block"] else "stamp pending"}</td>'
        f'<td class="wrap">{daily_note(d)}</td></tr>' 
        for d in ledger["daily_roots"])

    hidden = len(cycles) - len(shown)
    return f"""<h2 id="archive">The archive behind it</h2>
  <p>The operator side of every comparison above comes from files this project caught before they were
  replaced. Each cycle is hashed file by file into one Merkle root, the root is stamped into the Bitcoin
  blockchain through OpenTimestamps, and the manifest plus ten files chosen by the root itself are pushed
  into the Wayback Machine so an independent copy exists that this project does not control.</p>
  <p class="fine">As of <b>{esc(_utc_min(ledger["generated_utc"]))} UTC</b>: <b>{t["cycles"]}</b> cycles,
  <b>{t["complete"]}</b> complete with roots, <b>{t["attested"]}</b> anchored in Bitcoin,
  <b>{t["witness_defects"]}</b> with a defect in the independent copy. Source bytes archived:
  <b>{gb(t["bytes_raw"])} GB</b> across {t["files"]:,} files as served. Stored gzipped as
  <b>{gb(t["bytes_stored"])} GB</b>, of which {gb(t["bytes_stored_local"])} GB is on the poller's disk and
  {gb(t["bytes_stored_cold_only"])} GB exists only in cold object storage. Cadence holds, meaning a set served
  longer than nine hours: <b>{t["cadence_holds"]}</b>. Poller heartbeat coverage over the last 24 hours:
  <b>{cov}</b>. This project exists because SpaceX publishes the feed openly.</p>
  {cycle_strip(ledger)}
  <div class="tablewrap"><table>
    <caption>The most recent {len(shown)} cycles{f", plus every older cycle with a defect" if hidden else ""}.
    Amber marks a cycle whose own pull succeeded but whose independent copy did not.</caption>
    <thead><tr><th scope="col">first seen (utc)</th><th scope="col">cycle</th>
      <th scope="col" class="num">files</th><th scope="col" class="num">source gb</th>
      <th scope="col">merkle root</th><th scope="col">opentimestamps</th>
      <th scope="col">wayback machine</th><th scope="col">held</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table></div>
  <p class="fine">{f"{hidden} older cycles are not shown here and are all in ledger.json. " if hidden else ""}
  Method: {esc(ledger["method"])}. Poller: {esc(ledger["poller"])}.</p>
  <h3>Daily roots</h3>
  <div class="tablewrap"><table>
    <caption>A root over each day's complete cycle roots, built shortly after midnight UTC and stamped
    separately.</caption>
    <thead><tr><th scope="col">date</th><th scope="col">root</th><th scope="col" class="num">leaves</th>
      <th scope="col">opentimestamps</th><th scope="col">note</th></tr></thead>
    <tbody>{droots or '<tr><td colspan="5">the first daily root arrives after the first full UTC day</td></tr>'}</tbody>
  </table></div>
  <p class="fine">A cycle still pulling at midnight is left out of that day's root and stays out. It keeps its
  own cycle root and its own OpenTimestamps proof, so nothing is unwitnessed, but it sits under no daily
  root.</p>"""


def render_verify(ledger: dict) -> str:
    latest = next((c for c in ledger["cycles"]
                   if c["merkle_root"] and c["ots"]["attested_block"] and c["wayback"]["manifest_copy_url"]), None)
    if latest is None:
        return ("""<h2 id="check">Check it yourself</h2>
  <p>No cycle yet has both a Bitcoin attestation and an independent copy, so there is nothing here a
  stranger could run today. This section fills in as soon as one does.</p>""")
    wb = latest["wayback"]
    return f"""<h2 id="check">Check it yourself</h2>
  <p>None of this is worth anything if you have to take my word for it. Here is what you can run right now,
  and what still needs data this site does not publish yet. I would rather say which is which.</p>
  <p><b>Fetch an independent copy and hash it.</b> Each cycle's file list is pushed into the Wayback Machine
  the moment it is caught, so a copy exists that I do not control. For cycle
  <span class="mono">{esc(latest["cycle"][6:])}</span> that copy is
  <a href="{esc(wb["manifest_copy_url"])}">here</a>, and its SHA-256 is
  <code>{esc(wb["manifest_copy_sha256"] or "")}</code>. Download it, hash it, and you have checked that the
  list of files I claim to have caught is the list the source was actually serving. Ten files from each
  cycle are copied the same way, and every copy URL and digest is in
  <a href="ledger.json">ledger.json</a>.</p>
  <p><b>Check which ten files were copied.</b> I do not get to choose them. File number
  <code>int(sha256(root + ":" + k), 16) mod n</code> for k from 0 to 9, where n is the number of files in
  the list you just downloaded. Run that and you get the same ten names this site published.</p>
  <p><b>Check the timestamp.</b> Each cycle root is stamped through OpenTimestamps. Running
  <code>ots verify root.txt.ots</code> against a Bitcoin node shows this cycle's root committed in block
  {esc(latest["ots"]["attested_block"])}, which fixes the latest moment it could have been written. Nobody,
  including me, can move a root backwards once it is in a block. The proof files ship with the data
  release.</p>
  <p class="fine">What you cannot do from this page alone is rebuild the Merkle root, because that needs the
  SHA-256 of every one of the {latest["files_recorded"]:,} files in the cycle and this site publishes the
  summary rather than the full digest list. Those digests, and the exact byte format of the root file, come
  with the data release described below. The construction is the plain one: leaves are the file digests in
  manifest order, adjacent pairs are hashed as SHA-256 of the two digests joined end to end, and an odd
  trailing node is paired with a copy of itself.</p>"""


def render_data(ledger: dict) -> str:
    gen = _utc_min(ledger["generated_utc"])
    return f"""<h2 id="data">Data, licence and citation</h2>
  <ul>
    <li><a href="ledger.json">ledger.json</a> carries every cycle, its root, its attestation, its witness
    state and every scored summary on this page, as machine-readable JSON. It is the same file the page is
    built from.</li>
    <li>The globe's per-cycle pack, with the element sets and the scored separations, is at
    <a href="globe/pack.json">globe/pack.json</a> for the newest scored cycle.</li>
    <li>The full per-comparison rows, about 140,000 per cycle, are kept in the archive and are available on
    request. They move to public object storage once the storage layer is finished.</li>
    <li>The raw operator files are held as published, hashed and witnessed. They are not re-published here
    while the licence question below is open.</li>
  </ul>
  <p class="fine"><b>Licence.</b> Code is MIT. Figures derived by this project are intended for CC BY 4.0.
  The raw SpaceX files carry no stated licence; a written request went to SpaceX on 31 August 2026 and is
  unanswered as of this build, and any file comes down on request. Public element sets come from
  Space-Track.org and are redistributed under Space-Track's blanket approval for basic space situational
  awareness data, with citation.</p>
  <p class="fine"><b>Citation.</b> Ryan, K. (2026). <i>Ephemera: an archive of the public Starlink
  ephemerides and a daily measure of public catalogue visibility.</i> https://ephemera.space, retrieved
  {esc(gen)} UTC.</p>"""


def render_next(ledger: dict) -> str:
    seen = sorted(c["first_seen_utc"] for c in ledger["cycles"] if c["first_seen_utc"])
    if seen:
        days = (parse_utc(seen[-1]) - parse_utc(seen[0])).total_seconds() / 86400
        span = "Less than a day" if days < 1 else f"{days:.0f} days"
    else:
        span = "An empty archive"
    return f"""<h2 id="next">Not here yet</h2>
  <p>{span} of archive is not a long record, and this page should not pretend otherwise. What is running:
  the poller, the hashing, the witnessing, cold storage, and the catalogue comparison above. What is not:</p>
  <ul>
    <li>A second poller on a different machine in a different country, so that a gap in one is visible in the
    other rather than invisible in both.</li>
    <li>The self-consistency scoreboard, which compares an earlier operator prediction with a later one from
    the same operator, normalised by the earlier uncertainty.</li>
    <li>The manoeuvre census, which will publish three differently defined counts side by side and never a
    ratio against anyone's declared figure.</li>
    <li>Other constellations, which reach this project through CelesTrak SupGP without covariance.</li>
    <li>A restore drill from cold storage, proving a cycle can be pulled back and re-verified end to end.</li>
  </ul>"""


def render_contact() -> str:
    return f"""<h2 id="who">Who runs this</h2>
  <p>{esc(CONTACT_NAME)}, on my own time, on a home computer in Cape Town, with no funding and no
  affiliation to any operator or agency. If a figure here is wrong I want to know, and corrections get
  published rather than quietly fixed.</p>
  <p class="fine"><a href="mailto:{esc(CONTACT_MAIL)}">{esc(CONTACT_MAIL)}</a> &nbsp;
  <a href="{esc(CONTACT_LINKEDIN)}">linkedin.com/in/kira-ryan</a></p>"""


def render(ledger: dict) -> str:
    gen = _utc_min(ledger["generated_utc"])
    reports = ledger["visibility"]["reports"]
    start = reports[0]["at_file_start"] if reports and reports[0]["at_file_start"] else None
    desc = ("An archive of the public Starlink ephemerides, hashed and anchored in Bitcoin, with a daily "
            "measure of how well the public satellite catalogue can see the constellation.")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ephemera</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="https://ephemera.space/">
<link rel="icon" href="icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="icon-180.png">
<meta name="theme-color" content="#090c17">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Ephemera">
<meta property="og:title" content="Ephemera">
<meta property="og:url" content="https://ephemera.space/">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:image" content="https://ephemera.space/social.png">
<meta name="twitter:card" content="summary_large_image">
<style>{CSS}</style>
</head>
<body>
<a class="skip" href="#finding">Skip to the finding</a>
<main>
  <div class="masthead">
    {brand.inline_mark(44)}
    <h1>Ephemera</h1>
    <span class="where">ephemera.space<br>built {esc(gen)} UTC</span>
  </div>
  <nav><a href="#finding">The finding</a><span>/</span><a href="#archive">The archive</a><span>/</span><a
    href="globe/">The globe</a><span>/</span><a href="#check">Check it</a><span>/</span><a
    href="#data">Data</a><span>/</span><a href="#next">Not here yet</a><span>/</span><a
    href="#who">Who runs this</a></nav>

  <p class="tag">Every eight hours, SpaceX publishes where each of about eleven thousand Starlink satellites
  will be for the next three days, and how sure it is. Eight hours later that set is gone, replaced by the
  next one. <strong>Ephemera keeps them, and measures what the public catalogue can see.</strong></p>
  <p class="dim">The files carry a full position and velocity uncertainty every sixty seconds, read from the
  feed on 30 August 2026. Starlink is the only operator with public covariance; other operators enter via
  CelesTrak SupGP without covariance.</p>

  {stat_band(ledger)}
  <p class="fine">{"Headline figures from cycle " + esc(reports[0]["cycle"][6:]) + ", scored " + esc(_utc_min(reports[0]["as_of"])) + " UTC, measured at the first instant of each operator file. " if start else ""}Archive figures as of {esc(gen)} UTC.</p>

  {render_visibility(ledger)}

  {render_archive(ledger)}

  {render_verify(ledger)}

  {render_data(ledger)}

  {render_next(ledger)}

  {render_contact()}

  <footer>
    <p>Operator ephemerides are predictions, not observations. Public GP data is too noisy to test
    sub-metre covariance; the self-consistency scoreboard measures prediction-versus-later-prediction.
    That scoreboard is not built yet. Inputs are archived by this project and witnessed by OpenTimestamps
    and the Wayback Machine; they are not re-fetchable from the source after one cycle. Every figure above
    carries the build time it was true at. Gapped or lost items are printed, never hidden.</p>
  </footer>
</main>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spool", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=REPO / "web" / "dist")
    args = ap.parse_args(argv)
    ledger = build_ledger(args.spool, utc_now())
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "ledger.json").write_text(json.dumps(ledger, indent=1), encoding="utf-8")
    (args.out / "index.html").write_text(render(ledger), encoding="utf-8")
    brand.write_all(args.out, "An archive of the public Starlink\nephemerides, kept and witnessed.",
                    "Hashed per cycle, anchored in Bitcoin, measured daily.")
    globe_out = args.out / "globe"
    globe_out.mkdir(exist_ok=True)
    shutil.copyfile(REPO / "web" / "globe" / "index.html", globe_out / "index.html")
    shutil.copyfile(args.out / "icon.svg", globe_out / "icon.svg")
    latest_pack = next((r["pack"] for r in ledger["visibility"]["reports"] if r["pack"]), None)
    if latest_pack:
        shutil.copyfile(latest_pack, globe_out / "pack.json")
    t = ledger["totals"]
    print(f"built: {t['cycles']} cycles ({t['complete']} complete, {t['attested']} attested, "
          f"{t['witness_defects']} witness defects), coverage={ledger['coverage_24h']}, "
          f"holds={t['cadence_holds']}, scored={len(ledger['visibility']['reports'])} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
