#!/usr/bin/env python3
"""Create (idempotently) the cold-storage bucket for the raw archive (D15). Called only after
infra/guard.py has verified the personal account; the bucket lives in eu-west-1 (the cheapest
Deep Archive region in probe P4).

Settings, each chosen for a reason:
  Object Lock enabled at creation (governance mode, NO default retention) - versioning is implied,
      an accidental delete is recoverable, and the small records can still be re-put as they change;
  Block Public Access on - verifiers get object keys and hashes from the ledger, not a public bucket;
  tag project=ephemera - cost allocation for the P4 kill-line check against real bills;
  lifecycle: abort incomplete multipart uploads after 7 days - the one way to leak money here.
No lifecycle transition is needed: the shipper PUTs tars straight into DEEP_ARCHIVE.
"""
from __future__ import annotations

import sys

import boto3
from botocore.exceptions import ClientError

BUCKET = "ephemera-space-raw"
REGION = "eu-west-1"


def ensure_bucket(s3, bucket: str = BUCKET, region: str = REGION) -> str:
    try:
        s3.head_bucket(Bucket=bucket)
        print(f"bucket {bucket}: exists")
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("404", "NoSuchBucket"):
            raise
        s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": region},
                         ObjectLockEnabledForBucket=True)
        print(f"bucket {bucket}: created in {region} with Object Lock")
    s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
    s3.put_bucket_tagging(Bucket=bucket, Tagging={"TagSet": [{"Key": "project", "Value": "ephemera"}]})
    s3.put_bucket_lifecycle_configuration(Bucket=bucket, LifecycleConfiguration={"Rules": [{
        "ID": "abort-stale-multipart", "Status": "Enabled", "Filter": {"Prefix": ""},
        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}}]})
    print(f"bucket {bucket}: public access blocked, tagged project=ephemera, stale multipart aborted after 7 days")
    return bucket


if __name__ == "__main__":
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    import guard

    who = guard.enforce()
    print(f"guard: account {who['account']} via profile {who['profile']}")
    ensure_bucket(boto3.client("s3", region_name=REGION))
