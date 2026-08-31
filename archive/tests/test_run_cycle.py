"""Behavioural tests for archive/run_cycle.py: the watcher pulls a new manifest once, skips a
complete cycle, retries a gapped one, and heart-beats every tick. Driven through main(--once)."""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_cycle  # noqa: E402
import poll  # noqa: E402
from test_poll import CONTACT, Feed, build_site, make_file  # noqa: E402


@pytest.fixture
def feed(tmp_path):
    site, names = build_site(tmp_path)
    f = Feed(site, names)
    try:
        yield f
    finally:
        f.close()


def once(feed: Feed, spool: Path) -> tuple[int, dict]:
    rc = run_cycle.main(["--base", feed.base, "--spool", str(spool), "--workers", "4",
                         "--contact", CONTACT, "--min-free-gb", "0", "--once"])
    return rc, json.loads((spool / "heartbeat.json").read_text())


def test_new_manifest_is_pulled_once_then_skipped(feed, tmp_path):
    """Mutation: drop the 'complete' check in tick() -> the second tick re-issues 3 file GETs, red."""
    spool = tmp_path / "spool"
    rc1, hb1 = once(feed, spool)
    assert rc1 == 0 and hb1["action"] == "pulled" and hb1["cycles_complete"] == 1
    assert hb1["tick"] == 1 and CONTACT in hb1["poller"] and hb1["last_exit"] == 0
    gets_after_first = feed.file_gets()
    assert gets_after_first == 3
    rc2, hb2 = once(feed, spool)
    assert rc2 == 0 and hb2["action"] == "skipped-complete"
    assert feed.file_gets() == gets_after_first  # not even a conditional GET per file
    assert hb2["manifest_sha256"] == hb1["manifest_sha256"]


def test_gapped_cycle_is_retried_while_its_manifest_is_current(feed, tmp_path, monkeypatch):
    monkeypatch.setattr(poll, "BACKOFF_S", 0.0)
    missing = "MEME_0_LATE_0_Operational_0_UNCLASSIFIED.txt"
    (feed.site / "MANIFEST.txt").write_text("\n".join(feed.names + [missing]) + "\n")
    spool = tmp_path / "spool"
    rc1, hb1 = once(feed, spool)
    assert rc1 == 2 and hb1["action"] == "pulled" and hb1["last_exit"] == 2 and hb1["cycles_complete"] == 0
    (feed.site / missing).write_bytes(make_file(9))  # the file appears; same manifest bytes
    rc2, hb2 = once(feed, spool)
    assert rc2 == 0 and hb2["action"] == "pulled" and hb2["cycles_complete"] == 1
    rec = json.loads(next(spool.glob("cycle_*/cycle.json")).read_text())
    assert rec["status"] == "complete" and rec["files_recorded"] == 4
    assert sum(1 for r in rec["files"] if r["status"] == "unchanged-304") == 3


def test_daemon_loop_retries_an_incomplete_cycle_while_the_manifest_is_unchanged(feed, tmp_path, monkeypatch):
    """The real loop keeps one state dict, so the manifest GET answers 304 on every later tick. A
    gapped cycle must still be re-pulled. Mutation: return on 304 before checking the cycle record
    -> the cycle stays 'gaps' for as long as the manifest does not change, red."""
    monkeypatch.setattr(poll, "BACKOFF_S", 0.0)
    missing = "MEME_0_LATE_0_Operational_0_UNCLASSIFIED.txt"
    (feed.site / "MANIFEST.txt").write_text("\n".join(feed.names + [missing]) + "\n")
    spool = tmp_path / "spool"

    pauses = []

    def pause_then_fix(seconds):  # between tick 1 and tick 2 the missing file appears on the server
        pauses.append(seconds)
        if not (feed.site / missing).exists():
            (feed.site / missing).write_bytes(make_file(9))

    monkeypatch.setattr(run_cycle, "pause", pause_then_fix)
    rc = run_cycle.main(["--base", feed.base, "--spool", str(spool), "--workers", "4",
                         "--contact", CONTACT, "--min-free-gb", "0", "--interval", "0", "--ticks", "3"])
    assert rc == 0 and pauses == [0.0, 0.0]  # tick 1 pulled (gaps) BEFORE the file existed
    rec = json.loads(next(spool.glob("cycle_*/cycle.json")).read_text())
    assert rec["status"] == "complete" and rec["files_recorded"] == 4
    assert sum(1 for r in rec["files"] if r["status"] == "unchanged-304") == 3  # tick 2 resumed, not re-downloaded
    hb = json.loads((spool / "heartbeat.json").read_text())
    assert hb["tick"] == 3 and hb["cycles_complete"] == 1 and hb["action"] == "unchanged-304"


def test_an_interrupted_pull_stops_the_watcher(feed, tmp_path, monkeypatch):
    """poll.main() absorbs Ctrl-C/SIGTERM into exit 4; the watcher must exit on it rather than sleep
    into the next tick (systemd stop would otherwise SIGKILL it). Mutation: ignore rc -> red."""
    monkeypatch.setattr(poll, "main", lambda argv: poll.EXIT_INTERRUPTED)
    monkeypatch.setattr(run_cycle, "pause", lambda s: pytest.fail("watcher slept after an interrupt"))
    rc = run_cycle.main(["--base", feed.base, "--spool", str(tmp_path / "spool"), "--contact", CONTACT,
                         "--min-free-gb", "0", "--interval", "60", "--ticks", "5"])
    assert rc == poll.EXIT_INTERRUPTED
    hb = json.loads((tmp_path / "spool" / "heartbeat.json").read_text())
    assert hb["action"] == "pulled" and hb["last_exit"] == 4


def test_watcher_forwards_workers_and_min_free_gb(feed, tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(poll, "main", lambda argv: seen.setdefault("argv", argv) and 0)
    rc = run_cycle.main(["--base", feed.base, "--spool", str(tmp_path / "spool"), "--contact", CONTACT,
                         "--workers", "7", "--min-free-gb", "123.5", "--once"])
    assert rc == 0
    argv = seen["argv"]
    assert argv[argv.index("--workers") + 1] == "7" and argv[argv.index("--min-free-gb") + 1] == "123.5"
    assert argv[argv.index("--contact") + 1] == CONTACT


def test_heartbeat_pulses_during_a_long_pull(tmp_path):
    """During a pull the heartbeat must keep beating with action 'pulling', or a status page would
    call a healthy poller dead mid-cycle. Mutation: drop the pulse thread -> 'pulling' never appears."""
    import threading as _threading
    site, names = build_site(tmp_path, 6)
    f = Feed(site, names, delay=0.4)
    try:
        spool = tmp_path / "spool"
        seen: set = set()
        rc_box: list = []

        def go():
            rc_box.append(run_cycle.main(["--base", f.base, "--spool", str(spool), "--workers", "2",
                                          "--contact", CONTACT, "--min-free-gb", "0",
                                          "--once", "--pulse", "0.15"]))

        t = _threading.Thread(target=go)
        t.start()
        for _ in range(200):  # sample the heartbeat while the pull runs (~1.2 s)
            try:
                seen.add(json.loads((spool / "heartbeat.json").read_text())["action"])
            except (OSError, ValueError, KeyError):
                pass
            if not t.is_alive():
                break
            _threading.Event().wait(0.05)
        t.join()
        assert rc_box == [0]
        assert "pulling" in seen, f"no in-pull heartbeat observed; saw {seen}"
        hb = json.loads((spool / "heartbeat.json").read_text())
        assert hb["action"] == "pulled" and hb["last_exit"] == 0  # the final write wins
    finally:
        f.close()


def test_manifest_fetch_failure_is_a_heartbeat_error_not_a_crash(tmp_path):
    spool = tmp_path / "spool"
    rc = run_cycle.main(["--base", "http://127.0.0.1:9", "--spool", str(spool),
                         "--contact", CONTACT, "--min-free-gb", "0", "--once"])
    hb = json.loads((spool / "heartbeat.json").read_text())
    assert rc == -1 and hb["action"] == "error" and hb["cycles_complete"] == 0


def test_log_file_receives_both_watcher_and_poller_lines(feed, tmp_path):
    """Under pythonw there is no stderr; --log-file must carry both modules' logging. Mutation: drop
    the handlers= argument in configure_logging -> the file is never written, red."""
    spool = tmp_path / "spool"
    logfile = tmp_path / "logs" / "watch.log"
    root = logging.getLogger()
    saved = list(root.handlers)
    for h in saved:
        root.removeHandler(h)
    try:
        rc = run_cycle.main(["--base", feed.base, "--spool", str(spool), "--workers", "4",
                             "--contact", CONTACT, "--min-free-gb", "0", "--once", "--log-file", str(logfile)])
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
            h.close()
        for h in saved:
            root.addHandler(h)
    assert rc == 0
    text = logfile.read_text(encoding="utf-8")
    assert "tick 1: pulled" in text and "ephemera.poll" not in text  # format is asctime level message
    assert "done: complete 3/3 files" in text  # a poll.py line, through the same handler


def test_missing_contact_is_refused(feed, tmp_path, monkeypatch):
    monkeypatch.delenv("EPHEMERA_CONTACT", raising=False)
    rc = run_cycle.main(["--base", feed.base, "--spool", str(tmp_path / "spool"), "--once"])
    assert rc == 5 and feed.requests == []
