#!/usr/bin/env python3
"""Build the public site from the spool's records (D08: all computation at build time, the output
is static files; D18: the ledger is one record per poller per cycle, gaps and disagreement
published, never suppressed).

  python web/build.py --spool Z:/ephemera/spool

Writes web/dist/index.html and web/dist/ledger.json. Every number the page shows carries the
build's as-of time and the method note; a gapped cycle renders as a loud row, not a missing one.
The committed dist/ is the publication of record - the publish task commits each build, so every
figure that was ever public is in git history.
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCHEMA = 1
COVERAGE_WINDOW_H = 24
HEARTBEAT_FRESH_S = 600          # D18: a minute is covered while a heartbeat is under ten minutes old
CADENCE_HOLD_H = 9.0             # a manifest held longer than this counts as a cadence hold


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def load_spool(spool: Path) -> dict:
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
                "manifest_verified": bool((wb.get("manifest") or {}).get("verified")),
                "samples_verified": sum(1 for s in samples.values() if s.get("verified")),
                "samples_total": len(samples),
                "losses": sum(1 for s in samples.values() if s.get("gave_up")),
                "skipped": wb.get("skipped"),
            },
        })
    cycles.sort(key=lambda c: c["first_seen_utc"] or "", reverse=True)

    dailies = []
    for ddir in sorted(spool.glob("daily/*")):
        d_path = ddir / "daily.json"
        if d_path.exists():
            d = json.loads(d_path.read_text())
            dailies.append({"date": d["date"], "merkle_root": d["merkle_root"],
                            "cycles": len(d["cycles"]), "gapped_excluded": d.get("gapped_cycles_excluded", 0),
                            "attested_block": ((d.get("ots") or {}).get("attested") or {}).get("block_height")})
    dailies.sort(key=lambda d: d["date"], reverse=True)

    ticks = []
    hb_hist = spool / "heartbeats.jsonl"
    if hb_hist.exists():
        for line in hb_hist.read_text(encoding="utf-8").splitlines():
            try:
                ticks.append(parse_utc(json.loads(line)["utc"]))
            except (ValueError, KeyError):
                continue
    return {"cycles": cycles, "dailies": dailies, "ticks": ticks, "scores": load_scores(spool)}


def load_scores(spool: Path) -> list[dict]:
    """One entry per scored cycle from <spool>/score/visibility_<sha12>.json, newest first. Only
    what the page shows is carried: the inputs, the counts, the overall and per-age-bin figures,
    and whether a globe pack exists for the cycle."""
    out = []
    for rp in sorted((spool / "score").glob("visibility_*.json")):
        r = json.loads(rp.read_text(encoding="utf-8"))
        sha12 = rp.stem.removeprefix("visibility_")
        pack = spool / "score" / f"globe_{sha12}.json"
        out.append({"cycle": r["inputs"]["cycle"], "first_seen_utc": r["inputs"].get("first_seen_utc"),
                    "as_of": r["as_of"], "method": r["method"], "eval_step_min": r["eval_step_min"],
                    "snapshot": r["inputs"]["catalogue_snapshot"],
                    "snapshot_fetched_utc": r["inputs"]["catalogue_fetched_utc"],
                    "snapshot_relation": r["inputs"].get("snapshot_relation"),
                    "catalogue_sets": r["inputs"].get("catalogue_sets"),
                    "counts": r["counts"], "overall": r["summary"]["overall"], "by_age": r["summary"]["by_age"],
                    "pack": str(pack) if pack.exists() else None})
    out.sort(key=lambda x: x["first_seen_utc"] or "", reverse=True)
    return out


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


def build_ledger(spool: Path, now: datetime) -> dict:
    data = load_spool(spool)
    complete = [c for c in data["cycles"] if c["merkle_root"]]
    return {
        "schema": SCHEMA,
        "generated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "poller": "home (Cape Town, residential; single poller until poller A exists)",
        "method": "built from each cycle's cycle.json and witness.json in the poller's spool; "
                  "coverage is the fraction of the last 24 h's minutes with a watcher heartbeat "
                  "under 10 minutes old (D18); a cadence hold is a manifest first-seen gap over 9 h",
        "totals": {
            "cycles": len(data["cycles"]),
            "complete": len(complete),
            "attested": sum(1 for c in complete if c["ots"]["attested_block"]),
            "bytes_raw": sum(c["bytes_raw"] for c in data["cycles"]),
            "cadence_holds": cadence_holds(data["cycles"]),
        },
        "coverage_24h": coverage_24h(data["ticks"], now),
        "visibility": {"reports": data["scores"], "latest": data["scores"][0]["cycle"] if data["scores"] else None},
        "cycles": data["cycles"],
        "daily_roots": data["dailies"],
    }


def esc(x) -> str:
    return html.escape(str(x))


def _utc_min(s: str | None) -> str:
    return (s or "?")[:16].replace("T", " ")


def render_visibility(vis: dict) -> str:
    """The catalogue-visibility section: the latest scored cycle by element-age bin, then one row
    per scored cycle. Every figure sits next to its as-of time, its inputs and the method; the
    caveat that both sides are predictions is on the same screen as the numbers."""
    reports = vis["reports"]
    if not reports:
        return ('<h2>Catalogue visibility</h2>\n  <p class="dim">No cycle has been scored yet. Scoring starts once '
                'the public-catalogue feed has a snapshot to pair with an archived cycle.</p>')
    latest = reports[0]

    def pct(x: float) -> str:
        return f"{100 * x:.0f}%"

    age_rows = "".join(
        f'<tr><td>{esc(b["bin"])}</td><td>{b["n"]:,}</td><td>{b["median_km"]:.1f}</td><td>{b["p90_km"]:.1f}</td>'
        f'<td>{pct(b["within_km"]["10"])}</td><td>{pct(b["within_km"]["30"])}</td></tr>' for b in latest["by_age"])
    cyc_rows = []
    for r in reports:
        o, c = r["overall"], r["counts"]
        if r["snapshot_relation"] == "before_cycle":
            rel = "fetched before the cycle"
        elif r["snapshot_relation"] == "after_cycle":
            rel = "fetched after the cycle (the cycle predates the catalogue feed)"
        else:
            rel = "pairing not recorded"
        fresh = next((b for b in r["by_age"] if b["bin"] == "0-6 h"), None)
        fresh_cell = f"{fresh['median_km']:.1f}" if fresh else "none in bin"
        if o is None:
            cyc_rows.append(f'<tr class="gap"><td>{esc(_utc_min(r["first_seen_utc"]))}</td><td class="mono">{esc(r["cycle"][6:])}</td>'
                            f'<td>{c["scored"]:,} / {c["files"]:,}</td><td colspan="5"><b>NOTHING SCORED: '
                            f'{c["unreadable"]:,} unreadable, {c["no_public_set"]:,} without a public set</b></td>'
                            f'<td>{esc(_utc_min(r["as_of"]))}</td></tr>')
            continue
        cyc_rows.append(
            f'<tr><td>{esc(_utc_min(r["first_seen_utc"]))}</td><td class="mono">{esc(r["cycle"][6:])}</td>'
            f'<td>{c["scored"]:,} / {c["files"]:,}</td>'
            f'<td>{esc(_utc_min(r["snapshot_fetched_utc"]))}, {esc(rel)}</td>'
            f'<td>{fresh_cell}</td><td>{o["median_km"]:.1f}</td><td>{pct(o["within_km"]["10"])}</td>'
            f'<td>{pct(o["within_km"]["30"])}</td><td>{esc(_utc_min(r["as_of"]))}</td></tr>')
    o, c = latest["overall"], latest["counts"]
    globe = ('<a href="globe/" style="color:var(--accent)">See it on the globe</a>: every satellite drawn twice, '
             "the operator trajectory and the public catalogue's ghost." if latest["pack"] else "")
    mean_age = f'{o["mean_age_h"]:.1f} h' if o else "no comparisons"
    return f"""<h2>Catalogue visibility</h2>
  <p>How far the public catalogue's prediction sits from the operator's, for every satellite in a
  cycle. The public element set (Space-Track) is propagated with SGP4 to the operator file's own
  epochs, every {latest["eval_step_min"]:g} minutes across the file's span, and the distance is
  taken. <b>Both are predictions.</b> The operator's file includes planned trajectory changes the
  public set cannot know about, so a large distance is that gap, not an error of the satellite.
  Public GP data is too noisy to test sub-metre covariance; the self-consistency scoreboard, when it
  exists, measures prediction-versus-later-prediction.</p>
  <p>Latest scored cycle <span class="mono">{esc(latest["cycle"][6:])}</span> (first seen
  {esc(_utc_min(latest["first_seen_utc"]))} UTC): <b>{c["scored"]:,}</b> of {c["files"]:,} files scored
  against the snapshot fetched {esc(_utc_min(latest["snapshot_fetched_utc"]))} UTC
  ({esc(latest["catalogue_sets"] if latest["catalogue_sets"] is not None else "?")} element sets);
  {c["no_public_set"]:,} without a public set, {c["decayed_set"]:,} marked decayed,
  {c["propagation_failed"]:,} propagation failures, {c["unreadable"]:,} unreadable.
  Mean element age across the comparison: <b>{mean_age}</b>. Scored {esc(_utc_min(latest["as_of"]))} UTC.
  {globe}</p>
  <div class="tablewrap"><table>
    <tr><th>element age</th><th>comparisons</th><th>median km</th><th>90th pct km</th><th>within 10 km</th><th>within 30 km</th></tr>
    {age_rows}
  </table></div>
  <p class="dim">Element age is the evaluation epoch minus the public element set's epoch; a negative
  age means the set was published after that point of the file. Age and time-into-file are correlated
  within one cycle, so these bins are not yet a clean age effect.</p>
  <div class="tablewrap"><table>
    <tr><th>cycle first seen</th><th>cycle</th><th>scored</th><th>public snapshot</th><th>median km, age 0-6 h</th>
        <th>median km, all</th><th>within 10 km</th><th>within 30 km</th><th>scored at (utc)</th></tr>
    {"".join(cyc_rows)}
  </table></div>
  <p class="dim">Method: {esc(latest["method"])}</p>"""


def render(ledger: dict) -> str:
    rows = []
    for c in ledger["cycles"]:
        in_progress = c["status"] == "in-progress"
        gap = c["merkle_root"] is None and not in_progress
        wb = c["wayback"]
        if wb["skipped"]:
            wb_cell = f"lost: {esc(wb['skipped'])}"
        elif wb["samples_total"]:
            wb_cell = f"manifest {'ok' if wb['manifest_verified'] else 'MISSING'}, {wb['samples_verified']}/{wb['samples_total']} samples verified"
            if wb["losses"]:
                wb_cell += f", {wb['losses']} lost"
        else:
            wb_cell = "pending"
        ots = f"block {c['ots']['attested_block']}" if c["ots"]["attested_block"] else (
            "stamped, attestation pending" if c["ots"]["stamped"] else
            ("follows the pull" if in_progress else "pending"))
        if in_progress:
            status_cell = f"pulling now: {c['files_recorded']:,} of {c['files_listed']:,} so far"
        elif gap:
            status_cell = f"<b>INCOMPLETE: {c['files_failed']:,} of {c['files_listed']:,} missing, recorded</b>"
        else:
            status_cell = f"{c['files_recorded']:,} / {c['files_listed']:,}"
        rows.append(
            f'<tr class="{"gap" if gap else "ok"}"><td>{esc((c["first_seen_utc"] or "?")[:16].replace("T", " "))}</td>'
            f'<td class="mono">{esc(c["cycle"][6:])}</td><td>{status_cell}</td>'
            f'<td>{c["bytes_raw"] / 1e9:.1f}</td>'
            f'<td class="mono">{esc((c["merkle_root"] or "none")[:12])}</td>'
            f'<td>{esc(ots)}</td><td>{wb_cell}</td></tr>')

    droots = " &nbsp; ".join(f'{esc(d["date"])}: <span class="mono">{esc(d["merkle_root"][:12])}</span>'
                        f'{" (block " + str(d["attested_block"]) + ")" if d["attested_block"] else " (stamp pending)"}'
                        for d in ledger["daily_roots"]) or "first daily root arrives after the first full UTC day"
    cov = ledger["coverage_24h"]
    cov_txt = f"{100 * cov:.1f}% of the last 24 hours" if cov is not None else \
        "not yet measured (heartbeat history shorter than 24 h)"
    t = ledger["totals"]
    gen = ledger["generated_utc"][:16].replace("T", " ")
    vis = render_visibility(ledger["visibility"])

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ephemera</title>
<meta name="description" content="An archive of the public Starlink ephemerides. Each eight-hour set is replaced by the next. Ephemera keeps the history.">
<style>
  :root {{ --bg: #0c0f1d; --ink: #e8e6df; --dim: #9a97a8; --accent: #ffb347; --line: #2a1f5e; --bad: #ff6b6b; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: var(--bg); color: var(--ink); font: 16px/1.6 Georgia, 'Times New Roman', serif;
         padding: 3rem 1.5rem; display: flex; justify-content: center; }}
  main {{ max-width: 52rem; width: 100%; }}
  h1 {{ font-family: ui-monospace, 'Cascadia Code', Consolas, monospace; font-size: 1.05rem; font-weight: 400;
       letter-spacing: .55em; color: var(--accent); text-transform: uppercase;
       border-bottom: 1px solid var(--line); padding-bottom: 1.1rem; margin-bottom: 1.6rem; }}
  h1 span {{ color: var(--dim); letter-spacing: .2em; font-size: .8rem; float: right; margin-top: .2rem; }}
  h2 {{ font-size: 1rem; color: var(--accent); margin: 2rem 0 .7rem; font-weight: 600; }}
  .tag {{ font-size: 1.2rem; line-height: 1.5; margin-bottom: 1.2rem; }}
  .tag strong {{ color: var(--accent); }}
  p {{ margin-bottom: .8rem; }}
  .dim {{ color: var(--dim); font-size: .92rem; }}
  .mono {{ font-family: ui-monospace, 'Cascadia Code', Consolas, monospace; font-size: .85em; }}
  .tablewrap {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .85rem; }}
  th, td {{ text-align: left; padding: .45rem .6rem; border-bottom: 1px solid #1a1d33; vertical-align: top; }}
  th {{ color: var(--dim); font-weight: 400; font-family: ui-monospace, Consolas, monospace; font-size: .72rem;
       text-transform: uppercase; letter-spacing: .08em; }}
  tr.gap td {{ color: var(--bad); }}
  footer {{ margin-top: 2.4rem; padding-top: 1.1rem; border-top: 1px solid var(--line); color: var(--dim);
           font-size: .78rem; line-height: 1.6; font-family: ui-monospace, Consolas, monospace; }}
</style>
</head>
<body>
<main>
  <h1>Ephemera <span>ephemera.space</span></h1>
  <p class="tag">Every eight hours, SpaceX publishes where each Starlink satellite is going, with
  its uncertainty. It is the only public feed of its kind. Each set is replaced by the next.
  <strong>Ephemera keeps the history.</strong></p>

  <h2>The archive record</h2>
  <p>As of <b>{esc(gen)} UTC</b> the archive holds <b>{t["cycles"]}</b> cycles.
  <b>{t["complete"]}</b> are complete with Merkle roots and <b>{t["attested"]}</b> are anchored in
  Bitcoin through OpenTimestamps. Raw data kept: <b>{t["bytes_raw"] / 1e9:.0f} GB</b>.
  Poller heartbeat coverage: {esc(cov_txt)}. Cadence holds (a manifest served longer than
  9 hours): <b>{t["cadence_holds"]}</b>. This project exists because SpaceX publishes the feed
  openly.</p>

  <div class="tablewrap"><table>
    <tr><th>first seen (utc)</th><th>cycle</th><th>files recorded</th><th>raw&nbsp;gb</th>
        <th>merkle root</th><th>opentimestamps</th><th>wayback machine</th></tr>
    {"".join(rows)}
  </table></div>
  <p class="dim">Method: {esc(ledger["method"])}. Poller: {esc(ledger["poller"])}. Full data:
  <a href="ledger.json" style="color:var(--accent)">ledger.json</a>; the verification procedure a
  stranger can run is in the repository's VERIFY.md (independent Merkle re-implementation,
  OpenTimestamps against a Bitcoin block, Wayback copies re-hashed).</p>

  <h2>Daily roots</h2>
  <p class="dim">{droots}</p>

  {vis}

  <h2>Contact</h2>
  <p class="dim">Kira Ryan.
  <a href="mailto:KiraRyan27@gmail.com" style="color:var(--accent)">KiraRyan27@gmail.com</a>,
  <a href="https://www.linkedin.com/in/kira-ryan/" style="color:var(--accent)">linkedin.com/in/kira-ryan</a>.</p>

  <footer>
    <p>Operator ephemerides are predictions, not observations. Inputs are archived by this project
    and witnessed by OpenTimestamps and the Wayback Machine; they are not re-fetchable from the
    source after one cycle. Every figure above carries the build time it was true at. Gapped or
    lost items are printed, never hidden.</p>
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
    globe_out = args.out / "globe"
    globe_out.mkdir(exist_ok=True)
    shutil.copyfile(REPO / "web" / "globe" / "index.html", globe_out / "index.html")
    latest_pack = next((r["pack"] for r in ledger["visibility"]["reports"] if r["pack"]), None)
    if latest_pack:
        shutil.copyfile(latest_pack, globe_out / "pack.json")
    t = ledger["totals"]
    print(f"built: {t['cycles']} cycles ({t['complete']} complete, {t['attested']} attested), "
          f"coverage={ledger['coverage_24h']}, holds={t['cadence_holds']} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
