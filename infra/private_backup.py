#!/usr/bin/env python3
"""Copy the owner's private notes to a private prefix of the locked bucket, and prove each one landed.

DOCS/ and PLAN.md are gitignored and exist only on the owner's machine, so this is their one copy off
it. Run by hand from that machine after they change:

    python infra/private_backup.py --extra Z:/ephemera/private-correspondence

Every file goes to private/ in Standard class, unless the object there already records the same
SHA-256. Each upload is read back: size and digest must match or this stops with the reason. The bucket
blocks public access, and versioning keeps an overwritten copy. The host's shipper can read the rest of the
bucket, so nothing goes up unless its policy denies this prefix (infra/iam_shipper.py). The account guard
runs first; there is no way to skip it.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REPO = Path(__file__).resolve().parents[1]
BUCKET = "ephemera-space-raw"
REGION = "eu-west-1"
PREFIX = "private/"


def notes(repo: Path, extras: list[Path]) -> list[tuple[Path, str]]:
    """(local file, object key) for everything this backs up."""
    items = [(p, PREFIX + p.relative_to(repo).as_posix()) for p in sorted((repo / "DOCS").rglob("*")) if p.is_file()]
    items.append((repo / "PLAN.md", PREFIX + "PLAN.md"))
    for extra in extras:
        items += [(p, f"{PREFIX}{extra.name}/{p.relative_to(extra).as_posix()}") for p in sorted(extra.rglob("*")) if p.is_file()]
    return items


def host_is_denied(iam, bucket: str) -> bool:
    """Whether the host's shipper is denied this prefix in the policy it holds right now. An existing user keeps
    the policy it was given until infra/iam_shipper.py runs again, so what the code says proves nothing."""
    import iam_shipper  # noqa: PLC0415 - sibling module, found through the path main() sets

    try:
        doc = iam.get_user_policy(UserName=iam_shipper.USER_DEFAULT, PolicyName=iam_shipper.POLICY_NAME)["PolicyDocument"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchEntity":
            return False
        raise
    held = json.loads(doc) if isinstance(doc, str) else doc
    return all(s in held["Statement"] for s in iam_shipper.policy_document(bucket)["Statement"] if s["Effect"] == "Deny")


def recorded_digest(s3, bucket: str, key: str) -> str | None:
    try:
        return s3.head_object(Bucket=bucket, Key=key).get("Metadata", {}).get("sha256")
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return None
        raise


def back_up(s3, bucket: str, items: list[tuple[Path, str]]) -> tuple[int, int]:
    """(uploaded, already there). Raises the moment an upload does not read back as what was sent."""
    uploaded = unchanged = 0
    for path, key in items:
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if recorded_digest(s3, bucket, key) == digest:
            unchanged += 1
            continue
        s3.put_object(Bucket=bucket, Key=key, Body=body, StorageClass="STANDARD", ChecksumAlgorithm="CRC32",
                      Metadata={"sha256": digest})
        head = s3.head_object(Bucket=bucket, Key=key)
        if head["ContentLength"] != len(body) or head.get("Metadata", {}).get("sha256") != digest:
            raise RuntimeError(f"{key} did not read back as uploaded: {head['ContentLength']} bytes, expected {len(body)}")
        uploaded += 1
    return uploaded, unchanged


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument("--extra", type=Path, action="append", default=[], help="another private folder to include")
    ap.add_argument("--bucket", default=BUCKET)
    args = ap.parse_args(argv)
    folders, files = (args.repo / "DOCS", *args.extra), (args.repo / "PLAN.md",)
    missing = [str(p) for p in folders if not p.is_dir()] + [str(p) for p in files if not p.is_file()]
    if missing:
        print(f"private_backup: {', '.join(missing)} not found where expected (folders for DOCS and --extra, a file for "
              "PLAN.md). The notes are only on the owner's machine; nothing was uploaded.", file=sys.stderr)
        return 2
    items = notes(args.repo, args.extra)
    clashes = [key for key, n in collections.Counter(key for _, key in items).items() if n > 1]
    if clashes:
        print(f"private_backup: two files would share {', '.join(clashes)}; nothing was uploaded.", file=sys.stderr)
        return 2
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import guard  # noqa: PLC0415 - only needed when actually guarding

    guard.enforce()                                 # raises GuardRefused; nothing catches it here
    if not host_is_denied(boto3.client("iam"), args.bucket):
        print("private_backup: the host's shipper is not denied this prefix, so it could read the notes. Run "
              "infra/iam_shipper.py first; nothing was uploaded.", file=sys.stderr)
        return 3
    uploaded, unchanged = back_up(boto3.client("s3", region_name=REGION), args.bucket, items)
    print(f"private_backup: {uploaded} uploaded and verified, {unchanged} already there, under {args.bucket}/{PREFIX}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
