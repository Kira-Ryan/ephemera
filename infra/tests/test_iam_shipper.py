"""infra/iam_shipper against an in-memory IAM (moto): one user per host whose one policy can add to
the archive bucket and never remove from it; the key is created once, rotated only on request,
never printed, and written to a 0600 profile file or not created at all."""
from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import iam_shipper  # noqa: E402

USER = "shipper-t"
BUCKET = "ephemera-test-raw"


@pytest.fixture
def iam(monkeypatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)   # never inherit a profile from another test
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        yield boto3.client("iam", region_name="eu-west-1")


def key_ids(iam) -> list[str]:
    return [k["AccessKeyId"] for k in iam.list_access_keys(UserName=USER)["AccessKeyMetadata"]]


def test_the_policy_can_add_to_the_bucket_and_never_remove_from_it():
    doc = iam_shipper.policy_document(BUCKET)
    actions = [a for s in doc["Statement"] for a in s["Action"]]
    assert {"s3:PutObject", "s3:GetObject", "s3:ListBucket"} <= set(actions)
    assert not [a for a in actions if "Delete" in a or "Retention" in a or "Bypass" in a or a.endswith("*")]
    assert all(s["Effect"] == "Allow" for s in doc["Statement"])
    assert {s["Resource"] for s in doc["Statement"]} == {f"arn:aws:s3:::{BUCKET}", f"arn:aws:s3:::{BUCKET}/*"}


def test_first_run_creates_user_policy_and_key_and_writes_the_profile_file(iam, tmp_path, capsys):
    cfg = tmp_path / "aws-config"
    assert iam_shipper.run(iam, USER, BUCKET, rotate=False, write_config=cfg, profile="ephemera") == 0
    assert iam.get_user(UserName=USER)["User"]["UserName"] == USER
    pol = iam.get_user_policy(UserName=USER, PolicyName=iam_shipper.POLICY_NAME)["PolicyDocument"]
    assert (json.loads(pol) if isinstance(pol, str) else pol) == iam_shipper.policy_document(BUCKET)
    ids = key_ids(iam)
    assert len(ids) == 1
    text = cfg.read_text(encoding="utf-8")
    assert text.startswith("[profile ephemera]\n")
    assert f"aws_access_key_id = {ids[0]}\n" in text and "aws_secret_access_key = " in text
    assert text.endswith("region = eu-west-1\n") and "\r" not in text
    if sys.platform != "win32":
        assert stat.S_IMODE(cfg.stat().st_mode) == 0o600
    out = capsys.readouterr().out
    assert "key created" in out and ids[0] not in out


def test_a_second_run_keeps_the_existing_key_and_writes_nothing(iam, tmp_path):
    cfg = tmp_path / "aws-config"
    iam_shipper.run(iam, USER, BUCKET, rotate=False, write_config=cfg, profile="ephemera")
    before, ids = cfg.read_text(), key_ids(iam)
    iam_shipper.run(iam, USER, BUCKET, rotate=False, write_config=tmp_path / "other", profile="ephemera")
    assert key_ids(iam) == ids
    assert cfg.read_text() == before and not (tmp_path / "other").exists()


def test_rotate_replaces_the_one_key_in_iam_and_in_the_file(iam, tmp_path):
    cfg = tmp_path / "aws-config"
    iam_shipper.run(iam, USER, BUCKET, rotate=False, write_config=cfg, profile="ephemera")
    [old] = key_ids(iam)
    iam_shipper.run(iam, USER, BUCKET, rotate=True, write_config=cfg, profile="ephemera")
    [new] = key_ids(iam)
    assert new != old
    assert new in cfg.read_text() and old not in cfg.read_text()


def test_a_key_is_never_created_with_nowhere_to_put_it(iam):
    with pytest.raises(SystemExit, match="write-config"):
        iam_shipper.run(iam, USER, BUCKET, rotate=False, write_config=None, profile="ephemera")
    assert iam.get_user(UserName=USER)["User"]["UserName"] == USER   # the user and policy are still made
    assert key_ids(iam) == []


def test_main_runs_the_guard_first_and_then_the_work(iam, tmp_path, monkeypatch):
    """The caller. Mutation: drop the run() call from main() and the file is never written."""
    import guard  # noqa: PLC0415 - infra/ is on sys.path via the module under test

    order: list[str] = []
    monkeypatch.setattr(guard, "enforce", lambda: (order.append("guard"), {"account": "1", "profile": "p"})[1])
    monkeypatch.setattr(iam_shipper.boto3, "client", lambda service, **kw: (order.append(service), iam)[1])
    cfg = tmp_path / "aws-config"
    assert iam_shipper.main(["--user", USER, "--bucket", BUCKET, "--write-config", str(cfg)]) == 0
    assert order == ["guard", "iam"]
    assert cfg.exists() and len(key_ids(iam)) == 1
