"""Behavioural tests for archive/ship.py against an in-memory S3 (moto), driven through main()
over real cycles built by poll.main. The guard is monkeypatched to a fake personal identity; the
real guard has its own tests. What must hold: a finished cycle's tar lands in DEEP_ARCHIVE with
its SHA-256 in metadata and is verified before being marked shipped; records sit beside it in
STANDARD and re-sync when they change; local files survive until --keep-days; an unshipped or
in-flight cycle is never deleted; a verification failure is recorded, not hidden."""
from __future__ import annotations

import hashlib
import json
import sys
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra"))
import poll  # noqa: E402
import ship  # noqa: E402
import guard  # noqa: E402
from test_poll import CONTACT, Feed, build_site, run  # noqa: E402

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
def cycle(tmp_path):
    site, names = build_site(tmp_path)
    feed = Feed(site, names)
    spool = tmp_path / "spool"
    rc, rec, cyc = run(feed, spool)
    assert rc == 0
    (cyc / "witness.json").write_text(json.dumps({"ots": {"stamped_utc": poll.utc_now()}, "wayback": {}}))
    yield feed, spool, rec, cyc
    feed.close()


def smain(spool: Path, *extra) -> int:
    return ship.main(["--spool", str(spool), "--bucket", BUCKET, "--region", "eu-west-1",
                      "--part-size-mb", "5", "--once", *extra])


def test_finished_cycle_ships_verified_with_records_beside_it(s3, cycle):
    _, spool, rec, cyc = cycle
    assert smain(spool) == 0
    state = json.loads((cyc / "ship.json").read_text())
    key = f"cycles/{cyc.name[6:]}/files.tar"
    assert state["shipped"]["key"] == key and state["error"] is None
    head = s3.head_object(Bucket=BUCKET, Key=key)
    assert head["StorageClass"] == "DEEP_ARCHIVE"
    assert head["ContentLength"] == state["shipped"]["bytes"]
    assert head["Metadata"]["sha256"] == state["shipped"]["sha256"]
    assert head["Metadata"]["merkle_root"] == rec["merkle_root"]
    # A Deep Archive object cannot be read until restored (moto enforces this like AWS does); this
    # is the verifier's path: restore, read, compare with the recorded SHA-256.
    s3.restore_object(Bucket=BUCKET, Key=key,
                      RestoreRequest={"Days": 1, "GlacierJobParameters": {"Tier": "Bulk"}})
    body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    assert hashlib.sha256(body).hexdigest() == state["shipped"]["sha256"]
    tar_path = spool / "outbox" / f"{cyc.name}.tar.check"
    tar_path.write_bytes(body)
    with tarfile.open(tar_path) as tar:
        names = set(tar.getnames())
    assert {f"{cyc.name}/files/{n}.gz" for n in [f["name"] for f in rec["files"]]} <= names
    assert f"{cyc.name}/cycle.json" in names and f"{cyc.name}/root.txt" in names
    for name in ("cycle.json", "root.txt", "witness.json", "MANIFEST.txt"):
        assert s3.head_object(Bucket=BUCKET, Key=f"cycles/{cyc.name[6:]}/{name}").get("StorageClass", "STANDARD") == "STANDARD"
    assert not (spool / "outbox" / f"{cyc.name}.tar").exists()      # outbox tar removed after verify
    assert (cyc / "files").exists() and not state.get("local_files_deleted_utc")  # too young to delete


def test_records_resync_when_they_change_and_tar_is_not_reuploaded(s3, cycle):
    _, spool, rec, cyc = cycle
    assert smain(spool) == 0
    first = json.loads((cyc / "ship.json").read_text())
    (cyc / "witness.json").write_text(json.dumps({"ots": {"attested": {"block_height": 964904}}, "wayback": {}}))
    assert smain(spool) == 0
    second = json.loads((cyc / "ship.json").read_text())
    assert second["shipped"] == first["shipped"]                     # no second upload
    assert second["records"]["witness.json"] != first["records"]["witness.json"]
    body = s3.get_object(Bucket=BUCKET, Key=f"cycles/{cyc.name[6:]}/witness.json")["Body"].read()
    assert b"964904" in body


def test_local_files_deleted_only_after_keep_days(s3, cycle):
    """Mutation: drop the age check -> files vanish on the first pass, red."""
    _, spool, rec, cyc = cycle
    assert smain(spool) == 0
    assert (cyc / "files").exists()
    r = json.loads((cyc / "cycle.json").read_text())
    r["first_seen_utc"] = (datetime.now(timezone.utc) - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (cyc / "cycle.json").write_text(json.dumps(r))
    assert smain(spool) == 0
    state = json.loads((cyc / "ship.json").read_text())
    assert not (cyc / "files").exists() and state["local_files_deleted_utc"]
    assert (cyc / "cycle.json").exists() and (cyc / "root.txt").exists()   # records stay local forever


def test_gapped_cycle_ships_but_in_progress_does_not(s3, tmp_path, monkeypatch):
    site, names = build_site(tmp_path)
    feed = Feed(site, names)
    try:
        (site / "MANIFEST.txt").write_text("\n".join(names + ["MEME_0_GONE_0_Operational_0_UNCLASSIFIED.txt"]) + "\n")
        monkeypatch.setattr(poll, "BACKOFF_S", 0.0)
        spool = tmp_path / "spool"
        rc, rec, gap = run(feed, spool)
        assert rc == 2
        prog = spool / "cycle_000000000000"
        (prog / "files").mkdir(parents=True)
        (prog / "cycle.json").write_text(json.dumps({"cycle": prog.name, "status": "in-progress",
                                                    "first_seen_utc": poll.utc_now(), "files": []}))
        assert smain(spool) == 0
        assert json.loads((gap / "ship.json").read_text())["shipped"]["key"].endswith("/files.tar")
        assert not (prog / "ship.json").exists()
        keys = [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET)["Contents"]]
        assert not any(k.startswith("cycles/000000000000") for k in keys)
    finally:
        feed.close()


def test_verification_failure_is_recorded_and_nothing_is_marked_shipped(s3, cycle, monkeypatch):
    _, spool, rec, cyc = cycle
    real_head = s3.head_object

    def lying_head(**kw):
        h = real_head(**kw)
        if kw["Key"].endswith("files.tar"):
            h["ContentLength"] = h["ContentLength"] - 1
        return h

    monkeypatch.setattr(s3, "head_object", lying_head)
    monkeypatch.setattr(boto3, "client", lambda *a, **k: s3)
    assert smain(spool) == 1
    state = json.loads((cyc / "ship.json").read_text())
    assert state["shipped"] is None and "size mismatch" in state["error"]
    assert (cyc / "files").exists()
    assert (spool / "outbox" / f"{cyc.name}.tar").exists()          # kept for the retry


def test_max_cycles_bounds_uploads_per_pass(s3, cycle):
    """Mutation: ignore --max-cycles -> both cycles ship on pass 1, red."""
    feed, spool, rec, cyc1 = cycle
    extra = "MEME_9_STARLINK-9_1_Operational_1_UNCLASSIFIED.txt"
    (feed.site / extra).write_bytes(__import__("test_poll").make_file(9))
    (feed.site / "MANIFEST.txt").write_text("\n".join(feed.names + [extra]) + "\n")
    assert poll.main(["--base", feed.base, "--spool", str(spool), "--workers", "4",
                      "--contact", CONTACT, "--min-free-gb", "0"]) == 0
    assert smain(spool, "--max-cycles", "1") == 0
    shipped = [c for c in spool.glob("cycle_*") if (c / "ship.json").exists()
               and json.loads((c / "ship.json").read_text())["shipped"]]
    assert len(shipped) == 1
    assert smain(spool, "--max-cycles", "1") == 0
    shipped = [c for c in spool.glob("cycle_*") if (c / "ship.json").exists()
               and json.loads((c / "ship.json").read_text())["shipped"]]
    assert len(shipped) == 2


def test_guard_refusal_stops_everything_before_any_upload(s3, cycle, monkeypatch):
    _, spool, rec, cyc = cycle

    def refuse(*a, **k):
        raise guard.GuardRefused("guard: REFUSED - test")

    monkeypatch.setattr(guard, "enforce", refuse)
    with pytest.raises(guard.GuardRefused):
        smain(spool)
    assert "Contents" not in s3.list_objects_v2(Bucket=BUCKET)
    assert not (cyc / "ship.json").exists()
