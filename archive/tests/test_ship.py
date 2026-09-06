"""Behavioural tests for archive/ship.py against an in-memory S3 (moto), driven through main()
over real cycles built by poll.main. The guard is monkeypatched to a fake personal identity; the
real guard has its own tests. What must hold: a finished cycle's tar lands in DEEP_ARCHIVE with
its SHA-256 in metadata and is verified before being marked shipped; records sit beside it in
STANDARD and re-sync when they change; local files survive until --keep-days; an unshipped or
in-flight cycle is never deleted; a verification failure is recorded, not hidden."""
from __future__ import annotations

import hashlib
import io
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


# --------------------------------------------------------------- audit, 6 Sep 2026


def test_a_healed_cycle_is_reshipped_not_left_incomplete_in_cold_storage(s3, cycle, monkeypatch):
    """A cycle can ship with gaps and be completed later by a resumed pull. The tar is written once
    and never refreshed, but the records beside it are re-synced, so cold storage ended up holding a
    tar missing the recovered file next to a cycle.json calling the cycle complete. Then the local
    files were deleted.

    Mutation: drop the tar_sha_of_files / reship logic and this goes red."""
    feed, spool, rec, cyc = cycle
    # ship it, then heal it: a file appears that the tar does not contain
    assert smain(spool) == 0
    state = json.loads((cyc / "ship.json").read_text())
    assert state["shipped"]
    first_key = state["shipped"]["key"]

    def members(key):
        s3.restore_object(Bucket=BUCKET, Key=key,
                          RestoreRequest={"Days": 1, "GlacierJobParameters": {"Tier": "Bulk"}})
        body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        with tarfile.open(fileobj=io.BytesIO(body)) as t:
            return {m.name for m in t.getmembers() if "/files/" in m.name}

    before = members(first_key)

    raw = b"created: healed\n" + b"x" * 2000
    healed = cyc / "files" / "MEME_77_STARLINK-77_1_Operational_1_UNCLASSIFIED.txt.gz"
    healed.write_bytes(__import__("gzip").compress(raw))
    r = json.loads((cyc / "cycle.json").read_text())
    r["files"] = r["files"] + [{"name": healed.name[:-3],
                                "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}]
    r["files_recorded"] = len(r["files"])
    (cyc / "cycle.json").write_text(json.dumps(r))

    assert smain(spool) == 0
    after = members(first_key)
    assert len(after) == len(before) + 1, "the healed file never reached cold storage"
    assert any(healed.name in n for n in after)


def test_shipment_state_is_durable_before_anything_is_deleted(s3, cycle, monkeypatch):
    """Nothing may be destroyed before the upload that replaces it is recorded on disk.

    The failure this guards against is a chain, not a line: the outbox tar was deleted, retention
    deleted the local files in the same pass, and only then was ship.json written. A failure at that
    last step left a cycle with no local files and no record of having shipped, so the next pass
    packed what remained, which was the records alone, and uploaded that over the good object.

    Simulated by making every ship.json write fail. What must survive: the local files and the
    outbox tar, so that a later pass can finish rather than destroy.

    Mutation: move the durable write below `tar_path.unlink()` and this goes red, because with
    --keep-days 0 the retention step will already have deleted files/ by the time the write fails.
    """
    feed, spool, rec, cyc = cycle
    real_write = poll.write_json_atomic

    def refuse_ship_json(path, data):
        if Path(path).name == "ship.json":
            raise OSError("simulated failure writing ship.json")
        return real_write(path, data)

    monkeypatch.setattr(poll, "write_json_atomic", refuse_ship_json)
    with pytest.raises(OSError):
        smain(spool, "--keep-days", "0")

    assert (cyc / "files").exists() and any((cyc / "files").iterdir()), \
        "local files were deleted before the shipment was durably recorded"
    assert (spool / "outbox" / f"{cyc.name}.tar").exists(), \
        "the outbox tar was deleted before the shipment was durably recorded"

    monkeypatch.setattr(poll, "write_json_atomic", real_write)
    assert smain(spool, "--keep-days", "999") == 0
    state = json.loads((cyc / "ship.json").read_text())
    assert state["shipped"] and state["shipped"]["files_count"] == len(rec["files"])
    s3.restore_object(Bucket=BUCKET, Key=state["shipped"]["key"],
                      RestoreRequest={"Days": 1, "GlacierJobParameters": {"Tier": "Bulk"}})
    body = s3.get_object(Bucket=BUCKET, Key=state["shipped"]["key"])["Body"].read()
    with tarfile.open(fileobj=io.BytesIO(body)) as t:
        stored = {m.name for m in t.getmembers() if "/files/" in m.name}
    assert len(stored) == len(rec["files"]), "cold storage holds a records-only tar"


def test_an_unfinished_cycle_does_not_consume_the_pass_budget(s3, cycle):
    """--max-cycles counted every unshipped directory, including ones that upload nothing, so an
    in-progress cycle sorting earlier by hash could block a finished one every pass, forever.

    Mutation: count attempts rather than uploads and this goes red."""
    feed, spool, rec, cyc = cycle
    blocked = spool / "cycle_000000000000"          # sorts first, and is still pulling
    (blocked / "files").mkdir(parents=True)
    (blocked / "cycle.json").write_text(json.dumps({
        "cycle": blocked.name, "manifest_sha256": "00" * 32, "first_seen_utc": poll.utc_now(),
        "status": "in-progress", "files_listed": 5, "files_recorded": 1, "files_failed": 0,
        "files_not_attempted": 4, "bytes_raw": 10, "merkle_root": None, "files": []}))
    assert smain(spool, "--max-cycles", "1") == 0
    state = json.loads((cyc / "ship.json").read_text())
    assert state["shipped"], "the finished cycle was starved by an in-progress one"


def test_stored_files_are_verified_against_the_record_before_they_are_shipped(s3, cycle):
    """The shipper tarred whatever *.gz it found and checked only the upload's own size and the
    metadata it had just supplied. A locally corrupted file was archived as if it were the real
    thing, and the cycle was then marked shipped.

    Mutation: drop the pre-ship verification and this goes red."""
    feed, spool, rec, cyc = cycle
    r = json.loads((cyc / "cycle.json").read_text())
    victim = cyc / "files" / (r["files"][0]["name"] + ".gz")
    victim.write_bytes(__import__("gzip").compress(b"created: not the recorded bytes\n" + b"z" * 2000))
    assert smain(spool) == 1
    state = json.loads((cyc / "ship.json").read_text())
    assert state["shipped"] is None, "a corrupted cycle was marked shipped"
    assert "do not match the record" in (state["error"] or "")
    assert "Contents" not in s3.list_objects_v2(Bucket=BUCKET, Prefix=f"cycles/{cyc.name[6:]}/files.tar")


def test_a_cycle_shipped_before_fingerprints_existed_is_adopted_not_reuploaded(s3, cycle):
    """Twenty-three cycles were already in cold storage when the tar-to-record binding was added.
    Re-uploading them all would cost days of uplink and the money to match, and treating the absence
    of a fingerprint as "stale" would do exactly that.

    The tar matches the record whenever the record was final before the upload, and both sides
    already record their times. Where that holds the fingerprint is adopted; where it does not, the
    cycle is re-shipped.

    Mutation: treat a missing fingerprint as stale and this goes red."""
    feed, spool, rec, cyc = cycle
    assert smain(spool) == 0
    state = json.loads((cyc / "ship.json").read_text())
    key = state["shipped"]["key"]
    before = s3.head_object(Bucket=BUCKET, Key=key)["LastModified"]

    # rewind to the old shape: shipped, with no fingerprint, record final before the upload
    del state["shipped"]["files_fingerprint"]
    state["shipped"]["uploaded_utc"] = "2026-12-31T00:00:00Z"
    (cyc / "ship.json").write_text(json.dumps(state))
    r = json.loads((cyc / "cycle.json").read_text())
    r["finished_utc"] = "2026-01-01T00:00:00Z"
    (cyc / "cycle.json").write_text(json.dumps(r))

    assert smain(spool) == 0
    assert s3.head_object(Bucket=BUCKET, Key=key)["LastModified"] == before, "an intact cycle was re-uploaded"
    adopted = json.loads((cyc / "ship.json").read_text())
    assert adopted["shipped"]["files_fingerprint"] == ship.files_fingerprint(r), \
        "the fingerprint was not recorded, so the next pass has to guess again"

    # but a record that was still changing when the upload ran is not adoptable
    state = json.loads((cyc / "ship.json").read_text())
    del state["shipped"]["files_fingerprint"]
    state["shipped"]["uploaded_utc"] = "2026-01-01T00:00:00Z"
    (cyc / "ship.json").write_text(json.dumps(state))
    r["finished_utc"] = "2026-12-31T00:00:00Z"
    (cyc / "cycle.json").write_text(json.dumps(r))
    assert smain(spool) == 0
    reshipped = json.loads((cyc / "ship.json").read_text())["shipped"]
    assert reshipped["uploaded_utc"] != "2026-01-01T00:00:00Z", \
        "a cycle whose record was still changing at upload time was left unverified"
    assert reshipped["files_fingerprint"] == ship.files_fingerprint(r)
