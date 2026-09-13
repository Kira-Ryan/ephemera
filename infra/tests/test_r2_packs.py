"""Behavioural tests for infra/r2_packs.py against an in-memory S3 (moto), which R2 is compatible
with for everything used here. What must hold: the account guard refuses anything that is not the
personal account and cannot be talked out of it; a pack is uploaded once and then recognised as
already published; a pack whose bytes changed is re-uploaded rather than trusted; nothing is ever
deleted, because a pack whose spool copy has been cleaned up is the history R2 exists to keep; and
the public URL is built from the configured host so the site can never link a vendor hostname by
accident.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guard_cf  # noqa: E402
import r2_packs  # noqa: E402

BUCKET = "ephemera-packs-test"
ENV = {
    "R2_ACCOUNT_ID": "1111aaaa2222bbbb3333cccc4444dddd",
    "EPHEMERA_CF_ACCOUNT_IDS": "1111aaaa2222bbbb3333cccc4444dddd",
    "R2_ACCESS_KEY_ID": "testing",
    "R2_SECRET_ACCESS_KEY": "testing",
    "R2_ENDPOINT": "https://1111aaaa2222bbbb3333cccc4444dddd.r2.cloudflarestorage.com",
    "R2_BUCKET": BUCKET,
    "R2_PUBLIC_HOST": "packs.ephemera.space",
}


@pytest.fixture
def r2(monkeypatch):
    """A guarded client pointed at moto instead of R2. settings() is left real so the guard it
    enforces is the one under test; only the personal.env read and the endpoint are replaced."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    # Another test in this directory sets AWS_PROFILE, and boto3 prefers a named profile over
    # environment keys, so without this the client raises ProfileNotFound when the whole suite runs
    # even though the file passes alone.
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setattr(guard_cf, "_load_personal_env", lambda: dict(ENV))
    with mock_aws():
        c = boto3.client("s3", region_name="us-east-1")
        c.create_bucket(Bucket=BUCKET)
        monkeypatch.setattr(r2_packs, "client", lambda env: c)
        yield c


@pytest.fixture
def spool(tmp_path):
    score = tmp_path / "score"
    score.mkdir()
    for sha12, rows in (("aaaaaaaaaaaa", 3), ("bbbbbbbbbbbb", 5)):
        (score / f"globe_{sha12}.json").write_text(
            json.dumps({"cycle": f"cycle_{sha12}", "rows": [{"n": i} for i in range(rows)]}), encoding="utf-8")
    return tmp_path


def test_the_guard_refuses_anything_that_is_not_the_personal_account(monkeypatch):
    """Mutation: drop the allowlist check from settings() and the first case passes."""
    monkeypatch.setattr(guard_cf, "_load_personal_env", lambda: dict(ENV, R2_ACCOUNT_ID="999999999999"))
    with pytest.raises(r2_packs.R2Refused, match="not on the personal allowlist"):
        r2_packs.settings()
    monkeypatch.setattr(guard_cf, "_load_personal_env", lambda: dict(ENV, EPHEMERA_CF_ACCOUNT_IDS=""))
    with pytest.raises(r2_packs.R2Refused, match="empty allowlist is a refusal"):
        r2_packs.settings()
    monkeypatch.setattr(guard_cf, "_load_personal_env",
                        lambda: {k: v for k, v in ENV.items() if k != "R2_SECRET_ACCESS_KEY"})
    with pytest.raises(r2_packs.R2Refused, match="missing R2_SECRET_ACCESS_KEY"):
        r2_packs.settings()


def test_settings_takes_no_argument_that_could_bypass_the_check():
    """The project's guards have no override by design. This is the same assertion the AWS and
    Cloudflare guards carry, applied to the R2 one before it grows a seam."""
    import inspect
    assert list(inspect.signature(r2_packs.settings).parameters) == []


def test_a_pack_is_uploaded_once_then_recognised_as_published(r2, spool):
    """Mutation: make sync() skip the object_sha comparison and always upload, and the second
    call reports two uploads instead of two skips."""
    first = r2_packs.sync(spool)
    assert sorted(first["uploaded"]) == ["aaaaaaaaaaaa", "bbbbbbbbbbbb"] and not first["skipped"]
    second = r2_packs.sync(spool)
    assert not second["uploaded"] and sorted(second["skipped"]) == ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]
    head = r2.head_object(Bucket=BUCKET, Key="globe/aaaaaaaaaaaa.json")
    assert head["ContentType"] == "application/json"
    assert head["CacheControl"] == r2_packs.CACHE_CONTROL
    assert head["Metadata"]["sha256"] == r2_packs.sha256_file(spool / "score" / "globe_aaaaaaaaaaaa.json")


def test_a_pack_whose_bytes_changed_is_re_uploaded(r2, spool):
    """A rescored cycle rewrites its pack under the same name. Publishing the stale copy forever
    would make the globe disagree with the figures the ledger publishes for that cycle.

    Mutation: compare only the key's presence, not its digest, and this fails."""
    r2_packs.sync(spool)
    path = spool / "score" / "globe_aaaaaaaaaaaa.json"
    path.write_text(json.dumps({"cycle": "cycle_aaaaaaaaaaaa", "rows": [{"n": 99}]}), encoding="utf-8")
    again = r2_packs.sync(spool)
    assert again["uploaded"] == ["aaaaaaaaaaaa"] and again["skipped"] == ["bbbbbbbbbbbb"]
    assert r2.head_object(Bucket=BUCKET, Key="globe/aaaaaaaaaaaa.json")["Metadata"]["sha256"] == \
        r2_packs.sha256_file(path)


def test_a_pack_cleaned_from_the_spool_stays_published(r2, spool):
    """The spool is pruned; R2 is the history. A sync that deleted what it could not see locally
    would quietly destroy every pack older than the retention window.

    Mutation: add a prune step to sync() and this fails."""
    r2_packs.sync(spool)
    (spool / "score" / "globe_aaaaaaaaaaaa.json").unlink()
    r = r2_packs.sync(spool)
    assert r["local"] == 1 and not r["failed"]
    assert "globe/aaaaaaaaaaaa.json" in {o["Key"] for o in r2.list_objects_v2(Bucket=BUCKET)["Contents"]}


def test_the_public_url_comes_from_the_configured_host(r2):
    """The site links this string. If the host is missing the answer is a refusal, never a vendor
    hostname or a relative path that would silently 404 on the globe."""
    env = r2_packs.settings()
    assert r2_packs.public_url(env, "aaaaaaaaaaaa") == \
        "https://packs.ephemera.space/globe/aaaaaaaaaaaa.json"
    with pytest.raises(r2_packs.R2Refused, match="R2_PUBLIC_HOST"):
        r2_packs.public_url({k: v for k, v in env.items() if k != "R2_PUBLIC_HOST"}, "aaaaaaaaaaaa")


def test_dry_run_writes_nothing(r2, spool):
    r = r2_packs.sync(spool, dry_run=True)
    assert sorted(r["uploaded"]) == ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]
    assert "Contents" not in r2.list_objects_v2(Bucket=BUCKET)
