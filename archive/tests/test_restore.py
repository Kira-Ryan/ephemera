"""Behavioural tests for archive/restore.py against an in-memory S3 (moto), driven through main()
over real cycles built by poll.main and really shipped by ship.main. The guard is monkeypatched to a
fake personal identity; the real guard has its own tests.

What must hold: the drill is resumable across the 12 to 48 hour Bulk wait and does not download
before the object is readable; a passing drill has checked the whole evidence chain, not just the
object hash; and every way the cold copy could be wrong (a tampered tar, a member whose bytes
changed, a record that no longer matches the root) fails loudly rather than passing. The last group
is the point of the file: a drill that cannot fail proves nothing.
"""
from __future__ import annotations

import gzip
import io
import json
import sys
import tarfile
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra"))
import guard  # noqa: E402
import poll  # noqa: E402
import restore  # noqa: E402
import ship  # noqa: E402
from test_poll import Feed, build_site, run  # noqa: E402

BUCKET = "ephemera-test-raw"


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setattr(guard, "enforce", lambda *a, **k: {"profile": "test", "account": "111111111111"})
    with mock_aws():
        c = boto3.client("s3", region_name="eu-west-1")
        c.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})
        yield c


@pytest.fixture
def shipped(tmp_path, s3):
    """A real cycle, really packed and uploaded, with its local files deleted so the cold copy is
    the only copy: the state a drill is supposed to be run against."""
    site, names = build_site(tmp_path)
    feed = Feed(site, names)
    spool = tmp_path / "spool"
    rc, rec, cyc = run(feed, spool)
    assert rc == 0
    (cyc / "witness.json").write_text(json.dumps({"ots": {"stamped_utc": poll.utc_now()}, "wayback": {}}))
    assert ship.main(["--spool", str(spool), "--bucket", BUCKET, "--region", "eu-west-1",
                      "--part-size-mb", "5", "--once"]) == 0
    feed.close()
    yield spool, cyc, rec


def rmain(spool: Path, *extra) -> int:
    return restore.main(["--spool", str(spool), "--bucket", BUCKET, "--region", "eu-west-1",
                         "--once", *extra])


def drill_of(spool: Path, cyc: Path) -> dict:
    return json.loads((spool / "drills" / f"{cyc.name[6:]}.json").read_text())


def drive_to_verified(spool: Path, cyc: Path) -> int:
    """Request, then poll, then download and verify. moto restores instantly, so two passes reach
    the download; the loop bounds it so a stuck drill fails the test rather than hanging."""
    for _ in range(5):
        rc = rmain(spool)
        if rc != 3:
            return rc
    raise AssertionError("drill never finished")


def test_drill_is_resumable_and_downloads_only_once_the_object_is_readable(s3, shipped):
    """Mutation: make one_pass() download before restore_state() reports ready, and the first pass
    fails against an object that is still in DEEP_ARCHIVE."""
    spool, cyc, _ = shipped
    assert rmain(spool) == 3                       # requested, not finished
    d = drill_of(spool, cyc)
    assert d["requested_utc"] and not d["restored_utc"] and not d["downloaded_utc"]
    assert d["shipped"]["key"] == f"cycles/{cyc.name[6:]}/files.tar"
    assert drive_to_verified(spool, cyc) == 0
    d = drill_of(spool, cyc)
    assert d["restored_utc"] and d["downloaded_utc"] and d["verified_utc"]
    # the order is real, not cosmetic: nothing is downloaded before the object says it is readable
    assert d["requested_utc"] <= d["restored_utc"] <= d["downloaded_utc"] <= d["verified_utc"]


def test_a_passing_drill_checked_the_whole_evidence_chain(s3, shipped):
    """The point of the drill: not "S3 gave the bytes back" but "the bytes are the archive whose
    root is stamped in Bitcoin". Mutation: drop any of the four checks from verify() and this
    fails."""
    spool, cyc, rec = shipped
    assert drive_to_verified(spool, cyc) == 0
    checks = drill_of(spool, cyc)["checks"]
    assert set(checks) == {"tar_sha256", "tar_bytes", "members", "merkle_root", "files_fingerprint"}
    assert all(c["ok"] for c in checks.values()), checks
    assert checks["members"]["in_tar"] == checks["members"]["recorded"] == len(rec["files"])
    assert checks["merkle_root"]["rebuilt"] == rec["merkle_root"]
    assert checks["tar_sha256"]["got"] == json.loads((cyc / "ship.json").read_text())["shipped"]["sha256"]


def test_nothing_is_downloaded_while_the_object_is_still_restoring(s3, shipped, monkeypatch):
    """moto restores instantly, so the happy path cannot distinguish "waited correctly" from "never
    waited". Hold restore_state at not-ready and assert download() is never reached: a 9.3 GB GET
    against an object still in DEEP_ARCHIVE is an error, and on the real service it is the whole
    reason this is resumable.

    Mutation: drop the `if not ready` gate in one_pass() and this fails."""
    spool, cyc, _ = shipped
    assert rmain(spool) == 3                       # the request pass
    monkeypatch.setattr(restore, "restore_state", lambda s3, shipped: (False, 'ongoing-request="true"'))
    called: list = []
    monkeypatch.setattr(restore, "download", lambda *a, **k: called.append(a))
    assert rmain(spool) == 3
    assert not called, "downloaded while the object was still restoring"
    d = drill_of(spool, cyc)
    assert d["restored_utc"] is None and d["downloaded_utc"] is None


def test_a_root_that_no_longer_matches_the_record_fails_the_drill(s3, shipped):
    """The Merkle root is what the OpenTimestamps proof and the Bitcoin block actually commit to, so
    a restore whose rebuilt root does not match root.txt has not proved what the site claims, even
    with every byte intact.

    Mutation: remove the merkle_root raise from verify() and this fails."""
    spool, cyc, rec = shipped
    assert drive_to_verified(spool, cyc) == 0
    shipped_rec = json.loads((cyc / "ship.json").read_text())["shipped"]
    tar_path = spool / "drills" / f"{cyc.name[6:]}.tar"
    restore.download(boto3.client("s3", region_name="eu-west-1"), shipped_rec, tar_path)
    (cyc / "root.txt").write_text("0" * 64 + "\n", encoding="utf-8")
    with pytest.raises(restore.DrillFailed) as e:
        restore.verify(tar_path, cyc, shipped_rec)
    assert "root" in str(e.value).lower(), str(e.value)


def test_a_tampered_object_fails_the_drill_and_is_recorded(s3, shipped):
    """The cold copy is the thing under test. If S3 returns bytes that are not what was uploaded,
    the drill must fail loudly and say so in its record."""
    spool, cyc, _ = shipped
    key = f"cycles/{cyc.name[6:]}/files.tar"
    assert rmain(spool) == 3
    assert rmain(spool) in (0, 3)                  # restored; download may or may not have run yet
    s3.put_object(Bucket=BUCKET, Key=key, Body=b"not the archive")
    for p in (spool / "drills").glob("*.tar"):
        p.unlink()
    d = drill_of(spool, cyc)
    d["downloaded_utc"] = None
    d["verified_utc"] = None
    (spool / "drills" / f"{cyc.name[6:]}.json").write_text(json.dumps(d))
    assert rmain(spool) == 1
    d = drill_of(spool, cyc)
    assert d["verified_utc"] is None
    assert "DrillFailed" in d["error"] or "sha256" in d["error"], d["error"]


def test_a_member_whose_bytes_changed_fails_even_when_the_tar_hash_is_reconciled(s3, shipped, monkeypatch):
    """A tar that hashes correctly at the object level but whose members no longer match the record
    is the subtle failure: check 1 passes and checks 2 and 3 must catch it. Mutation: stop hashing
    members in verify() and this test passes a corrupt archive."""
    spool, cyc, rec = shipped
    assert drive_to_verified(spool, cyc) == 0
    shipped_rec = json.loads((cyc / "ship.json").read_text())["shipped"]
    tar_path = spool / "drills" / f"{cyc.name[6:]}.tar"
    restore.download(boto3.client("s3", region_name="eu-west-1"), shipped_rec, tar_path)

    # Rebuild the tar with one member's payload changed and RE-GZIPPED, so it is still a perfectly
    # valid gzip and only the raw-byte digest can object. Then declare the new tar's own hash as the
    # expected one, so check 1 passes and checks 2 and 3 are the only things standing between a
    # corrupt archive and a green drill.
    prefix = f"{cyc.name}/files/"
    bad = spool / "drills" / "tampered.tar"
    tampered = 0
    with tarfile.open(tar_path, "r") as src, tarfile.open(bad, "w") as dst:
        for m in src:
            fh = src.extractfile(m)
            data = fh.read() if fh else b""
            if not tampered and m.isfile() and m.name.startswith(prefix) and m.name.endswith(".gz"):
                raw = gzip.decompress(data) + b"\nnot what was archived\n"
                buf = io.BytesIO()
                with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
                    gz.write(raw)
                data = buf.getvalue()
                m.size = len(data)
                tampered += 1
            dst.addfile(m, io.BytesIO(data) if fh else None)
    assert tampered == 1, "the test tampered with no member, so it proves nothing"
    with tarfile.open(bad, "r") as tf:
        assert any(n.startswith(prefix) for n in tf.getnames()), "member names changed; update prefix"

    shipped_rec = dict(shipped_rec, sha256=ship.sha256_file(bad), bytes=bad.stat().st_size)
    with pytest.raises(restore.DrillFailed) as e:
        restore.verify(bad, cyc, shipped_rec)
    assert "different digest" in str(e.value), str(e.value)


def test_a_record_that_drifted_from_the_shipped_tar_fails_the_drill(s3, shipped):
    """The fingerprint is what binds a tar to the exact set of (name, sha256) pairs it was packed
    from. If the local record has since gained or lost a file, the restored tar is no longer the
    archive the record describes, and saying "verified" would be false.

    Mutation: remove the files_fingerprint raise from verify() and this fails."""
    spool, cyc, rec = shipped
    assert drive_to_verified(spool, cyc) == 0
    shipped_rec = json.loads((cyc / "ship.json").read_text())["shipped"]
    tar_path = spool / "drills" / f"{cyc.name[6:]}.tar"
    restore.download(boto3.client("s3", region_name="eu-west-1"), shipped_rec, tar_path)
    # the tar is untouched; only the record moves, which is the healed-cycle case ship.py guards
    shipped_rec = dict(shipped_rec, files_fingerprint="0" * 64)
    with pytest.raises(restore.DrillFailed) as e:
        restore.verify(tar_path, cyc, shipped_rec)
    assert "fingerprint" in str(e.value), str(e.value)


def test_the_drill_picks_a_cycle_whose_local_files_are_already_gone(s3, shipped, tmp_path):
    """A drill against a cycle that still has its files locally proves less. pick_cycle prefers a
    cleaned cycle, and falls back rather than refusing when none is cleaned yet."""
    spool, cyc, _ = shipped
    assert restore.pick_cycle(spool) == cyc        # falls back: nothing is cleaned yet
    state = json.loads((cyc / "ship.json").read_text())
    state["local_files_deleted_utc"] = poll.utc_now()
    (cyc / "ship.json").write_text(json.dumps(state))
    assert restore.pick_cycle(spool) == cyc
    with pytest.raises(restore.DrillFailed):
        restore.pick_cycle(tmp_path / "empty")


def test_status_prints_without_touching_aws(s3, shipped, capsys):
    """--status must be safe to run at any time, including before the guard has anything to check."""
    spool, cyc, _ = shipped
    assert restore.main(["--spool", str(spool), "--cycle", cyc.name[6:], "--status"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["cycle"] == cyc.name and out["verified_utc"] is None
