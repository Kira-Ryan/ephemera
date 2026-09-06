"""The finding section, the brand assets and the globe.

A spool with one scored cycle must render the comparable headline, the age curve, the truth-health
line and the caveats, mark a hindsight pairing as not comparable, and copy the globe page, the icon
and the newest pack into the built site. A spool with no scores must say so instead of showing an
empty table, and a report written before the headline existed must be called out rather than
crashing the build or being printed as if it were comparable.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402
from test_build import CHROME, REPO, make_spool  # noqa: E402

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
TLE1 = "1 25544U 98067A   26245.50000000  .00016717  00000-0  10270-3 0  9005"
TLE2 = "2 25544  51.6400 208.9000 0006700  90.0000 270.0000 15.50000000000000"


def stats(n, med, p90, w10, w30, lost=0, age=21.4):
    return {"n": n, "median_km": med, "p90_km": p90, "mean_age_h": age, "median_age_h": age,
            "within_km": {"1": 0.1, "10": w10, "30": w30}, "lost": lost,
            "lost_fraction": round(lost / n, 4) if n else 0.0}


def add_score(spool: Path, cycle: str = "cycle_cccccccccccc", with_pack: bool = True,
              relation: str = "before_cycle", headline: bool = True,
              first_seen: str = "2026-09-01T04:00:00Z") -> None:
    sha12 = cycle[6:]
    (spool / "score").mkdir(exist_ok=True)
    start = stats(8897, 3.0, 16.9, 0.81, 0.955, lost=41, age=12.6)
    start["satellites"] = start.pop("n")
    report = {
        "schema": 1, "kind": "catalogue_visibility_v0", "as_of": "2026-09-01T11:30:00Z",
        "method": "Public element set propagated with SGP4 and differenced against the operator-published trajectory.",
        "inputs": {"cycle": cycle, "first_seen_utc": first_seen, "merkle_root": "c3" * 32,
                   "manifest_sha256": "cc" * 32, "catalogue_snapshot": "20260901T030000Z_0123456789ab",
                   "catalogue_sha256": "ab" * 32, "catalogue_fetched_utc": "2026-09-01T03:00:00Z",
                   "catalogue_sets": 12811, "limit": None, "snapshot_relation": relation},
        "eval_step_min": 360.0, "thresholds_km": [1.0, 10.0, 30.0],
        "counts": {"files": 8900, "scored": 8897, "no_public_set": 27, "uncatalogued": 27, "decayed_set": 1,
                   "propagation_failed": 0, "unreadable": 0},
        "summary": {"overall": stats(115000, 8.9, 87.5, 0.53, 0.73, lost=3726, age=51.2),
                    "at_file_start": start if headline else None,
                    "catalogue_age": {"sets": 8897, "mean_h": 15.1, "median_h": 12.3, "p90_h": 27.6, "over_72h": 26},
                    "by_age": [{"bin": "0-6 h", **stats(6151, 1.4, 5.6, 0.94, 0.978)},
                               {"bin": "12-24 h", **stats(17318, 4.6, 25.6, 0.75, 0.91)},
                               {"bin": "48-72 h", **stats(43546, 24.8, 218.2, 0.35, 0.54)}],
                    "by_shell": [{"bin": "400-500 km", **stats(116938, 8.7, 63.3, 0.53, 0.75)}]},
        "satellites": {"scored": [], "no_public_set": [], "decayed_set": [46173], "propagation_failed": [],
                       "unreadable": []},
        "rows_file": f"visibility_{sha12}_rows.json.gz",
    }
    (spool / "score" / f"visibility_{sha12}.json").write_text(json.dumps(report))
    if with_pack:
        (spool / "score" / f"globe_{sha12}.json").write_text(json.dumps({
            "schema": 1, "kind": "globe_pack_v0", "as_of": "2026-09-01T11:31:00Z", "inputs": report["inputs"],
            "method": "pack", "base": "2026-09-01T04:00:00Z", "step_s": 21600, "counts": report["counts"],
            "sats": [{"id": 25544, "name": "STARLINK-1", "l1": TLE1, "l2": TLE2,
                      "set_epoch": "2026-09-01T02:00:00Z", "t0_s": 0, "alt_km": 420.0, "max_km": 12.5,
                      "ric_m": [100, 200, 300, 400, 500, 600]}]}))


def add_catalogue(spool: Path) -> None:
    d = spool / "gp" / "20260901T030000Z_0123456789ab"
    d.mkdir(parents=True)
    (d / "record.json").write_text(json.dumps({"fetched_utc": "2026-09-01T03:00:00Z", "records": 12811,
                                               "sha256": "ab" * 32}))


def build_site(tmp_path: Path, with_score: bool = True, **kw):
    spool = make_spool(tmp_path, NOW)
    add_catalogue(spool)
    if with_score:
        add_score(spool, **kw)
    out = tmp_path / "dist"
    assert build.main(["--spool", str(spool), "--out", str(out)]) == 0
    return (json.loads((out / "ledger.json").read_text(encoding="utf-8")),
            (out / "index.html").read_text(encoding="utf-8"), out)


def test_headline_is_the_comparable_figure_and_carries_its_provenance(tmp_path):
    ledger, page, out = build_site(tmp_path)
    flat = " ".join(page.split())
    assert ledger["visibility"]["latest"] == "cycle_cccccccccccc"
    # the hero is the at-file-start cut, not the incomparable overall median
    assert "puts <b>81%</b> of the scored Starlink satellites within 10 km" in flat
    assert "At the first instant of each operator file" in flat
    assert "The middle satellite is <b>3.0 km</b> away, with the public information a median of 13 hours old" in flat
    assert "Where the public information is two to three days old" in flat and "<b>25 km</b> apart" in flat
    assert "within 10 km at file start" in flat and "median miss at file start" in flat
    assert "3.0 km" in page
    # provenance and truth health
    assert "scored 2026-09-01 11:30 UTC against the public catalogue snapshot fetched 2026-09-01 03:00 UTC" in flat
    assert "8,897 of 8,900 operator files scored" in flat
    assert "27 have no entry in the public catalogue, of which 27 are new satellites" in flat
    assert "mean of <b>15.1 h</b> old when the snapshot was taken" in flat
    assert "element age is 51.2 h: the difference is the file's own prediction horizon" in flat
    assert "Space-Track: 1 snapshots held" in flat
    # the lost category is its own statement and is never called a manoeuvre
    assert '<b class="warnk">41</b> satellites (0.5%)' in flat
    assert "does not label any separation as a manoeuvre" in flat
    # the age curve is drawn from the same numbers as the table
    assert 'class="curve"' in page and "<polyline" in page
    assert "<td>0-6 h</td>" in page and "<td>48-72 h</td>" in page
    assert 'href="globe/"' in page and "See it on the globe" in page


def test_hindsight_pairing_is_marked_not_comparable(tmp_path):
    _, page, _ = build_site(tmp_path, relation="after_cycle")
    flat = " ".join(page.split())
    assert "scored with hindsight" in flat and 'class="warnk"' in page
    assert "already know what the satellite did during the file" in flat
    assert "1 of 1 scored cycles are in that state" in flat


def test_report_without_the_headline_is_called_out_not_crashed(tmp_path):
    _, page, _ = build_site(tmp_path, headline=False)
    flat = " ".join(page.split())
    assert "scored before the comparable headline existed" in flat
    assert "81%" not in flat                      # no headline claimed from a report that lacks one


def test_no_scores_says_so(tmp_path):
    ledger, page, out = build_site(tmp_path, with_score=False)
    assert ledger["visibility"] == {"reports": [], "latest": None}
    assert "No cycle has been scored yet" in page and "See it on the globe" not in page
    assert (out / "globe" / "index.html").exists() and not (out / "globe" / "pack.json").exists()


def test_brand_assets_are_built_and_linked(tmp_path):
    _, page, out = build_site(tmp_path)
    for name in ("icon.svg", "icon-180.png", "icon-512.png", "social.png"):
        assert (out / name).exists() and (out / name).stat().st_size > 200, name
    assert '<link rel="icon" href="icon.svg" type="image/svg+xml">' in page
    assert '<meta property="og:image" content="https://ephemera.space/social.png">' in page
    assert '<link rel="canonical" href="https://ephemera.space/">' in page
    assert '<svg class="mark"' in page and 'aria-hidden="true"' in page      # the inline masthead mark
    assert (out / "globe" / "icon.svg").exists()


def test_witness_defects_are_visible_and_named(tmp_path):
    """A cycle whose own pull succeeded but whose independent copy failed must not render as ok."""
    ledger, page, _ = build_site(tmp_path)
    assert ledger["totals"]["witness_defects"] >= 1
    assert 'class="warn"' in page
    assert "Amber marks a cycle whose own pull succeeded but whose independent copy did not" in " ".join(page.split())


def test_storage_says_where_the_bytes_actually_are(tmp_path):
    ledger, page, _ = build_site(tmp_path)
    t = ledger["totals"]
    assert t["bytes_stored_local"] + t["bytes_stored_cold_only"] == t["bytes_stored"]
    flat = " ".join(page.split())
    assert "Source bytes archived" in flat and "Stored gzipped as" in flat
    assert "exists only in cold object storage" in flat


def test_sections_are_present_and_linkable(tmp_path):
    _, page, _ = build_site(tmp_path)
    for anchor in ("finding", "archive", "check", "data", "next", "who"):
        assert f'id="{anchor}"' in page, anchor
        assert f'href="#{anchor}"' in page, anchor
    flat = " ".join(page.split())
    assert "Fetch an independent copy and hash it" in flat and "ots verify root.txt.ots" in flat
    assert "What you cannot do from this page alone is rebuild the Merkle root" in flat
    assert "web.archive.org/web/20260831060000id_" in page          # a link a stranger can actually open
    assert "Code is MIT" in flat and "Ryan, K. (2026)" in flat
    assert "A second poller on a different machine" in flat
    assert "mailto:KiraRyan27@gmail.com" in page and "linkedin.com/in/kira-ryan" in page


def test_no_typographic_characters_anywhere_in_the_built_site(tmp_path):
    _, page, out = build_site(tmp_path)
    globe = (out / "globe" / "index.html").read_text(encoding="utf-8")
    for ch in ("—", "–", "‘", "’", "“", "”", "·"):
        assert ch not in page, f"{ch!r} in index.html"
        assert ch not in globe, f"{ch!r} in globe/index.html"


def test_built_site_passes_the_claims_lint(tmp_path):
    _, _, out = build_site(tmp_path)
    r = subprocess.run([sys.executable, str(REPO / "tools" / "claims_lint.py"), str(out)],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout


def _serve(out: Path):
    import http.server
    import socketserver
    import threading
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(out), **k)  # noqa: E731
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_globe_keeps_its_caveats_at_every_width_in_a_real_browser(tmp_path):
    """Mutation: put `#foot { display: none }` back in the mobile media query and this fails."""
    if CHROME is None:
        pytest.skip("no Chrome/Chromium installed")
    _, _, out = build_site(tmp_path)
    src = (out / "globe" / "index.html").read_text(encoding="utf-8")
    probe = out / "globe" / "probe.html"
    probe.write_text(src.replace("</body>", """<script>
      addEventListener('load', () => setTimeout(() => {
        const box = (sel) => { const e = document.querySelector(sel); if (!e) return null;
          const r = e.getBoundingClientRect();
          return getComputedStyle(e).display === 'none' || r.height === 0 ? null : r; };
        const f = box('#foot');
        const hit = (b) => !!f && !!b && !(f.right <= b.left || f.left >= b.right
                                          || f.bottom <= b.top || f.top >= b.bottom);
        document.body.insertAdjacentHTML('afterbegin', '<div id=probe>' + innerWidth
          + '|' + (f ? 'CAVEATS-VISIBLE' : 'CAVEATS-HIDDEN')
          + '|' + (hit(box('.cesium-viewer-timelineContainer')) ? 'TIMELINE-COVERED' : 'TIMELINE-CLEAR')
          + '|' + (hit(box('.cesium-viewer-animationContainer')) ? 'CLOCK-COVERED' : 'CLOCK-CLEAR')
          + '</div>');
      }, 3000));
    </script></body>"""), encoding="utf-8")
    srv = _serve(out)
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/globe/probe.html"
        seen = {}
        for width in (400, 900, 1560):
            r = subprocess.run([CHROME, "--headless=new", "--use-angle=swiftshader",
                                "--enable-unsafe-swiftshader", "--force-device-scale-factor=1",
                                f"--window-size={width},900", "--virtual-time-budget=40000", "--dump-dom", url],
                               capture_output=True, timeout=180)
            seen[width] = " ".join(r.stdout.decode("utf-8", "replace").split())
    finally:
        srv.shutdown()
        probe.unlink(missing_ok=True)
    for width, dom in seen.items():
        assert "CAVEATS-VISIBLE" in dom, f"the required caveats are hidden at {width}px"
        # Cesium sizes its clock with the viewport, so a panel that clears it at one width can cover
        # it at another. Both widgets are checked at every width.
        assert "TIMELINE-CLEAR" in dom, f"the caveats cover the timeline at {width}px"
        assert "CLOCK-CLEAR" in dom, f"the caveats cover the clock at {width}px"


def test_globe_computes_from_the_pack_in_a_real_browser(tmp_path):
    if CHROME is None:
        pytest.skip("no Chrome/Chromium installed")
    _, _, out = build_site(tmp_path)
    srv = _serve(out)
    try:
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--dump-dom", "--virtual-time-budget=30000",
                            f"http://127.0.0.1:{srv.server_address[1]}/globe/"], capture_output=True, timeout=120)
        dom = " ".join(r.stdout.decode("utf-8", "replace").split())
    finally:
        srv.shutdown()
    assert "1 satellites | cycle cccccccccccc | public set snapshot fetched 2026-09-01 03:00 UTC" in dom
    # the clock animates from the pack base, so the instant advances between runs: pin the day and
    # the shape, never the minute, or this test flakes under load
    shown = re.search(r"showing 2026-09-01 \d\d:\d\d UTC: \d+ within 1 km, (\d+) within 10 km, "
                      r"\d+ at 30 km or beyond, of (\d+)", dom)
    assert shown, dom[dom.find("showing"):dom.find("showing") + 200]
    assert shown.group(1) == "1" and shown.group(2) == "1"
    assert "Pack built 2026-09-01 11:31 UTC from cycle cccccccccccc (root c3c3c3c3c3c3)" in dom
    assert "STARLINK-1" in dom and "12.5 km at most" in dom


def test_headline_never_comes_from_a_hindsight_pairing(tmp_path):
    """Mutation: make headline_report() return reports[0] and this fails. A cycle scored against a
    later snapshot is not comparable, so it must not supply the top tiles or the hero sentence."""
    spool = make_spool(tmp_path, NOW)
    add_catalogue(spool)
    add_score(spool, cycle="cycle_cccccccccccc", relation="after_cycle", first_seen="2026-09-01T04:00:00Z")
    add_score(spool, cycle="cycle_aaaaaaaaaaaa", relation="before_cycle", first_seen="2026-08-31T06:00:00Z")
    out = tmp_path / "dist"
    assert build.main(["--spool", str(spool), "--out", str(out)]) == 0
    ledger = json.loads((out / "ledger.json").read_text(encoding="utf-8"))
    page = (out / "index.html").read_text(encoding="utf-8")
    # the newest report is the hindsight one; the headline must come from the older comparable one
    assert ledger["visibility"]["reports"][0]["snapshot_relation"] == "after_cycle"
    assert build.headline_report(ledger["visibility"]["reports"])["cycle"] == "cycle_aaaaaaaaaaaa"
    flat = " ".join(page.split())
    assert "cycle aaaaaaaaaaaa" in flat.replace("<span class=\"mono\">", "cycle ").replace("</span>", "")
    assert "scored with hindsight" in flat


def test_a_cycle_with_no_scored_rows_renders_instead_of_crashing(tmp_path):
    spool = make_spool(tmp_path, NOW)
    add_catalogue(spool)
    add_score(spool)
    rp = spool / "score" / "visibility_cccccccccccc.json"
    r = json.loads(rp.read_text())
    r["summary"]["overall"] = None
    r["summary"]["at_file_start"] = None
    r["counts"] = {"files": 10, "scored": 0, "no_public_set": 10, "uncatalogued": 0, "decayed_set": 0,
                   "propagation_failed": 0, "unreadable": 0}
    rp.write_text(json.dumps(r))
    out = tmp_path / "dist"
    assert build.main(["--spool", str(spool), "--out", str(out)]) == 0
    flat = " ".join((out / "index.html").read_text(encoding="utf-8").split())
    assert "No comparison was made for this cycle" in flat
    assert "NOTHING SCORED" in flat


def test_pending_witnessing_is_not_painted_as_an_independent_copy(tmp_path):
    """A complete cycle whose Wayback copy has not been made yet is grey, not green.

    Mutation: drop the pending branch in cycle_strip and this cycle turns green, telling the reader
    an independent copy exists when witnessing has not run."""
    spool = make_spool(tmp_path, NOW)
    add_catalogue(spool)
    d = spool / "cycle_dddddddddddd"
    (d / "files").mkdir(parents=True)
    (d / "cycle.json").write_text(json.dumps({
        "cycle": "cycle_dddddddddddd", "manifest_sha256": "dd" * 32, "first_seen_utc": "2026-09-01T11:00:00Z",
        "status": "complete", "files_listed": 9000, "files_recorded": 9000, "files_failed": 0,
        "bytes_raw": 18_000_000_000, "wall_seconds": 2400.0, "merkle_root": "d1" * 32, "files": []}))
    out = tmp_path / "dist"
    assert build.main(["--spool", str(spool), "--out", str(out)]) == 0
    page = (out / "index.html").read_text(encoding="utf-8")
    assert 'class="pending"' in page
    assert "grey is complete with the copy still pending" in " ".join(page.split())
    assert build.witness_defect({"wayback": {"attempted": False}}) is None


def test_catalogue_snapshot_total_survives_the_recent_list_cap(tmp_path):
    spool = make_spool(tmp_path, NOW)
    for i in range(15):
        d = spool / "gp" / f"2026090{i % 9}T0{i % 9}0000Z_{i:012d}"
        d.mkdir(parents=True)
        (d / "record.json").write_text(json.dumps({"fetched_utc": f"2026-09-0{1 + i % 3}T0{i % 9}:00:00Z",
                                                   "records": 12811, "sha256": f"{i:064d}"}))
    add_score(spool)
    out = tmp_path / "dist"
    assert build.main(["--spool", str(spool), "--out", str(out)]) == 0
    ledger = json.loads((out / "ledger.json").read_text(encoding="utf-8"))
    assert ledger["catalogue_snapshots"] == 15 and len(ledger["catalogue"]) == 12
    assert "Space-Track: 15 snapshots held" in " ".join((out / "index.html").read_text(encoding="utf-8").split())


def test_daily_root_exclusion_reason_is_derived_from_the_cycle(tmp_path):
    """An incomplete pull left out of a daily root must not be described as merely still pulling."""
    spool = make_spool(tmp_path, NOW)
    add_catalogue(spool)
    day = (NOW - __import__("datetime").timedelta(hours=16)).strftime("%Y-%m-%d")
    ddir = spool / "daily" / day
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "daily.json").write_text(json.dumps({
        "date": day, "merkle_root": "e5" * 32, "built_utc": "2026-09-02T00:04:00Z",
        "cycles": [], "gapped_cycles_excluded": 1, "ots": {}}))
    out = tmp_path / "dist"
    assert build.main(["--spool", str(spool), "--out", str(out)]) == 0
    flat = " ".join((out / "index.html").read_text(encoding="utf-8").split())
    assert "incomplete pull, no root" in flat


# --------------------------------------------------------------- audit, 6 Sep 2026


def test_the_headline_is_attributed_to_the_cycle_it_came_from(tmp_path):
    """The headline is taken from the newest comparable report, but the line under it named the
    newest report of any kind. With a hindsight-paired cycle on top, the page printed one cycle's
    figures under another cycle's name.

    Mutation: attribute to reports[0] and this goes red."""
    spool = make_spool(tmp_path, NOW)
    add_catalogue(spool)
    add_score(spool, cycle="cycle_cccccccccccc", relation="after_cycle", first_seen="2026-09-01T04:00:00Z")
    add_score(spool, cycle="cycle_aaaaaaaaaaaa", relation="before_cycle", first_seen="2026-08-31T06:00:00Z")
    out = tmp_path / "dist"
    assert build.main(["--spool", str(spool), "--out", str(out)]) == 0
    flat = " ".join((out / "index.html").read_text(encoding="utf-8").split())
    assert "Headline figures from cycle aaaaaaaaaaaa" in flat
    assert "Headline figures from cycle cccccccccccc" not in flat


def test_the_published_globe_pack_is_the_cycle_the_page_describes(tmp_path):
    """The page linked the globe from the headline report while the build published whichever pack
    was newest, so the globe could be showing a different cycle from the one the text describes."""
    spool = make_spool(tmp_path, NOW)
    add_catalogue(spool)
    add_score(spool, cycle="cycle_cccccccccccc", relation="after_cycle", first_seen="2026-09-01T04:00:00Z")
    add_score(spool, cycle="cycle_aaaaaaaaaaaa", relation="before_cycle", first_seen="2026-08-31T06:00:00Z")
    out = tmp_path / "dist"
    assert build.main(["--spool", str(spool), "--out", str(out)]) == 0
    pack = json.loads((out / "globe" / "pack.json").read_text(encoding="utf-8"))
    assert pack["inputs"]["cycle"] == "cycle_aaaaaaaaaaaa", "the globe shows a different cycle from the page"


def test_a_rebuild_with_nothing_to_publish_removes_a_stale_pack(tmp_path):
    """A build with no scored cycle left the previous pack in place, so the globe went on serving
    figures the page no longer mentions and no longer stands behind."""
    spool = make_spool(tmp_path, NOW)
    add_catalogue(spool)
    add_score(spool)
    out = tmp_path / "dist"
    assert build.main(["--spool", str(spool), "--out", str(out)]) == 0
    assert (out / "globe" / "pack.json").exists()

    for f in (spool / "score").glob("*.json"):
        f.unlink()
    assert build.main(["--spool", str(spool), "--out", str(out)]) == 0
    assert not (out / "globe" / "pack.json").exists(), "a stale globe pack survived a rebuild"


def test_a_name_from_the_pack_cannot_run_script_in_the_page(tmp_path):
    """The page escapes what the pack gives it, whatever the pack builder already did.

    Mutation: drop esc() at either innerHTML sink and this goes red."""
    if CHROME is None:
        pytest.skip("no Chrome/Chromium installed")
    spool = make_spool(tmp_path, NOW)
    add_catalogue(spool)
    add_score(spool)
    packs = list((spool / "score").glob("globe_*.json"))
    pack = json.loads(packs[0].read_text())
    pack["sats"][0]["name"] = '<img src=x onerror="window.__pwned=1">'
    packs[0].write_text(json.dumps(pack))
    out = tmp_path / "dist"
    assert build.main(["--spool", str(spool), "--out", str(out)]) == 0

    src = (out / "globe" / "index.html").read_text(encoding="utf-8")
    probe = out / "globe" / "probe.html"
    probe.write_text(src.replace("</body>", """<script>
      addEventListener('load', () => setTimeout(() => {
        const imgs = document.querySelectorAll('#worst img, #sel img').length;
        document.body.insertAdjacentHTML('afterbegin',
          '<div id=probe>' + (window.__pwned ? 'PWNED' : 'clean') + '|imgs=' + imgs + '</div>');
      }, 1500));
    </script></body>"""), encoding="utf-8")
    srv = _serve(out)
    try:
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--virtual-time-budget=25000",
                            "--dump-dom", f"http://127.0.0.1:{srv.server_address[1]}/globe/probe.html"],
                           capture_output=True, timeout=120)
        dom = " ".join(r.stdout.decode("utf-8", "replace").split())
    finally:
        srv.shutdown()
        probe.unlink(missing_ok=True)
    # Read the probe's own verdict, not the whole document: the probe's source contains the word
    # it reports with, so searching the dump would always match.
    verdict = re.search(r'<div id="?probe"?>(.*?)</div>', dom)
    assert verdict, dom[-400:]
    assert verdict.group(1) == "clean|imgs=0", f"a catalogue name reached the DOM as markup: {verdict.group(1)}"
