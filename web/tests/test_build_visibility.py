"""The catalogue-visibility section and the globe: a spool with one scored cycle renders the
figures next to their as-of time, inputs and caveats; the globe page and the latest pack are copied
into the built site; a spool with no scores says so instead of showing an empty table."""
from __future__ import annotations

import json
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


def add_score(spool: Path, cycle: str = "cycle_cccccccccccc", with_pack: bool = True) -> None:
    sha12 = cycle[6:]
    (spool / "score").mkdir(exist_ok=True)
    stats = lambda n, med, p90, w10, w30: {"n": n, "median_km": med, "p90_km": p90, "mean_age_h": 21.4,  # noqa: E731
                                          "within_km": {"1": 0.1, "10": w10, "30": w30}}
    report = {
        "schema": 1, "kind": "catalogue_visibility_v0", "as_of": "2026-09-01T11:30:00Z",
        "method": "Public element set propagated with SGP4 and differenced against the operator-published trajectory; both are predictions.",
        "inputs": {"cycle": cycle, "first_seen_utc": "2026-09-01T04:00:00Z", "merkle_root": "c3" * 32,
                   "manifest_sha256": "cc" * 32, "catalogue_snapshot": "20260901T030000Z_0123456789ab",
                   "catalogue_sha256": "ab" * 32, "catalogue_fetched_utc": "2026-09-01T03:00:00Z",
                   "catalogue_sets": 12811, "limit": None, "snapshot_relation": "before_cycle"},
        "eval_step_min": 360.0, "thresholds_km": [1.0, 10.0, 30.0],
        "counts": {"files": 8900, "scored": 8897, "no_public_set": 2, "decayed_set": 1, "propagation_failed": 0, "unreadable": 0},
        "summary": {"overall": stats(115000, 8.9, 87.5, 0.53, 0.732),
                    "by_age": [{"bin": "0-6 h", **stats(6151, 1.061, 5.6, 0.94, 0.978)},
                               {"bin": "48-72 h", **stats(43546, 25.351, 218.2, 0.35, 0.54)}],
                    "by_shell": []},
        "satellites": {"scored": [], "no_public_set": [1, 2], "decayed_set": [46173], "propagation_failed": [], "unreadable": []},
        "rows_file": f"visibility_{sha12}_rows.json.gz",
    }
    (spool / "score" / f"visibility_{sha12}.json").write_text(json.dumps(report))
    if with_pack:
        (spool / "score" / f"globe_{sha12}.json").write_text(json.dumps({
            "schema": 1, "kind": "globe_pack_v0", "as_of": "2026-09-01T11:31:00Z", "inputs": report["inputs"],
            "method": "pack", "base": "2026-09-01T04:00:00Z", "step_s": 21600, "counts": report["counts"],
            "sats": [{"id": 25544, "name": "STARLINK-1", "l1": "1 25544U 98067A   26245.50000000  .00016717  00000-0  10270-3 0  9005",
                      "l2": "2 25544  51.6400 208.9000 0006700  90.0000 270.0000 15.50000000000000",
                      "set_epoch": "2026-09-01T02:00:00Z", "t0_s": 0, "alt_km": 420.0, "max_km": 12.5,
                      "ric_m": [100, 200, 300, 400, 500, 600]}]}))


def build_site(tmp_path: Path, with_score: bool, with_pack: bool = True):
    spool = make_spool(tmp_path, NOW)
    if with_score:
        add_score(spool, with_pack=with_pack)
    out = tmp_path / "dist"
    rc = build.main(["--spool", str(spool), "--out", str(out)])
    assert rc == 0
    ledger = json.loads((out / "ledger.json").read_text(encoding="utf-8"))
    page = (out / "index.html").read_text(encoding="utf-8")
    return ledger, page, out


def test_scored_cycle_renders_with_inputs_caveats_and_globe_link(tmp_path):
    ledger, page, out = build_site(tmp_path, with_score=True)
    v = ledger["visibility"]
    assert v["latest"] == "cycle_cccccccccccc" and v["reports"][0]["counts"]["scored"] == 8897
    flat = " ".join(page.split())
    assert "Catalogue visibility" in page
    assert "<b>8,897</b> of 8,900 files scored" in flat
    assert "snapshot fetched 2026-09-01 03:00 UTC (12811 element sets)" in flat
    assert "2 without a public set, 1 marked decayed, 0 propagation failures, 0 unreadable" in flat
    assert "Mean element age across the comparison: <b>21.4 h</b>. Scored 2026-09-01 11:30 UTC." in flat
    assert "<td>0-6 h</td><td>6,151</td><td>1.1</td><td>5.6</td><td>94%</td><td>98%</td>" in page
    assert "<td>48-72 h</td><td>43,546</td><td>25.4</td><td>218.2</td><td>35%</td><td>54%</td>" in page
    assert "fetched before the cycle" in page and "<td>1.1</td><td>8.9</td><td>53%</td><td>73%</td>" in page
    assert "Both are predictions." in flat and "planned trajectory changes the public set cannot know about" in flat
    assert "Public GP data is too noisy to test sub-metre covariance" in flat
    assert 'href="globe/"' in page and "See it on the globe" in page
    assert "under construction" not in page
    for ch in ("—", "–", "‘", "’", "“", "”", "·"):
        assert ch not in page
    assert (out / "globe" / "index.html").exists()
    pack = json.loads((out / "globe" / "pack.json").read_text(encoding="utf-8"))
    assert pack["inputs"]["cycle"] == "cycle_cccccccccccc" and pack["sats"][0]["id"] == 25544
    globe = (out / "globe" / "index.html").read_text(encoding="utf-8")
    assert "Operator ephemerides are predictions, not observations." in globe
    assert "cesium@1.131.0" in globe and "satellite.js@5.0.0" in globe and "pack.json" in globe
    for ch in ("—", "–", "‘", "’", "“", "”", "·"):
        assert ch not in globe


def test_no_scores_says_so_and_globe_has_no_pack(tmp_path):
    ledger, page, out = build_site(tmp_path, with_score=False)
    assert ledger["visibility"] == {"reports": [], "latest": None}
    assert "No cycle has been scored yet" in page and "See it on the globe" not in page
    assert (out / "globe" / "index.html").exists() and not (out / "globe" / "pack.json").exists()


def test_score_without_pack_renders_without_globe_link(tmp_path):
    _, page, out = build_site(tmp_path, with_score=True, with_pack=False)
    assert "Catalogue visibility" in page and "See it on the globe" not in page
    assert not (out / "globe" / "pack.json").exists()


def test_built_site_passes_the_claims_lint(tmp_path):
    _, _, out = build_site(tmp_path, with_score=True)
    r = subprocess.run([sys.executable, str(REPO / "tools" / "claims_lint.py"), str(out)], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout


def test_globe_page_computes_from_the_pack_in_a_real_browser(tmp_path):
    """Serve the built site over HTTP (fetch needs it) and let headless Chrome run the page's own
    JavaScript: the status line must be computed from the pack, whether or not WebGL is available."""
    if CHROME is None:
        pytest.skip("no Chrome/Chromium installed")
    _, _, out = build_site(tmp_path, with_score=True)
    import http.server
    import socketserver
    import threading
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(out), **k)  # noqa: E731
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/globe/"
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--dump-dom", "--virtual-time-budget=30000", url],
                           capture_output=True, timeout=120)
        dom = " ".join(r.stdout.decode("utf-8", "replace").split())
    finally:
        srv.shutdown()
    assert "1 satellites | cycle cccccccccccc | public set snapshot fetched 2026-09-01 03:00 UTC" in dom
    assert "showing 2026-09-01 04:00 UTC:" in dom and "of 1" in dom
    assert "Pack built 2026-09-01 11:31 UTC from cycle cccccccccccc (root c3c3c3c3c3c3)" in dom
    assert "STARLINK-1" in dom and "12.5 km at most" in dom
