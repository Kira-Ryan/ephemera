#!/usr/bin/env python3
"""Create (idempotently) the IAM user a poller host ships with, and its one access key.

One user per host (ephemera-shipper-a for the Hetzner host), with one inline policy: put and read
objects under the raw-archive bucket, list it, and nothing else. No delete of any kind, no bucket
configuration, no other service, so a host that is lost can add to the archive and cannot remove
from it; versioning and Object Lock on the bucket (infra/s3_bucket.py) are the second wall. Called
only after infra/guard.py has verified the personal account.

The key is created on the first run, or again with --rotate-key, and goes only into the file named
by --write-config, as an AWS config-file profile section at mode 0600: the host's shipper unit names
that file in AWS_CONFIG_FILE (DOCS/migration-runbook.md, section 4). No key is ever printed, and
without --write-config no key is created.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

BUCKET = "ephemera-space-raw"
REGION = "eu-west-1"
USER_DEFAULT = "ephemera-shipper-a"
PROFILE_DEFAULT = "ephemera"
POLICY_NAME = "ephemera-shipper-bucket-only"


def policy_document(bucket: str = BUCKET) -> dict:
    """What archive/ship.py needs and nothing more: upload_file (PutObject, plus the abort and
    list-parts calls of a multipart upload), head_object (GetObject), put_object for the records
    (PutObject); list on the bucket so a hand check from the host can see what is there."""
    return {"Version": "2012-10-17", "Statement": [
        {"Sid": "ObjectsInTheArchiveBucketOnly", "Effect": "Allow",
         "Action": ["s3:PutObject", "s3:GetObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"],
         "Resource": f"arn:aws:s3:::{bucket}/*"},
        {"Sid": "SeeTheBucket", "Effect": "Allow",
         "Action": ["s3:ListBucket", "s3:ListBucketMultipartUploads", "s3:GetBucketLocation",
                    "s3:ListBucketVersions"],
         "Resource": f"arn:aws:s3:::{bucket}"},
    ]}


def ensure_user(iam, user: str, bucket: str = BUCKET) -> None:
    try:
        iam.create_user(UserName=user, Tags=[{"Key": "project", "Value": "ephemera"}])
        print(f"iam user {user}: created")
    except ClientError as e:
        if e.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
        print(f"iam user {user}: exists")
    iam.put_user_policy(UserName=user, PolicyName=POLICY_NAME, PolicyDocument=json.dumps(policy_document(bucket)))
    print(f"iam user {user}: inline policy {POLICY_NAME} set (put, get and list on {bucket}; no delete)")


def write_profile(path: Path, profile: str, key: dict, region: str = REGION) -> None:
    """An AWS config-file section with the credentials inside it: 0600, LF, replacing the file."""
    text = (f"[profile {profile}]\n"
            f"aws_access_key_id = {key['AccessKeyId']}\n"
            f"aws_secret_access_key = {key['SecretAccessKey']}\n"
            f"region = {region}\n")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.chmod(path, 0o600)
    print(f"iam user: profile [{profile}] written to {path} (0600)")


def ensure_key(iam, user: str, rotate: bool, write_config: Path | None, profile: str) -> bool:
    """The user's one access key. Creates one only when there is none or --rotate-key was given,
    and only with somewhere to put it. Returns whether a key was created."""
    existing = iam.list_access_keys(UserName=user)["AccessKeyMetadata"]
    if existing and not rotate:
        print(f"iam user {user}: has a key already (--rotate-key replaces it)")
        return False
    if write_config is None:
        raise SystemExit(f"iam user {user}: refusing to create a key with nowhere to put it; pass --write-config PATH")
    for k in existing:
        iam.delete_access_key(UserName=user, AccessKeyId=k["AccessKeyId"])
        print(f"iam user {user}: previous key deleted")
    key = iam.create_access_key(UserName=user)["AccessKey"]
    print(f"iam user {user}: key created")
    write_profile(write_config, profile, key)
    return True


def run(iam, user: str, bucket: str, rotate: bool, write_config: Path | None, profile: str) -> int:
    ensure_user(iam, user, bucket)
    ensure_key(iam, user, rotate, write_config, profile)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--user", default=USER_DEFAULT)
    ap.add_argument("--bucket", default=BUCKET)
    ap.add_argument("--profile", default=PROFILE_DEFAULT, help="the profile section name the host's guard pins")
    ap.add_argument("--rotate-key", action="store_true", help="delete the existing key and create a new one")
    ap.add_argument("--write-config", type=Path, default=None, metavar="PATH",
                    help="where a new key goes, as an AWS config-file profile section; required to create one")
    args = ap.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import guard  # noqa: PLC0415 - only needed when actually guarding

    who = guard.enforce()
    print(f"guard: account {who['account']} via profile {who['profile']}")
    return run(boto3.client("iam"), args.user, args.bucket, args.rotate_key, args.write_config, args.profile)


if __name__ == "__main__":
    sys.exit(main())
