"""Behavioural tests for archive/gp_pull.py against a fake Space-Track: login, one query, a
gzipped snapshot whose raw bytes hash to the record, dedup of an unchanged catalogue, and loud
failure on bad credentials, non-JSON or empty results."""
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
import gp_pull  # noqa: E402
from test_poll import CONTACT  # noqa: E402

ROWS = [{"NORAD_CAT_ID": str(n), "OBJECT_NAME": f"STARLINK-{n}", "EPOCH": f"2026-09-02T0{i}:00:00"}
        for i, n in enumerate((44713, 48125, 100224, 100300))]


class FakeSpaceTrack:
    def __init__(self, body: bytes | None = None, good_pw: str = "pw"):
        self.body = json.dumps(ROWS).encode() if body is None else body
        self.good_pw, self.logins, self.queries = good_pw, 0, 0
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body=b""):
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                form = self.rfile.read(n).decode()
                fake.logins += 1
                if self.path == "/ajaxauth/login" and f"password={fake.good_pw}" in form:
                    self._send(200, b'""')
                else:
                    self._send(200, b'{"Login":"Failed"}')

            def do_GET(self):
                fake.queries += 1
                if self.path.startswith("/basicspacedata/query/class/gp/"):
                    self._send(200, fake.body)
                else:
                    self._send(404)

        self.srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setenv("SPACETRACK_USER", "u@example.invalid")
    monkeypatch.setenv("SPACETRACK_PASS", "pw")


def gmain(spool: Path, base: str, *extra) -> int:
    return gp_pull.main(["--spool", str(spool), "--base", base, "--contact", CONTACT, "--once", *extra])


def test_snapshot_is_recorded_hashed_and_deduplicated(tmp_path):
    st = FakeSpaceTrack()
    try:
        spool = tmp_path / "spool"
        assert gmain(spool, st.base) == 0
        snaps = sorted((spool / "gp").glob("*"))
        assert len(snaps) == 1
        rec = json.loads((snaps[0] / "record.json").read_text())
        raw = gzip.open(snaps[0] / "gp.json.gz", "rb").read()
        assert hashlib.sha256(raw).hexdigest() == rec["sha256"] and len(raw) == rec["bytes"]
        assert snaps[0].name.endswith(rec["sha256"][:12])
        assert rec["records"] == 4 and rec["six_digit_ids"] == 2
        assert rec["epoch_min"].startswith("2026-09-02T00") and rec["epoch_max"].startswith("2026-09-02T03")
        assert "blanket approval" in rec["note"]
        assert st.logins == 1 and st.queries == 1                  # one login, one query per pass
        assert gmain(spool, st.base) == 0                          # unchanged catalogue: nothing new stored
        assert len(list((spool / "gp").glob("*"))) == 1
        st.body = json.dumps(ROWS + [{"NORAD_CAT_ID": "100400", "OBJECT_NAME": "STARLINK-X", "EPOCH": "2026-09-02T05:00:00"}]).encode()
        assert gmain(spool, st.base) == 0
        assert len(list((spool / "gp").glob("*"))) == 2
    finally:
        st.close()


def test_bad_credentials_are_loud_and_store_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("SPACETRACK_PASS", "wrong")
    st = FakeSpaceTrack()
    try:
        spool = tmp_path / "spool"
        assert gmain(spool, st.base) == 1
        assert not list((spool / "gp").glob("*")) and st.queries == 0
    finally:
        st.close()


@pytest.mark.parametrize("body", [b"<html>maintenance</html>", b"[]", b'[{"OBJECT_NAME": "x"}]'])
def test_bad_bodies_are_refused(tmp_path, body):
    st = FakeSpaceTrack(body=body)
    try:
        spool = tmp_path / "spool"
        assert gmain(spool, st.base) == 1
        assert not list((spool / "gp").glob("*"))
    finally:
        st.close()


def test_missing_contact_is_refused(tmp_path, monkeypatch):
    monkeypatch.delenv("EPHEMERA_CONTACT", raising=False)
    assert gp_pull.main(["--spool", str(tmp_path / "spool"), "--once"]) == 5
