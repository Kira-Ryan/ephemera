"""Behavioural tests for web/build.py: the ledger and page are built from a synthetic spool with
one healthy attested cycle, one gapped cycle, a witness loss, a cadence hold and a daily root -
every uncomfortable state must be printed, never hidden. Rendering is additionally checked in a
real browser (headless Chrome DOM dump) when one is installed, per the repo rule that a green flag
is not a picture."""
from __future__ import annotations

import json
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
        "wayback": {"manifest": {"verified": True},
                    "samples": {str(i): {"name": f"f{i}", "verified": True} for i in range(10)}}})
    cyc("cycle_bbbbbbbbbbbb", b, "gaps", 9100, 9050, None)
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


@pytest.fixture
def built(tmp_path):
    now = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    spool = make_spool(tmp_path, now)
    out = tmp_path / "dist"
    ledger = build.build_ledger(spool, now)
    out.mkdir()
    (out / "ledger.json").write_text(json.dumps(ledger, indent=1), encoding="utf-8")
    page = build.render(ledger)
    (out / "index.html").write_text(page, encoding="utf-8")
    return ledger, page, out


def test_ledger_counts_and_coverage(built):
    ledger, _, _ = built
    t = ledger["totals"]
    assert (t["cycles"], t["complete"], t["attested"]) == (3, 2, 1)
    assert t["cadence_holds"] == 1                      # the 14-hour gap between cycles a and b
    # The 30-minute hole starts ON a tick boundary, so the last tick before it is 2 min earlier;
    # minutes stay covered for 10 min after that tick: uncovered = 30 + 2 - 10 = 22 of 1440.
    assert ledger["coverage_24h"] == pytest.approx(1 - 22 / 1440, abs=1e-6)


def test_page_prints_the_uncomfortable_truths(built):
    """Mutation: drop the gap row styling/text, the loss count, or the cadence-hold figure -> red."""
    _, page, _ = built
    assert "INCOMPLETE — 50 of 9,100 missing, recorded" in page
    assert 'class="gap"' in page
    assert "1 lost" in page                              # the given-up witness sample
    assert ">1</b>" in page and "cadence holds" in page.lower()
    assert "block 964904" in page and "stamp" in page.lower()
    flat = " ".join(page.split())                       # the template wraps lines mid-phrase
    assert "Operator ephemerides are predictions, not observations." in flat
    assert "not re-fetchable from the source after one cycle" in flat
    assert "As of <b>2026-09-01 12:00" in page          # every figure carries its as-of time


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


def test_page_renders_in_a_real_browser(built, tmp_path):
    if CHROME is None:
        pytest.skip("no Chrome/Chromium installed")
    _, _, out = built
    r = subprocess.run([CHROME, "--headless", "--disable-gpu", "--dump-dom",
                        (out / "index.html").resolve().as_uri()],
                       capture_output=True, timeout=60)
    dom = " ".join(r.stdout.decode("utf-8", "replace").split())  # Chrome emits UTF-8; never let
    assert "INCOMPLETE — 50 of 9,100 missing, recorded" in dom   # the locale codec near it
    assert "Operator ephemerides are predictions, not observations." in dom
    assert "ledger.json" in dom
