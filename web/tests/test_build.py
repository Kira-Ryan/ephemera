"""Behavioural tests for web/build.py: the ledger and page are built from a synthetic spool with
one healthy attested cycle, one gapped cycle, a witness loss, a cadence hold and a daily root -
every uncomfortable state must be printed, never hidden. Rendering is additionally checked in a
real browser (headless Chrome DOM dump) when one is installed, per the repo rule that a green flag
is not a picture."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CHROME = next((c for c in (
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium-browser") if Path(c).exists()), None)


def utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_spool(tmp_path: Path, now: datetime) -> Path:
    spool = tmp_path / "spool"
    a = now - timedelta(hours=30)          # healthy, attested, fully witnessed
    b = now - timedelta(hours=16)          # gapped (14 h after a: THE one cadence hold)
    c = now - timedelta(hours=8)           # complete, stamp pending, one witness loss (8 h after b: no hold)

    def cyc(name, first_seen, status, listed, recorded, root, witness=None):
        d = spool / name
        (d / "files").mkdir(parents=True)
        rec = {"cycle": name, "manifest_sha256": name[6:] * 5 + "00", "first_seen_utc": utc(first_seen),
               "status": status, "files_listed": listed, "files_recorded": recorded,
               "files_failed": listed - recorded, "files_not_attempted": 0,
               "bytes_raw": recorded * 2_000_000, "wall_seconds": 2400.0, "merkle_root": root,
               "files": []}
        (d / "cycle.json").write_text(json.dumps(rec))
        if witness is not None:
            (d / "witness.json").write_text(json.dumps(witness))

    cyc("cycle_aaaaaaaaaaaa", a, "complete", 9000, 9000, "a1" * 32, witness={
        "ots": {"stamped_utc": utc(a), "attested": {"block_height": 964904}},
        "wayback": {"manifest": {"verified": True, "timestamp": "20260831060000",
                                 "id_url": "https://web.archive.org/web/20260831060000id_/https://example.invalid/MANIFEST.txt",
                                 "sha256_of_copy": "a1" * 32},
                    "samples": {str(i): {"name": f"f{i}", "verified": True, "timestamp": "20260831060100",
                                         "id_url": f"https://web.archive.org/web/20260831060100id_/https://example.invalid/f{i}",
                                         "sha256_of_copy": f"{i:02d}" * 32} for i in range(10)}}})
    cyc("cycle_bbbbbbbbbbbb", b, "gaps", 9100, 9050, None)
    cyc("cycle_eeeeeeeeeeee", now - timedelta(minutes=20), "in-progress", 9200, 3100, None)
    cyc("cycle_cccccccccccc", c, "complete", 8900, 8900, "c3" * 32, witness={
        "ots": {"stamped_utc": utc(c)},
        "wayback": {"manifest": {"verified": True},
                    "samples": {**{str(i): {"name": f"f{i}", "verified": True} for i in range(9)},
                                "9": {"name": "f9", "verified": False, "attempts": 5,
                                      "gave_up": utc(now), "error": "id_ fetch HTTP 404"}}}})

    ddir = spool / "daily" / a.strftime("%Y-%m-%d")
    ddir.mkdir(parents=True)
    (ddir / "daily.json").write_text(json.dumps({
        "date": a.strftime("%Y-%m-%d"), "merkle_root": "d4" * 32,
        "cycles": [{"cycle": "cycle_aaaaaaaaaaaa"}], "gapped_cycles_excluded": 0,
        "ots": {"stamped_utc": utc(a), "attested": {"block_height": 964950}}}))

    with open(spool / "heartbeats.jsonl", "w") as f:      # 25 h of ticks, one 30-min hole
        t = now - timedelta(hours=25)
        while t <= now:
            hole = now - timedelta(hours=5) <= t < now - timedelta(hours=4, minutes=30)
            if not hole:
                f.write(json.dumps({"utc": utc(t)}) + "\n")
            t += timedelta(minutes=2)
    return spool


# The pages web/pages.py renders, by path under the site root. The globe is built beside them.
PAGES = ("index.html", "finding/index.html", "scored/index.html", "archive/index.html", "check/index.html", "404.html")


@pytest.fixture
def built(tmp_path, monkeypatch):
    """The whole site as build.main() writes it, at a pinned build time: the ledger, every page's
    HTML keyed by its path (the globe included), and the output directory."""
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    spool = make_spool(tmp_path, now)
    out = tmp_path / "dist"
    monkeypatch.setattr(build, "utc_now", lambda: now)
    assert build.main(["--spool", str(spool), "--out", str(out)]) == 0
    ledger = json.loads((out / "ledger.json").read_text(encoding="utf-8"))
    site = {rel: (out / rel).read_text(encoding="utf-8") for rel in PAGES + ("globe/index.html",)}
    return ledger, site, out


def serve(out: Path):
    """A throwaway HTTP server on a free port with the built site as its root, for the browser
    tests. Shut it down with srv.shutdown()."""
    import http.server
    import socketserver
    import threading
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(out), **k)  # noqa: E731
    srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_ledger_counts_and_coverage(built):
    ledger, _, _ = built
    t = ledger["totals"]
    assert (t["cycles"], t["complete"], t["attested"]) == (4, 2, 1)
    assert t["cadence_holds"] == 1                      # the 14-hour gap between cycles a and b
    # The 30-minute hole starts ON a tick boundary, so the last tick before it is 2 min earlier;
    # minutes stay covered for 10 min after that tick: uncovered = 30 + 2 - 10 = 22 of 1440.
    assert ledger["coverage_24h"] == pytest.approx(1 - 22 / 1440, abs=1e-6)


def test_page_prints_the_uncomfortable_truths(built):
    """Mutation: drop the gap row styling/text, the loss count, or the cadence-hold figure -> red.
    The per-cycle rows live on the archive page; the front page carries the figures and the strip,
    whose blocks link to those rows."""
    _, site, _ = built
    page, archive = site["index.html"], site["archive/index.html"]
    assert "INCOMPLETE: 50 of 9,100 missing, recorded" in archive
    # a pull still running is not a gap: neutral wording, no red row, stamp follows the pull
    assert "pulling now: 3,100 of 9,200 so far" in archive
    assert archive.count('class="gap"') == 1 and "follows the pull" in archive
    # the owner's standing voice rule for outward text: no em or en dashes, no smart quotes,
    # no middle-dot separators, on every page
    for rel, doc in site.items():
        for ch in ("—", "–", "‘", "’", "“", "”", "·"):
            assert ch not in doc, f"typographic character {ch!r} crept into {rel}"
    for rel in PAGES:
        assert "mailto:KiraRyan27@gmail.com" in site[rel] and "linkedin.com/in/kira-ryan" in site[rel], rel
    assert 'class="gap" id="c-bbbbbbbbbbbb"' in archive
    assert 'href="archive/#c-bbbbbbbbbbbb"><rect class="miss"' in page   # the front page's strip paints it red
    assert "1 lost" in archive                           # the given-up witness sample
    assert 'class="warn" id="c-cccccccccccc"' in archive  # and its row is marked, not silent
    assert 'href="archive/#c-cccccccccccc"><rect class="warn"' in page   # as is its block on the strip
    assert ">1</b>" in page and "cadence holds" in page.lower()
    assert "block 964904" in page and "stamp" in page.lower()
    flat = " ".join(page.split())                       # the template wraps lines mid-phrase
    assert "Operator ephemerides are predictions, not observations." in flat
    assert "not re-fetchable from the source after one cycle" in flat
    assert "As of <b>2026-09-01 12:00" in page          # every figure carries its as-of time
    for rel in PAGES:
        assert "built 2026-09-01 12:00 UTC" in site[rel], rel


def test_coverage_short_history_says_not_measured(tmp_path):
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    spool = make_spool(tmp_path, now)
    lines = (spool / "heartbeats.jsonl").read_text().splitlines()
    (spool / "heartbeats.jsonl").write_text("\n".join(lines[-60:]) + "\n")  # only ~2 h of history
    ledger = build.build_ledger(spool, now)
    assert ledger["coverage_24h"] is None
    assert "not yet measured" in build.render(ledger)


def test_built_page_passes_the_claims_lint(built):
    _, _, out = built
    r = subprocess.run([sys.executable, str(REPO / "tools" / "claims_lint.py"), str(out)],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout


SITE_PATHS = ("", "finding/", "scored/", "archive/", "check/", "404.html", "globe/")


def test_page_renders_in_a_real_browser(built, tmp_path):
    """Every page is served over HTTP and loaded in headless Chrome. Each must render the mark and
    the wordmark, carry the first caveat, and raise no error in the console: Chrome writes console
    messages to stderr as CONSOLE lines, and an uncaught exception arrives there as one."""
    if CHROME is None:
        pytest.skip("no Chrome/Chromium installed")
    _, _, out = built
    srv = serve(out)
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}/"
        doms, consoles = {}, {}
        for path in SITE_PATHS:
            r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--enable-logging=stderr", "--v=0",
                                "--dump-dom", base + path], capture_output=True, timeout=90)
            doms[path] = " ".join(r.stdout.decode("utf-8", "replace").split())  # Chrome emits UTF-8; never let
            consoles[path] = [line for line in r.stderr.decode("utf-8", "replace").splitlines()  # the locale
                              if "CONSOLE" in line]                                                # codec near it
    finally:
        srv.shutdown()
    for path, dom in doms.items():
        assert '<svg class="mark"' in dom and (">Ephemera</a>" in dom or ">Ephemera</span>" in dom), path
        assert "Operator ephemerides are predictions, not observations." in dom, path
        errors = [line for line in consoles[path] if re.search(r"Uncaught|\bError\b|\berror\b", line)]
        assert not errors, f"/{path} raised in the console: {errors}"
    assert "INCOMPLETE: 50 of 9,100 missing, recorded" in doms["archive/"]
    for path in SITE_PATHS[:-1]:
        assert "ledger.json" in doms[path], path
    # the tab bar knows which page it is on, the globe included
    assert '<a href="./" aria-current="page">' in doms[""]
    assert '<a href="../archive/" aria-current="page">' in doms["archive/"]
    assert '<a href="../globe/" aria-current="page"' in doms["globe/"]
