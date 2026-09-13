#!/usr/bin/env python3
"""Publish the globe packs to Cloudflare R2, so they stop living in git (D08, D19).

Each scored cycle produces a globe pack of about 5.2 MB. Committing one per cycle, three times a
day, grew .git to 96 MB in eleven days and would add roughly 3 GB a year to a public repository
every cloner downloads in full. The packs are a rendering input, not a published figure: the ledger
carries the summary, and a pack is regenerable from its scored report and the archived files. So
they belong in object storage with a stable public URL, and the ledger keeps the name.

R2 rather than S3 because egress is free, which matters for a 5.2 MB download on every globe visit,
and because the site's own zone is already on the same Cloudflare account so the packs can be served
from packs.ephemera.space rather than a vendor hostname.

The key is the cycle's own sha12, so a pack is immutable once written and every scored cycle keeps
its own replayable pack rather than only the newest surviving. That is strictly more history than
git held, because git only ever carried whichever pack was headline at each build.

  python infra/r2_packs.py sync --spool Z:/ephemera/spool     upload every pack not already there
  python infra/r2_packs.py list                               what is published, with sizes
  python infra/r2_packs.py url <sha12>                        the public URL for one cycle

The account guard runs first: the R2 account must be on the same personal allowlist the Cloudflare
guard uses, and there is no override. Credentials come from the gitignored infra/personal.env.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard_cf  # noqa: E402

PREFIX = "globe/"
# The key names the cycle, so an object never legitimately changes. A year is what Cloudflare's
# own guidance suggests for content-addressed assets; immutable stops revalidation entirely.
CACHE_CONTROL = "public, max-age=31536000, immutable"


class R2Refused(RuntimeError):
    """The R2 account is not the personal one, or no credentials exist. Never overridden."""


def settings() -> dict:
    """The R2 names from personal.env, with the account checked against the same personal allowlist
    the Cloudflare guard enforces. An account that is not on it is a refusal, not a warning: the
    whole point of the guards is that no employer account is ever written to (D02)."""
    env = guard_cf._load_personal_env()
    need = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT", "R2_BUCKET")
    missing = [k for k in need if not env.get(k)]
    if missing:
        raise R2Refused(f"personal.env is missing {', '.join(missing)} - nothing to authenticate with")
    allow = (env.get("EPHEMERA_CF_ACCOUNT_IDS") or "").split()
    if not allow:
        raise R2Refused("EPHEMERA_CF_ACCOUNT_IDS is empty - an empty allowlist is a refusal, not a pass")
    if env["R2_ACCOUNT_ID"] not in allow:
        raise R2Refused(f"REFUSED - R2 account {env['R2_ACCOUNT_ID']} is not on the personal allowlist")
    return env


def client(env: dict):
    return boto3.client("s3", endpoint_url=env["R2_ENDPOINT"], region_name="auto",
                        aws_access_key_id=env["R2_ACCESS_KEY_ID"],
                        aws_secret_access_key=env["R2_SECRET_ACCESS_KEY"])


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def public_url(env: dict, sha12: str) -> str:
    host = env.get("R2_PUBLIC_HOST")
    if not host:
        raise R2Refused("R2_PUBLIC_HOST is not set - without it the site cannot link the pack")
    return f"https://{host}/{PREFIX}{sha12}.json"


def published(s3, bucket: str) -> dict[str, dict]:
    """{sha12: {size, sha256}} for everything already under the prefix. The digest is read from the
    object's own metadata rather than its ETag, because R2's ETag is an MD5 for a single-part upload
    and something else entirely for a multipart one, so it is not a stable identity across
    re-uploads."""
    out: dict[str, dict] = {}
    token = None
    while True:
        kw = {"Bucket": bucket, "Prefix": PREFIX}
        if token:
            kw["ContinuationToken"] = token
        page = s3.list_objects_v2(**kw)
        for obj in page.get("Contents", []):
            name = obj["Key"][len(PREFIX):]
            if name.endswith(".json"):
                out[name[:-len(".json")]] = {"size": obj["Size"], "sha256": None}
        if not page.get("IsTruncated"):
            return out
        token = page.get("NextContinuationToken")


def object_sha(s3, bucket: str, sha12: str) -> str | None:
    try:
        head = s3.head_object(Bucket=bucket, Key=f"{PREFIX}{sha12}.json")
    except ClientError:
        return None
    return head.get("Metadata", {}).get("sha256")


def sync(spool: Path, dry_run: bool = False) -> dict:
    """Upload every local pack that is not already published with the same bytes. Never deletes:
    a pack whose spool copy has been cleaned up is exactly the history R2 is there to keep."""
    env = settings()
    s3 = client(env)
    bucket = env["R2_BUCKET"]
    have = published(s3, bucket)
    local = sorted((spool / "score").glob("globe_*.json"))
    uploaded, skipped, failed = [], [], []
    for path in local:
        sha12 = path.stem[len("globe_"):]
        digest = sha256_file(path)
        if sha12 in have and object_sha(s3, bucket, sha12) == digest:
            skipped.append(sha12)
            continue
        if dry_run:
            uploaded.append(sha12)
            continue
        try:
            s3.upload_file(str(path), bucket, f"{PREFIX}{sha12}.json",
                           ExtraArgs={"ContentType": "application/json", "CacheControl": CACHE_CONTROL,
                                      "Metadata": {"sha256": digest, "bytes": str(path.stat().st_size)}})
            uploaded.append(sha12)
        except ClientError as e:
            failed.append(f"{sha12}: {e.response['Error']['Code']}")
    return {"local": len(local), "uploaded": uploaded, "skipped": skipped, "failed": failed,
            "base_url": public_url(env, "").rsplit("/", 1)[0] + "/"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["sync", "list", "url"])
    ap.add_argument("sha12", nargs="?", default=None)
    ap.add_argument("--spool", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    try:
        env = settings()
    except R2Refused as e:
        print(f"r2_packs: {e}", file=sys.stderr)
        return 2

    if args.command == "url":
        if not args.sha12:
            print("r2_packs: url needs a cycle sha12", file=sys.stderr)
            return 2
        print(public_url(env, args.sha12))
        return 0

    if args.command == "list":
        s3 = client(env)
        have = published(s3, env["R2_BUCKET"])
        total = sum(v["size"] for v in have.values())
        for sha12 in sorted(have):
            print(f"{sha12}  {have[sha12]['size'] / 1e6:6.2f} MB  {public_url(env, sha12)}")
        print(f"{len(have)} packs, {total / 1e6:.1f} MB in {env['R2_BUCKET']}")
        return 0

    if not args.spool or not args.spool.is_dir():
        print("r2_packs: sync needs --spool <spool>", file=sys.stderr)
        return 2
    r = sync(args.spool, dry_run=args.dry_run)
    print(f"r2_packs: {r['local']} local, {len(r['uploaded'])} "
          f"{'would upload' if args.dry_run else 'uploaded'}, {len(r['skipped'])} already published"
          + (f", {len(r['failed'])} FAILED" if r["failed"] else ""))
    for f in r["failed"]:
        print(f"  failed: {f}", file=sys.stderr)
    return 1 if r["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
