"""infra/s3_bucket.ensure_bucket against an in-memory S3 (moto): idempotent, Object Lock on,
public access blocked, cost tag present, stale-multipart lifecycle set."""
from __future__ import annotations

import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import s3_bucket  # noqa: E402


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)   # never inherit a profile from another test
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        yield boto3.client("s3", region_name="eu-west-1")


def test_bucket_is_created_hardened_and_idempotent(s3, capsys):
    name = s3_bucket.ensure_bucket(s3, "ephemera-test-raw", "eu-west-1")
    assert name == "ephemera-test-raw"
    assert s3.get_object_lock_configuration(Bucket=name)["ObjectLockConfiguration"]["ObjectLockEnabled"] == "Enabled"
    pab = s3.get_public_access_block(Bucket=name)["PublicAccessBlockConfiguration"]
    assert all(pab.values())
    tags = {t["Key"]: t["Value"] for t in s3.get_bucket_tagging(Bucket=name)["TagSet"]}
    assert tags == {"project": "ephemera"}
    rules = s3.get_bucket_lifecycle_configuration(Bucket=name)["Rules"]
    assert rules[0]["AbortIncompleteMultipartUpload"]["DaysAfterInitiation"] == 7
    assert s3.get_bucket_versioning(Bucket=name).get("Status") == "Enabled"  # implied by Object Lock
    s3_bucket.ensure_bucket(s3, name, "eu-west-1")                          # second call: no error
    assert "exists" in capsys.readouterr().out
