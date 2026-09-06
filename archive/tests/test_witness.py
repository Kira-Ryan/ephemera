"""Behavioural tests for archive/witness.py, driven through main() against a real spool (built by
poll.main over the fake feed) and a fake Wayback server. The OTS runner is stubbed - stamping is
exercised as an interface; the real client was proven in probes P2/P2b."""
from __future__ import annotations

import gzip
import hashlib
import http.server
import json
import socketserver
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import poll  # noqa: E402
import witness  # noqa: E402
from test_poll import CONTACT, Feed, build_site, make_file, run  # noqa: E402

TS = "20260831120000"


class FakeWayback:
    """Save-Page-Now double: /save/<url> 302-redirects to /web/<ts>/<url>; /web/<ts>id_/<url>
    serves the origin bytes gzip-compressed WITH Content-Encoding (requests then hands the caller
    decoded raw bytes - what the real id_ endpoint did in probe P2b), except for url suffixes in
    gzip_no_header, which get the gzip bytes with no header (a replay that lost the encoding
    header - the case witness's gunzip fallback exists for). corrupt: url suffixes whose id_ copy
    is wrong. limit_once: url suffixes that 429 one time."""

    def __init__(self, origin: dict[str, bytes], corrupt: set | None = None, limit_once: set | None = None,
                 gzip_no_header: set | None = None):
        self.origin, self.corrupt = origin, corrupt or set()
        self.gzip_no_header = gzip_no_header or set()
        self.limited = dict.fromkeys(limit_once or set(), 1)
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=b"", headers=()):
                self.send_response(code)
                for k, v in headers:
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.startswith("/save/"):
                    url = self.path[len("/save/"):]
                    for suffix, left in list(fake.limited.items()):
                        if url.endswith(suffix) and left > 0:
                            fake.limited[suffix] -= 1
                            self._send(429)
                            return
                    self._send(302, headers=[("Location", f"/web/{TS}/{url}")])
                elif self.path.startswith(f"/web/{TS}id_/"):
                    url = self.path[len(f"/web/{TS}id_/"):]
                    raw = fake.origin.get(url.split("?")[0])  # like the real origin: query ignored
                    if raw is None:
                        self._send(404)
                        return
                    if any(url.endswith(s) for s in fake.corrupt):
                        raw = b"corrupted " + raw[:100]
                    if any(url.endswith(s) for s in fake.gzip_no_header):
                        self._send(200, gzip.compress(raw))  # gzip payload, no encoding header
                    else:
                        self._send(200, gzip.compress(raw), [("Content-Encoding", "gzip")])
                elif self.path.startswith(f"/web/{TS}/"):
                    self._send(200, b"<html>captured</html>")
                else:
                    self._send(404)

        self.srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class StubOts:
    """Interface double for the OpenTimestamps runner. attest_after: upgrades before this many
    calls report a still-pending proof."""

    mode = "stub"

    def __init__(self, attest_after=1, fail_for: set | None = None):
        self.attest_after, self.fail_for = attest_after, fail_for or set()
        self.stamps, self.upgrades = [], []

    def stamp(self, cycle_dir: Path):
        if cycle_dir.name in self.fail_for:
            raise RuntimeError("stub: stamping refused for this cycle")
        # A real proof carries the SHA-256 of the file it stamps, and the verifier binds the proof
        # to the root through exactly that. A stub that omitted it would let a check that matters
        # pass on nothing, so it is included here.
        digest = hashlib.sha256((cycle_dir / "root.txt").read_bytes()).digest()
        (cycle_dir / "root.txt.ots").write_bytes(b"\x00OpenTimestamps stub\x01\x08" + digest)
        self.stamps.append(cycle_dir.name)

    def upgrade(self, cycle_dir: Path):
        self.upgrades.append(cycle_dir.name)

    def info(self, cycle_dir: Path) -> str:
        done = self.upgrades.count(cycle_dir.name) >= self.attest_after
        return "verify BitcoinBlockHeaderAttestation(964715)" if done else "PendingAttestation"


def build_cycle(tmp_path):
    """A real complete cycle in a spool, plus the origin byte map and a fake wayback for it."""
    site, names = build_site(tmp_path)
    feed = Feed(site, names)
    spool = tmp_path / "spool"
    rc, rec, cycle = run(feed, spool)
    assert rc == 0
    origin = {f"{feed.base}/MANIFEST.txt": (site / "MANIFEST.txt").read_bytes(),
              **{f"{feed.base}/{n}": (site / n).read_bytes() for n in names}}
    return feed, spool, rec, cycle, origin


def set_current(spool: Path, sha: str):
    poll.write_json_atomic(spool / "heartbeat.json", {"utc": poll.utc_now(), "manifest_sha256": sha})


def wmain(feed, spool, wb, *extra) -> int:
    return witness.main(["--spool", str(spool), "--base", feed.base, "--wayback", wb.base,
                         "--contact", CONTACT, "--samples", "3", "--capture-gap", "0", "--once", *extra])


@pytest.fixture(autouse=True)
def stub_runner(monkeypatch):
    stub = StubOts()
    monkeypatch.setattr(witness, "make_ots_runner", lambda mode: stub)
    yield stub


def test_sample_indices_follow_the_documented_chain_and_are_deterministic():
    """Mutation: pick indices any other way (random module, different separator) -> red."""
    root = "ab" * 32
    got = witness.sample_indices(root, 100, 10)
    expected, k = [], 0
    while len(expected) < 10:  # independent inline re-implementation of the documented sentence
        i = int(hashlib.sha256(f"{root}:{k}".encode()).hexdigest(), 16) % 100
        if i not in expected:
            expected.append(i)
        k += 1
    assert got == sorted(expected)
    assert witness.sample_indices(root, 100, 10) == got
    assert witness.sample_indices("cd" * 32, 100, 10) != got
    assert witness.sample_indices(root, 2, 10) == [0, 1]


def test_full_pass_stamps_and_verifies_manifest_plus_samples(tmp_path, stub_runner):
    """One sample arrives as gzip bytes without the encoding header, so this pins BOTH verification
    branches. Mutation: drop the gunzip fallback in verified_sha -> that sample mismatches, red."""
    feed, spool, rec, cycle, origin = build_cycle(tmp_path)
    wb = FakeWayback(origin, gzip_no_header={feed.names[2]})
    try:
        set_current(spool, rec["manifest_sha256"])
        assert wmain(feed, spool, wb) == 0
        w = json.loads((cycle / "witness.json").read_text())
        assert (cycle / "root.txt.ots").exists() and w["ots"]["runner"] == "stub"
        assert w["merkle_root"] == rec["merkle_root"]
        assert w["wayback"]["manifest"]["verified"] and w["wayback"]["manifest"]["timestamp"] == TS
        # each cycle's manifest gets its own capture URL (Wayback de-duplicates an unchanged URL)
        assert w["wayback"]["manifest"]["url"].endswith(f"/MANIFEST.txt?cycle={rec['manifest_sha256'][:12]}")
        assert sorted(map(int, w["wayback"]["samples"])) == witness.sample_indices(rec["merkle_root"], 3, 3)
        assert all(s["verified"] for s in w["wayback"]["samples"].values())
        assert {s["name"] for s in w["wayback"]["samples"].values()} == set(feed.names)
    finally:
        feed.close()
        wb.close()


def test_id_copy_mismatch_is_recorded_loudly(tmp_path):
    """The sceptic's check: sha256(gunzip(id_)) must equal the recorded hash. Mutation: skip the
    re-fetch or compare wire bytes -> this stays green/red the wrong way."""
    feed, spool, rec, cycle, origin = build_cycle(tmp_path)
    wb = FakeWayback(origin, corrupt={feed.names[1]})
    try:
        set_current(spool, rec["manifest_sha256"])
        assert wmain(feed, spool, wb) == 1
        w = json.loads((cycle / "witness.json").read_text())
        bad = [s for s in w["wayback"]["samples"].values() if s["name"] == feed.names[1]][0]
        assert bad["verified"] is False and "mismatch" in bad["error"]
    finally:
        feed.close()
        wb.close()


def test_superseded_cycle_is_stamped_but_wayback_records_the_loss(tmp_path):
    """Mutation: drop the is_current check and capture anyway -> the skip note never appears."""
    feed, spool, rec, cycle, origin = build_cycle(tmp_path)
    wb = FakeWayback(origin)
    try:
        set_current(spool, "0" * 64)  # the feed has moved on
        assert wmain(feed, spool, wb) == 1
        w = json.loads((cycle / "witness.json").read_text())
        assert (cycle / "root.txt.ots").exists()
        assert "superseded" in w["wayback"]["skipped"] and "3 sample captures never made" in w["wayback"]["skipped"]
        assert "manifest" not in w["wayback"]
    finally:
        feed.close()
        wb.close()


def test_upgrade_records_the_block_height_and_respects_the_backoff(tmp_path, stub_runner):
    feed, spool, rec, cycle, origin = build_cycle(tmp_path)
    wb = FakeWayback(origin)
    try:
        set_current(spool, rec["manifest_sha256"])
        stub_runner.attest_after = 2
        assert wmain(feed, spool, wb) == 0                      # pass 1: stamps only
        assert wmain(feed, spool, wb, "--upgrade-every", "0") == 0   # pass 2: upgrade -> still pending
        w = json.loads((cycle / "witness.json").read_text())
        assert not w["ots"].get("attested") and stub_runner.upgrades == [cycle.name]
        assert wmain(feed, spool, wb, "--upgrade-every", "1e6") == 0  # pass 3: backoff -> no attempt
        assert stub_runner.upgrades == [cycle.name]
        assert wmain(feed, spool, wb, "--upgrade-every", "0") == 0    # pass 4: attested
        w = json.loads((cycle / "witness.json").read_text())
        assert w["ots"]["attested"]["block_height"] == 964715
    finally:
        feed.close()
        wb.close()


def test_one_cycle_failing_does_not_block_the_next(tmp_path, stub_runner):
    feed, spool, rec1, cycle1, origin = build_cycle(tmp_path)
    (feed.site / "MEME_9_STARLINK-9_1_Operational_1_UNCLASSIFIED.txt").write_bytes(make_file(9))
    names2 = feed.names + ["MEME_9_STARLINK-9_1_Operational_1_UNCLASSIFIED.txt"]
    (feed.site / "MANIFEST.txt").write_text("\n".join(names2) + "\n")
    rc2 = poll.main(["--base", feed.base, "--spool", str(spool), "--workers", "4",
                     "--contact", CONTACT, "--min-free-gb", "0"])
    assert rc2 == 0
    cycle2 = [c for c in spool.glob("cycle_*") if c != cycle1][0]
    rec2 = json.loads((cycle2 / "cycle.json").read_text())
    origin.update({f"{feed.base}/MANIFEST.txt": (feed.site / "MANIFEST.txt").read_bytes(),
                   f"{feed.base}/{names2[-1]}": (feed.site / names2[-1]).read_bytes()})
    wb = FakeWayback(origin)
    try:
        set_current(spool, rec2["manifest_sha256"])
        stub_runner.fail_for = {cycle1.name}
        assert wmain(feed, spool, wb) == 1
        w1 = json.loads((cycle1 / "witness.json").read_text())
        w2 = json.loads((cycle2 / "witness.json").read_text())
        assert "stamping refused" in w1["ots"]["error"]
        assert w2["wayback"]["manifest"]["verified"] and (cycle2 / "root.txt.ots").exists()
    finally:
        feed.close()
        wb.close()


def test_rate_limit_is_recorded_and_retried_on_the_next_pass(tmp_path):
    feed, spool, rec, cycle, origin = build_cycle(tmp_path)
    wb = FakeWayback(origin, limit_once={feed.names[0]})
    try:
        set_current(spool, rec["manifest_sha256"])
        assert wmain(feed, spool, wb) == 1
        w = json.loads((cycle / "witness.json").read_text())
        hit = [s for s in w["wayback"]["samples"].values() if s["name"] == feed.names[0]][0]
        assert "429" in hit["error"]
        assert wmain(feed, spool, wb) == 0  # the limiter releases; only the missing capture retried
        w = json.loads((cycle / "witness.json").read_text())
        assert all(s["verified"] for s in w["wayback"]["samples"].values())
    finally:
        feed.close()
        wb.close()


def _second_cycle(feed, spool):
    """Add a file, change the manifest, pull again: a second complete cycle in the same spool."""
    extra = "MEME_9_STARLINK-9_1_Operational_1_UNCLASSIFIED.txt"
    (feed.site / extra).write_bytes(make_file(9))
    (feed.site / "MANIFEST.txt").write_text("\n".join(feed.names + [extra]) + "\n")
    rc = poll.main(["--base", feed.base, "--spool", str(spool), "--workers", "4",
                    "--contact", CONTACT, "--min-free-gb", "0"])
    assert rc == 0
    (feed.site / "MANIFEST.txt").write_bytes((feed.site / "MANIFEST.txt").read_bytes())  # unchanged from here
    return extra


def test_daily_root_is_built_over_first_seen_order_and_stamped(tmp_path, stub_runner):
    """D16. The two cycles' first_seen times are assigned in REVERSE of their directory-name order,
    so a mutation that sorts by name (or builds today's root early) goes red."""
    from datetime import datetime, timedelta, timezone
    feed, spool, rec1, cycle1, origin = build_cycle(tmp_path)
    _second_cycle(feed, spool)
    try:
        cycles = sorted(spool.glob("cycle_*"))  # name order
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        times = {cycles[0].name: f"{yesterday}T09:00:00Z", cycles[1].name: f"{yesterday}T01:00:00Z"}
        for c in cycles:  # later-named cycle gets the EARLIER first_seen
            r = json.loads((c / "cycle.json").read_text())
            r["first_seen_utc"] = times[c.name]
            (c / "cycle.json").write_text(json.dumps(r))
        current = json.loads((cycles[0] / "cycle.json").read_text())
        set_current(spool, "0" * 64)  # neither cycle is current: wayback records the loss, rc 1
        wb = FakeWayback(origin)
        try:
            assert wmain(feed, spool, wb) == 1
        finally:
            wb.close()
        ddir = spool / "daily" / yesterday
        d = json.loads((ddir / "daily.json").read_text())
        assert [c["cycle"] for c in d["cycles"]] == [cycles[1].name, cycles[0].name]  # first_seen order
        roots = {c.name: json.loads((c / "cycle.json").read_text())["merkle_root"] for c in cycles}
        left = bytes.fromhex(roots[cycles[1].name])
        right = bytes.fromhex(roots[cycles[0].name])
        expected = hashlib.sha256(left + right).hexdigest()  # independent two-leaf construction
        assert d["merkle_root"] == expected
        assert (ddir / "root.txt").read_bytes() == (expected + "\n").encode()
        assert (ddir / "root.txt.ots").exists() and yesterday in stub_runner.stamps
        assert d["gapped_cycles_excluded"] == 0
        assert not (spool / "daily" / datetime.now(timezone.utc).strftime("%Y-%m-%d")).exists()
    finally:
        feed.close()


def test_daily_root_is_never_rebuilt_upgrades_and_skips_today(tmp_path, stub_runner):
    """Also pins the today-guard: the second cycle keeps today's first_seen and must NOT get a
    daily root yet. Mutation: drop the date >= today check -> today's dir appears, red."""
    from datetime import datetime, timedelta, timezone
    feed, spool, rec, cycle, origin = build_cycle(tmp_path)
    extra = _second_cycle(feed, spool)
    origin.update({f"{feed.base}/MANIFEST.txt": (feed.site / "MANIFEST.txt").read_bytes(),
                   f"{feed.base}/{extra}": (feed.site / extra).read_bytes()})
    cycle2 = [c for c in spool.glob("cycle_*") if c != cycle][0]
    rec2 = json.loads((cycle2 / "cycle.json").read_text())
    try:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        r = json.loads((cycle / "cycle.json").read_text())
        r["first_seen_utc"] = f"{yesterday}T03:00:00Z"
        (cycle / "cycle.json").write_text(json.dumps(r))
        set_current(spool, rec2["manifest_sha256"])
        wb = FakeWayback(origin)
        try:
            # pass 1 returns 1: cycle 1 was superseded before witnessing and the loss is recorded
            # once; later passes are clean because the recorded skip is not a new error
            assert wmain(feed, spool, wb) == 1
            first = (spool / "daily" / yesterday / "root.txt").read_bytes()
            assert wmain(feed, spool, wb, "--upgrade-every", "0") == 0
            assert wmain(feed, spool, wb, "--upgrade-every", "0") == 0
        finally:
            wb.close()
        assert (spool / "daily" / yesterday / "root.txt").read_bytes() == first
        assert stub_runner.stamps.count(yesterday) == 1
        d = json.loads((spool / "daily" / yesterday / "daily.json").read_text())
        assert d["ots"]["attested"]["block_height"] == 964715
        assert [c["cycle"] for c in d["cycles"]] == [cycle.name]
        assert first == (r["merkle_root"] + "\n").encode()  # one leaf: the daily root IS the cycle root
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert not (spool / "daily" / today).exists()  # today's root is never built early
    finally:
        feed.close()


def test_impossible_capture_gives_up_after_the_cap_and_goes_quiet(tmp_path):
    """One file's id_ copy 404s on every attempt (Wayback throttling repeat captures of one URL is
    the real-world case, measured 31 Aug). The loss must be recorded loudly while attempts remain,
    then once at give-up, and never re-flag later passes. Mutation: drop the gave_up exclusion from
    pending(), or stop counting attempts -> pass 3 keeps failing, red."""
    feed, spool, rec, cycle, origin = build_cycle(tmp_path)
    del origin[f"{feed.base}/{feed.names[0]}"]  # its id_ fetch will 404 forever
    wb = FakeWayback(origin)
    try:
        set_current(spool, rec["manifest_sha256"])
        assert wmain(feed, spool, wb, "--max-capture-attempts", "2") == 1  # attempt 1: error
        assert wmain(feed, spool, wb, "--max-capture-attempts", "2") == 1  # attempt 2: gives up
        assert wmain(feed, spool, wb, "--max-capture-attempts", "2") == 0  # quiet: loss recorded
        w = json.loads((cycle / "witness.json").read_text())
        lost = [s for s in w["wayback"]["samples"].values() if s["name"] == feed.names[0]][0]
        assert lost["attempts"] == 2 and lost.get("gave_up") and not lost.get("verified")
        others = [s for s in w["wayback"]["samples"].values() if s["name"] != feed.names[0]]
        assert others and all(s["verified"] for s in others)
    finally:
        feed.close()
        wb.close()


def test_missing_contact_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("EPHEMERA_CONTACT", raising=False)
    assert witness.main(["--spool", str(tmp_path / "spool"), "--once"]) == 5


# --------------------------------------------------------------- audit follow-on, 6 Sep 2026


def test_a_cycle_whose_root_changed_after_stamping_is_stamped_again(tmp_path, stub_runner):
    """The witness stamped only when no proof file existed, so a root that changed after stamping
    kept the old proof, the old attestation and the samples chosen by the old root. The verifier
    now fails that state; this is the half that repairs it.

    Mutation: stamp only when root.txt.ots is absent and this goes red."""
    feed, spool, rec, cycle, origin = build_cycle(tmp_path)
    wb = FakeWayback(origin)
    try:
        set_current(spool, rec["manifest_sha256"])
        assert wmain(feed, spool, wb) == 0
        assert wmain(feed, spool, wb) == 0                      # attested by the stub on the upgrade
        w = json.loads((cycle / "witness.json").read_text())
        assert w["ots"]["attested"] and w["merkle_root"] == rec["merkle_root"]
        old_proof = (cycle / "root.txt.ots").read_bytes()

        new_root = "ab" * 32
        r = json.loads((cycle / "cycle.json").read_text())
        r["merkle_root"] = new_root
        (cycle / "cycle.json").write_text(json.dumps(r))
        (cycle / "root.txt").write_bytes((new_root + "\n").encode())

        assert wmain(feed, spool, wb) == 0
        w = json.loads((cycle / "witness.json").read_text())
        proof = (cycle / "root.txt.ots").read_bytes()
        assert proof != old_proof, "the old proof was kept for a root it does not prove"
        assert hashlib.sha256((new_root + "\n").encode()).digest() in proof
        assert w["merkle_root"] == new_root, "witness.json still names the old root"
        assert not w["ots"].get("attested"), "an attestation of the old root was carried over"
        assert stub_runner.stamps.count(cycle.name) == 2
        kept = list(cycle.glob("root.txt.ots.stale-*"))
        assert len(kept) == 1 and kept[0].read_bytes() == old_proof, "the superseded proof was not kept"
        # the samples are chosen by the root, so they are chosen again
        assert sorted(map(int, w["wayback"]["samples"])) == witness.sample_indices(new_root, 3, 3)
    finally:
        feed.close()
        wb.close()
