"""Behavioural tests for archive/poll.py against a local HTTP server.

Each test serves a tiny fake feed from a temporary directory and drives poll.main() as the real
entry point (not the helpers), so a regression in the wiring - not just in a helper - fails here.
Where a test exists to pin one specific line of poll.py, its docstring names the mutation that
turns it red.
"""
from __future__ import annotations

import _thread
import gzip
import hashlib
import http.server
import json
import socketserver
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import poll  # noqa: E402

CONTACT = "test@example.invalid"


def make_file(n: int) -> bytes:
    """A body that passes the poller's sanity check: starts with 'created:' and exceeds 1000 bytes."""
    head = (f"created:2026-08-30 00:00:{n:02d} UTC\n"
            "ephemeris_start:2026-08-30 00:00:00 UTC ephemeris_stop:2026-09-02 00:00:00 UTC step_size:60\n"
            "ephemeris_source:blend\nUVW\n")
    body = "".join(f"2026242000000.000 {n}.0 {i}.0 0.0 0.0 0.0 0.0\n" for i in range(60))
    return (head + body).encode()


class Feed:
    """A fake feed. etag: send ETags and honour If-None-Match. honour_ims: let the stdlib answer
    If-Modified-Since (a plain server does; set False so only If-None-Match can yield 304).
    delay: seconds to sleep per file GET. manifests: successive bodies for MANIFEST.txt (the
    k-th GET gets manifests[min(k, last)]); None serves the file on disk."""

    def __init__(self, site: Path, names: list[str], *, etag=True, honour_ims=True, delay=0.0, delays=None,
                 manifests=None, no_validators=False, bogus_304=False):
        """delays: per-file-name seconds (overrides delay). no_validators: send neither ETag nor
        Last-Modified. bogus_304: answer 304 to a repeat GET that carries no validator at all (a
        protocol violation the poller must not trust)."""
        self.site, self.names = site, names
        self.requests: list[str] = []
        self.manifest_gets = 0
        served: set[str] = set()
        feed = self

        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                feed.requests.append(self.path)
                if self.path.endswith("/MANIFEST.txt") and manifests is not None:
                    body = manifests[min(feed.manifest_gets, len(manifests) - 1)]
                    feed.manifest_gets += 1
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if not self.path.endswith("/MANIFEST.txt"):
                    d = (delays or {}).get(self.path.rsplit("/", 1)[-1], delay)
                    if d:
                        time.sleep(d)
                    has_validator = self.headers.get("If-None-Match") or self.headers.get("If-Modified-Since")
                    if bogus_304 and self.path in served and not has_validator:
                        self.send_response(304)
                        self.end_headers()
                        return
                    served.add(self.path)
                super().do_GET()

            def send_header(self, keyword, value):
                if no_validators and keyword.lower() in ("etag", "last-modified"):
                    return
                super().send_header(keyword, value)

            def send_head(self):
                path = Path(self.translate_path(self.path))
                if not honour_ims:
                    del self.headers["If-Modified-Since"]
                if etag and path.is_file():
                    tag = '"%s"' % hashlib.sha256(path.read_bytes()).hexdigest()[:32]
                    if self.headers.get("If-None-Match") == tag:
                        self.send_response(304)
                        self.send_header("ETag", tag)
                        self.end_headers()
                        return None
                    self._etag = tag
                return super().send_head()

            def end_headers(self):
                tag = getattr(self, "_etag", None)
                if tag:
                    self.send_header("ETag", tag)
                    self._etag = None
                super().end_headers()

        handler = lambda *a, **k: Handler(*a, directory=str(site), **k)  # noqa: E731
        self.srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def file_gets(self) -> int:
        return sum(1 for p in self.requests if not p.endswith("/MANIFEST.txt"))

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def build_site(tmp_path: Path, count: int = 3) -> tuple[Path, list[str]]:
    site = tmp_path / "site"
    site.mkdir()
    names = [f"MEME_{i}_STARLINK-{i}_1_Operational_1_UNCLASSIFIED.txt" for i in range(1, count + 1)]
    for i, n in enumerate(names, 1):
        (site / n).write_bytes(make_file(i))
    (site / "MANIFEST.txt").write_text("\n".join(names) + "\n")
    return site, names


@pytest.fixture
def feed(tmp_path):
    site, names = build_site(tmp_path)
    f = Feed(site, names)
    try:
        yield f
    finally:
        f.close()


def run(feed: Feed, spool: Path, *extra: str, partial: bool = False) -> tuple[int, dict, Path]:
    argv = ["--base", feed.base, "--spool", str(spool), "--workers", "4",
            "--contact", CONTACT, "--min-free-gb", "0", *extra]
    rc = poll.main(argv)
    where = spool / "partial" if partial else spool
    cycles = sorted(where.glob("cycle_*"))
    assert len(cycles) == 1, cycles
    return rc, json.loads((cycles[0] / "cycle.json").read_text()), cycles[0]


def expected_root(site: Path, names: list[str]) -> str:
    return poll.merkle_root([hashlib.sha256((site / n).read_bytes()).hexdigest() for n in names])


def manifest_sha(site: Path) -> str:
    return hashlib.sha256((site / "MANIFEST.txt").read_bytes()).hexdigest()


def test_complete_cycle_writes_root_and_gzipped_files(feed, tmp_path):
    rc, rec, cycle = run(feed, tmp_path / "spool")
    assert rc == 0 and rec["status"] == "complete"
    assert rec["files_listed"] == rec["files_recorded"] == 3 and rec["files_failed"] == 0
    assert rec["merkle_root"] == expected_root(feed.site, feed.names)
    assert rec["partial"] is None and rec["manifest_changed_during_pull"] is None
    for r in rec["files"]:
        raw = gzip.open(cycle / "files" / (r["name"] + ".gz"), "rb").read()
        assert hashlib.sha256(raw).hexdigest() == r["sha256"] and len(raw) == r["bytes"]
    assert (cycle / "MANIFEST.txt").read_bytes() == (feed.site / "MANIFEST.txt").read_bytes()
    assert CONTACT in rec["poller"]


def test_root_txt_is_exactly_64_lowercase_hex_plus_lf(feed, tmp_path):
    """D12. Mutation: write_bytes -> write_text(root + '\\n') produces CRLF on Windows and fails here."""
    rc, rec, cycle = run(feed, tmp_path / "spool")
    b = (cycle / "root.txt").read_bytes()
    assert len(b) == 65 and b[-1:] == b"\n" and b[:-1].decode("ascii") == rec["merkle_root"]
    assert b"\r" not in b and set(b[:-1]) <= set(b"0123456789abcdef")


def test_cycle_identity_is_manifest_sha_not_wall_clock(feed, tmp_path, monkeypatch):
    """D10/D11. Mutation: put started[:10] back into the directory name -> two dirs, red."""
    spool = tmp_path / "spool"
    monkeypatch.setattr(poll, "utc_now", lambda: "2026-08-30T23:59:00Z")
    rc1, rec1, cycle1 = run(feed, spool)
    monkeypatch.setattr(poll, "utc_now", lambda: "2026-08-31T00:01:00Z")
    rc2, rec2, cycle2 = run(feed, spool)
    assert rc1 == rc2 == 0 and cycle1 == cycle2
    assert cycle1.name == f"cycle_{manifest_sha(feed.site)[:12]}" == rec2["cycle"]
    assert rec2["first_seen_utc"] == "2026-08-30T23:59:00Z" and rec2["started_utc"] == "2026-08-31T00:01:00Z"
    assert {r["status"] for r in rec2["files"]} == {"unchanged-304"}


def test_rerun_resumes_with_304_and_same_root(feed, tmp_path):
    spool = tmp_path / "spool"
    rc1, rec1, _ = run(feed, spool)
    before = feed.file_gets()
    rc2, rec2, _ = run(feed, spool)
    assert rc1 == rc2 == 0
    assert rec2["merkle_root"] == rec1["merkle_root"]
    assert {r["status"] for r in rec2["files"]} == {"unchanged-304"}
    assert feed.file_gets() == before + 3  # one conditional GET per file, no re-download


def test_resume_requires_if_none_match_when_server_ignores_if_modified_since(tmp_path):
    """Pins the ETag path. The server strips If-Modified-Since, so a 304 can only come from
    If-None-Match. Mutation: delete the If-None-Match header line (or record etag as None) in
    poll.fetch_one -> second run re-downloads everything, statuses are 'fetched', red."""
    site, names = build_site(tmp_path)
    f = Feed(site, names, etag=True, honour_ims=False)
    try:
        spool = tmp_path / "spool"
        rc1, rec1, _ = run(f, spool)
        assert rc1 == 0 and all(r["etag"] for r in rec1["files"])
        rc2, rec2, _ = run(f, spool)
        assert rc2 == 0 and {r["status"] for r in rec2["files"]} == {"unchanged-304"}
        assert rec2["merkle_root"] == rec1["merkle_root"]
    finally:
        f.close()


def test_rerun_resumes_via_if_modified_since_when_server_has_no_etag(tmp_path):
    """Fallback path: a plain server sends Last-Modified but no ETag."""
    site, names = build_site(tmp_path, 2)
    f = Feed(site, names, etag=False, honour_ims=True)
    try:
        spool = tmp_path / "spool"
        rc1, rec1, _ = run(f, spool)
        assert rc1 == 0 and all(r["etag"] is None and r["last_modified"] for r in rec1["files"])
        rc2, rec2, _ = run(f, spool)
        assert rc2 == 0 and {r["status"] for r in rec2["files"]} == {"unchanged-304"}
        assert rec2["merkle_root"] == rec1["merkle_root"]
    finally:
        f.close()


def test_missing_file_is_a_loud_gap_with_no_root(feed, tmp_path, monkeypatch):
    (feed.site / "MANIFEST.txt").write_text("\n".join(feed.names + ["MEME_0_MISSING_0_Operational_0_UNCLASSIFIED.txt"]) + "\n")
    monkeypatch.setattr(poll, "BACKOFF_S", 0.0)  # do not sleep through retries in a test
    rc, rec, cycle = run(feed, tmp_path / "spool")
    assert rc == 2 and rec["status"] == "gaps"
    assert rec["files_listed"] == 4 and rec["files_recorded"] == 3 and rec["files_failed"] == 1
    assert rec["merkle_root"] is None and not (cycle / "root.txt").exists()
    assert list(rec["failures"]) == ["MEME_0_MISSING_0_Operational_0_UNCLASSIFIED.txt"]
    assert "404" in next(iter(rec["failures"].values()))


def test_body_sanity_check_rejects_a_non_ephemeris(feed, tmp_path, monkeypatch):
    (feed.site / feed.names[0]).write_bytes(b"<html>rate limited</html>")
    monkeypatch.setattr(poll, "BACKOFF_S", 0.0)
    rc, rec, _ = run(feed, tmp_path / "spool")
    assert rc == 2 and rec["files_failed"] == 1
    assert "unexpected body" in next(iter(rec["failures"].values()))


def test_unsafe_and_duplicate_manifest_names_are_gaps_not_paths(feed, tmp_path, monkeypatch):
    """Anomalies are counted per manifest line, never collide with recorded files, and never touch
    the filesystem. Mutation: drop name_problem() or the duplicate check -> '../escaped.txt.gz'
    lands outside files/; key anomalies by name -> the counts stop summing to files_listed."""
    a, b, c = feed.names
    listed = [a, "../escaped.txt", "sub/dir.txt", b, b, b, c + "#frag", c, "x y.txt"]
    (feed.site / "MANIFEST.txt").write_text("\n".join(listed) + "\n")
    monkeypatch.setattr(poll, "BACKOFF_S", 0.0)
    rc, rec, cycle = run(feed, tmp_path / "spool")
    assert rc == 2 and rec["status"] == "gaps" and rec["merkle_root"] is None
    assert rec["files_listed"] == 9 and rec["files_recorded"] == 3
    assert rec["failures"] == {}  # download failures only; anomalies live in their own list
    assert [(x["line"], x["entry"], x["reason"]) for x in rec["manifest_anomalies"]] == [
        (2, "../escaped.txt", "path separator"),
        (3, "sub/dir.txt", "path separator"),
        (5, b, "duplicate manifest entry"),
        (6, b, "duplicate manifest entry"),
        (7, c + "#frag", "character outside [A-Za-z0-9._-]"),
        (9, "x y.txt", "character outside [A-Za-z0-9._-]"),
    ]
    assert rec["files_failed"] == 6 and rec["files_not_attempted"] == 0
    assert rec["files_recorded"] + rec["files_failed"] + rec["files_not_attempted"] == rec["files_listed"]
    assert {r["name"] for r in rec["files"]} == {a, b, c}
    stray = [p for p in tmp_path.rglob("*") if "escaped" in p.name or p.name in ("dir.txt.gz", "x y.txt.gz")]
    assert stray == []
    assert sorted(p.name for p in (cycle / "files").iterdir()) == sorted(n + ".gz" for n in feed.names)


def test_case_insensitive_duplicate_is_an_anomaly(feed, tmp_path, monkeypatch):
    """Two names differing only in case would overwrite each other under files/ on NTFS/APFS while
    the root committed to both. Mutation: compare names case-sensitively -> 'complete' with one file."""
    twin = feed.names[0].lower()
    (feed.site / twin).write_bytes(make_file(7))
    (feed.site / "MANIFEST.txt").write_text("\n".join(feed.names + [twin]) + "\n")
    monkeypatch.setattr(poll, "BACKOFF_S", 0.0)
    rc, rec, cycle = run(feed, tmp_path / "spool")
    assert rc == 2 and rec["merkle_root"] is None
    assert [x["reason"] for x in rec["manifest_anomalies"]] == ["duplicate manifest entry (case-insensitive)"]
    assert rec["files_recorded"] == 3 and rec["files_failed"] == 1


def test_bom_is_stripped_and_bare_control_separators_are_not_line_breaks(feed, tmp_path, monkeypatch):
    """A UTF-8 BOM must not become part of the first name; a bare CR/FS inside a line must reach
    name_problem() as a control character rather than splitting the line into two 'files'."""
    a, b, c = feed.names
    (feed.site / "MANIFEST.txt").write_bytes(("﻿" + a + "\n" + b + "\x1c" + "GHOST.txt" + "\n" + c + "\n").encode("utf-8"))
    monkeypatch.setattr(poll, "BACKOFF_S", 0.0)
    rc, rec, cycle = run(feed, tmp_path / "spool")
    assert rc == 2 and rec["files_listed"] == 3 and rec["files_recorded"] == 2
    assert rec["manifest_anomalies"][0]["line"] == 2 and "control" in rec["manifest_anomalies"][0]["reason"]
    assert {r["name"] for r in rec["files"]} == {a, c}
    assert not any("GHOST" in p.name for p in tmp_path.rglob("*"))


def test_merkle_leaves_follow_manifest_order_not_completion_order(tmp_path):
    """D09. The first listed file finishes last. Mutation: build `ordered` from records in completion
    order -> root differs from the manifest-order expectation, red every time."""
    site, names = build_site(tmp_path)
    f = Feed(site, names, delays={names[0]: 0.6})
    try:
        rc, rec, _ = run(f, tmp_path / "spool")
        assert rc == 0 and rec["merkle_root"] == expected_root(site, names)
        assert [r["name"] for r in rec["files"]] == names
        assert rec["files"][0]["fetched_utc"] >= rec["files"][2]["fetched_utc"]
    finally:
        f.close()


def test_stale_root_is_removed_when_a_rerun_ends_in_gaps(feed, tmp_path, monkeypatch):
    """Mutation: never unlink root.txt -> cycle.json says gaps while root.txt still exists."""
    spool = tmp_path / "spool"
    rc1, _, cycle = run(feed, spool)
    assert rc1 == 0 and (cycle / "root.txt").exists()
    (feed.site / feed.names[1]).unlink()  # same manifest, one file now 404s: the resume must end in gaps
    monkeypatch.setattr(poll, "BACKOFF_S", 0.0)
    rc2, rec2, cycle2 = run(feed, spool)
    assert cycle2 == cycle and rc2 == 2 and rec2["status"] == "gaps" and rec2["merkle_root"] is None
    assert not (cycle / "root.txt").exists()


def test_oserror_in_the_download_loop_stops_the_pool_and_marks_the_record(tmp_path, monkeypatch):
    """An OSError from the cache flush must not leave sixteen workers downloading with nobody
    collecting. Mutation: catch only KeyboardInterrupt around the loop -> all 12 files are fetched
    after main() raised, and cycle.json stays 'in-progress'."""
    site, names = build_site(tmp_path, 12)
    f = Feed(site, names, delay=0.3)
    real = poll.write_json_atomic

    def flaky(path, obj):
        if path.name == "etag_cache.json":
            raise OSError(28, "No space left on device")
        real(path, obj)

    monkeypatch.setattr(poll, "write_json_atomic", flaky)
    monkeypatch.setattr(poll, "FLUSH_EVERY", 1)
    try:
        spool = tmp_path / "spool"
        with pytest.raises(OSError):
            poll.main(["--base", f.base, "--spool", str(spool), "--workers", "2",
                       "--contact", CONTACT, "--min-free-gb", "0"])
        gets_at_raise = f.file_gets()
        time.sleep(1.5)
        assert f.file_gets() == gets_at_raise <= 4  # nothing new after main() raised
        rec = json.loads(next(spool.glob("cycle_*/cycle.json")).read_text())
        assert rec["status"] == "error" and "No space left" in rec["error"]
        assert rec["merkle_root"] is None
    finally:
        f.close()


def test_manifest_fetch_failure_exits_5_with_no_cycle_dir(tmp_path):
    spool = tmp_path / "spool"
    rc = poll.main(["--base", "http://127.0.0.1:9", "--spool", str(spool), "--contact", CONTACT, "--min-free-gb", "0"])
    assert rc == 5 and not list(spool.glob("**/cycle_*"))


def test_304_without_a_validator_sent_is_not_trusted(tmp_path, monkeypatch):
    """A server that answers 304 to an unconditional GET is broken; the poller must record a gap,
    not mark the file unchanged. Mutation: accept any 304 when the file exists -> rc 0."""
    site, names = build_site(tmp_path)
    f = Feed(site, names, etag=False, no_validators=True, bogus_304=True)
    monkeypatch.setattr(poll, "BACKOFF_S", 0.0)
    try:
        spool = tmp_path / "spool"
        rc1, rec1, _ = run(f, spool)
        assert rc1 == 0 and all(r["etag"] is None and r["last_modified"] is None for r in rec1["files"])
        rc2, rec2, _ = run(f, spool)
        assert rc2 == 2 and rec2["files_failed"] == 3 and rec2["merkle_root"] is None
    finally:
        f.close()


def test_limit_slice_is_partial_with_no_root_under_partial_dir(feed, tmp_path):
    """D09/D13. Mutation: compute the root over the slice (the original defect) -> root.txt appears, red."""
    spool = tmp_path / "spool"
    rc, rec, cycle = run(feed, spool, "--limit", "2", partial=True)
    assert rc == 3 and rec["status"] == "partial" and rec["partial"] == {"limit": 2}
    assert rec["files_listed"] == 3 and rec["files_recorded"] == 2 and rec["files_not_attempted"] == 1
    assert rec["merkle_root"] is None and not (cycle / "root.txt").exists()
    assert cycle.parent == spool / "partial" and not list(spool.glob("cycle_*"))
    # a real run afterwards is unaffected by the slice
    rc2, rec2, cycle2 = run(feed, spool)
    assert rc2 == 0 and cycle2.parent == spool and (cycle2 / "root.txt").exists()


def test_empty_manifest_is_refused_with_no_cycle_dir(feed, tmp_path):
    """Mutation: delete the empty-manifest guard -> an exit-0 cycle with zero files, red."""
    (feed.site / "MANIFEST.txt").write_text("\n")
    spool = tmp_path / "spool"
    rc = poll.main(["--base", feed.base, "--spool", str(spool), "--contact", CONTACT, "--min-free-gb", "0"])
    assert rc == 5 and not list(spool.glob("**/cycle_*"))


def test_missing_contact_is_refused_before_any_request(feed, tmp_path, monkeypatch):
    monkeypatch.delenv("EPHEMERA_CONTACT", raising=False)
    rc = poll.main(["--base", feed.base, "--spool", str(tmp_path / "spool"), "--min-free-gb", "0"])
    assert rc == 5 and feed.requests == []


def test_disk_floor_refuses_before_any_request(feed, tmp_path):
    rc = poll.main(["--base", feed.base, "--spool", str(tmp_path / "spool"), "--contact", CONTACT,
                    "--min-free-gb", "1e9"])
    assert rc == 5 and feed.requests == [] and not list((tmp_path / "spool").glob("cycle_*"))


def test_manifest_change_during_pull_is_recorded_and_root_still_written(tmp_path):
    """D09: a pull that recorded every listed file is complete even if the manifest rolled after.
    Mutation: drop the end-of-pull re-fetch -> manifest_changed_during_pull stays null, red."""
    site, names = build_site(tmp_path)
    v1 = (site / "MANIFEST.txt").read_bytes()
    v2 = v1 + b"MEME_9_STARLINK-9_1_Operational_1_UNCLASSIFIED.txt\n"
    f = Feed(site, names, manifests=[v1, v2])
    try:
        rc, rec, cycle = run(f, tmp_path / "spool")
        assert rc == 0 and rec["status"] == "complete" and (cycle / "root.txt").exists()
        assert rec["manifest_changed_during_pull"]["end_sha256"] == hashlib.sha256(v2).hexdigest()
        assert rec["manifest_sha256"] == hashlib.sha256(v1).hexdigest()
        # the re-fetch must come AFTER every file download, or a mid-pull rollover is never seen
        manifest_gets = [i for i, p in enumerate(f.requests) if p.endswith("/MANIFEST.txt")]
        assert manifest_gets == [0, len(f.requests) - 1] and len(f.requests) == 5
    finally:
        f.close()


def test_interrupt_writes_record_and_cache_without_root(tmp_path):
    """Ctrl-C mid-cycle: the record says 'interrupted', lists what was recorded, the ETag cache is on
    disk for the resume, and no root exists. Mutation: remove the KeyboardInterrupt handler -> the
    exception escapes main() and this test errors; remove flush_cache() -> etag_cache.json missing."""
    # 12 files, 2 workers, 0.5 s each: the interrupt (fired at 0.7 s) is seen by the main thread
    # when the second pair completes at ~1.0 s; whichever of the main thread or the workers wins the
    # race for the next pair, at least six files are still queued and get cancelled.
    site, names = build_site(tmp_path, 12)
    f = Feed(site, names, delay=0.5)
    try:
        spool = tmp_path / "spool"
        timer = threading.Timer(0.7, _thread.interrupt_main)
        timer.start()
        rc = poll.main(["--base", f.base, "--spool", str(spool), "--workers", "2",
                        "--contact", CONTACT, "--min-free-gb", "0"])
        timer.cancel()
        assert rc == 4
        cycles = list(spool.glob("cycle_*"))
        assert len(cycles) == 1
        rec = json.loads((cycles[0] / "cycle.json").read_text())
        assert rec["status"] == "interrupted" and rec["merkle_root"] is None
        assert not (cycles[0] / "root.txt").exists()
        assert 1 <= rec["files_recorded"] < 12 and rec["files_not_attempted"] >= 1
        assert rec["files_recorded"] + rec["files_failed"] + rec["files_not_attempted"] == 12
        cache = json.loads((cycles[0] / "etag_cache.json").read_text())
        assert set(cache) == {r["name"] for r in rec["files"]}
        # the resume completes the cycle with 304s for what was already stored
        rc2, rec2, cycle2 = run(f, spool)
        assert rc2 == 0 and cycle2 == cycles[0] and rec2["status"] == "complete"
        assert sum(1 for r in rec2["files"] if r["status"] == "unchanged-304") == rec["files_recorded"]
    finally:
        f.close()


def test_merkle_construction_is_the_documented_one():
    a, b, c = (hashlib.sha256(x).hexdigest() for x in (b"a", b"b", b"c"))
    h = lambda x, y: hashlib.sha256(bytes.fromhex(x) + bytes.fromhex(y)).hexdigest()  # noqa: E731
    assert poll.merkle_root([a]) == a
    assert poll.merkle_root([a, b]) == h(a, b)
    assert poll.merkle_root([a, b, c]) == h(h(a, b), h(c, c))  # odd trailing node paired with itself
    assert poll.merkle_root([]) is None


def test_a_304_does_not_trust_a_corrupted_local_file(tmp_path):
    """A resumed pull answers 304 for files it already has. The stored gzip was accepted because it
    existed, without ever being read, so local corruption became archive content and the shipper
    then verified only the upload's own size.

    Mutation: return the cached record on 304 without re-reading the file and this goes red."""
    site, names = build_site(tmp_path)
    feed = Feed(site, names)
    spool = tmp_path / "spool"
    try:
        rc, rec, cyc = run(feed, spool)
        assert rc == 0
        victim = rec["files"][0]
        gz = cyc / "files" / (victim["name"] + ".gz")
        gz.write_bytes(gzip.compress(b"created: not the bytes that were fetched\n" + b"q" * 3000))

        rc2 = poll.main(["--base", feed.base, "--spool", str(spool), "--workers", "4",
                         "--contact", CONTACT, "--min-free-gb", "0"])
        assert rc2 == 0
        again = json.loads((cyc / "cycle.json").read_text())
        restored = gzip.decompress(gz.read_bytes())
        assert hashlib.sha256(restored).hexdigest() == victim["sha256"], \
            "the corrupted file was left in place and reported as unchanged"
        entry = next(f for f in again["files"] if f["name"] == victim["name"])
        assert entry["sha256"] == victim["sha256"]
        assert entry.get("status") != "unchanged-304", "corruption was reported as unchanged"
    finally:
        feed.close()
