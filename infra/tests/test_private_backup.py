"""infra/private_backup against an in-memory S3 (moto): the private notes reach their prefix and read back, an
unchanged note is not sent again, a checkout without them uploads nothing, and the guard always runs first."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guard  # noqa: E402
import iam_shipper  # noqa: E402
import private_backup  # noqa: E402

BUCKET = "ephemera-test-raw"


@pytest.fixture
def s3(monkeypatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setattr(guard, "enforce", lambda *a, **k: {"profile": "t", "account": "111111111111"})
    with mock_aws():
        c = boto3.client("s3", region_name=private_backup.REGION)
        c.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": private_backup.REGION})
        iam_shipper.ensure_user(boto3.client("iam"), iam_shipper.USER_DEFAULT, BUCKET)
        yield c


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / "DOCS" / "sub").mkdir(parents=True)
    (r / "DOCS" / "decisions.md").write_text("decisions\n", encoding="utf-8")
    (r / "DOCS" / "sub" / "note.md").write_text("note\n", encoding="utf-8")
    (r / "PLAN.md").write_bytes(b"plan\n")
    return r


def keys(s3) -> list[str]:
    return sorted(o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET).get("Contents", []))


def run(repo: Path, *extra: str) -> int:
    return private_backup.main(["--repo", str(repo), "--bucket", BUCKET, *extra])


def test_every_note_lands_under_the_private_prefix_with_its_bytes(s3, repo, tmp_path, capsys):
    """Mutation: drop PLAN.md or the --extra folders from private_backup.notes and this fails."""
    letters = tmp_path / "private-correspondence"
    letters.mkdir()
    (letters / "letter.md").write_text("dear\n", encoding="utf-8")
    assert run(repo, "--extra", str(letters)) == 0
    assert keys(s3) == ["private/DOCS/decisions.md", "private/DOCS/sub/note.md", "private/PLAN.md",
                        "private/private-correspondence/letter.md"]
    assert s3.get_object(Bucket=BUCKET, Key="private/PLAN.md")["Body"].read() == b"plan\n"
    assert "4 uploaded and verified, 0 already there" in capsys.readouterr().out


def test_an_unchanged_note_is_not_sent_again_and_a_changed_one_is(s3, repo, capsys):
    """Mutation: drop the digest comparison in private_backup.back_up and this fails."""
    assert run(repo) == 0
    capsys.readouterr()
    assert run(repo) == 0
    assert "0 uploaded and verified, 3 already there" in capsys.readouterr().out
    (repo / "PLAN.md").write_bytes(b"plan, longer\n")
    assert run(repo) == 0
    assert "1 uploaded and verified, 2 already there" in capsys.readouterr().out
    assert s3.get_object(Bucket=BUCKET, Key="private/PLAN.md")["Body"].read() == b"plan, longer\n"


def test_a_checkout_without_the_notes_uploads_nothing(s3, tmp_path, monkeypatch, capsys):
    """A clone from GitHub has no DOCS/: that must be a stated refusal, never an empty backup that looks fine.

    Mutation: drop the existence check in private_backup.main and this fails."""
    monkeypatch.setattr(guard, "enforce", lambda *a, **k: pytest.fail("the guard ran for a checkout with nothing to send"))
    bare = tmp_path / "bare"
    bare.mkdir()
    assert run(bare) == 2
    assert "only on the owner's machine" in capsys.readouterr().err
    assert keys(s3) == []


def test_the_notes_wait_until_the_host_is_denied_them(s3, repo, capsys):
    """The host's shipper can read the rest of this bucket. An existing user keeps its old policy until
    iam_shipper.py is run again, so the notes must not go up beside a credential that can read them. Found in review.

    Mutation: drop the host_is_denied check from private_backup.main and this fails."""
    iam = boto3.client("iam")
    allow_only = dict(iam_shipper.policy_document(BUCKET))
    allow_only["Statement"] = [s for s in allow_only["Statement"] if s["Effect"] == "Allow"]
    iam.put_user_policy(UserName=iam_shipper.USER_DEFAULT, PolicyName=iam_shipper.POLICY_NAME, PolicyDocument=json.dumps(allow_only))
    assert run(repo) == 3
    assert "infra/iam_shipper.py" in capsys.readouterr().err
    assert keys(s3) == []
    iam.delete_user_policy(UserName=iam_shipper.USER_DEFAULT, PolicyName=iam_shipper.POLICY_NAME)
    assert run(repo) == 3
    assert keys(s3) == []


def test_two_folders_cannot_overwrite_each_other(s3, repo, tmp_path, capsys):
    """Same folder name, same file name, one key: the second would silently replace the first. Found in review.

    Mutation: drop the duplicate-key refusal from private_backup.main and this fails."""
    for parent in ("a", "b"):
        d = tmp_path / parent / "letters"
        d.mkdir(parents=True)
        (d / "x.md").write_text(parent, encoding="utf-8")
    assert run(repo, "--extra", str(tmp_path / "a" / "letters"), "--extra", str(tmp_path / "b" / "letters")) == 2
    assert "private/letters/x.md" in capsys.readouterr().err
    assert keys(s3) == []


def test_a_file_where_a_folder_belongs_is_refused(s3, repo, tmp_path, capsys):
    """A file passed as a folder has nothing to walk, so it was skipped while the run reported success. Found in review.

    Mutation: go back to a plain existence check in private_backup.main and this fails."""
    stray = tmp_path / "stray.md"
    stray.write_text("x", encoding="utf-8")
    assert run(repo, "--extra", str(stray)) == 2
    assert "stray.md" in capsys.readouterr().err
    assert keys(s3) == []


def test_the_guard_runs_before_anything_is_uploaded(s3, repo, monkeypatch):
    """Mutation: move guard.enforce after the upload, or delete it, and this fails."""
    def refuse(*a, **k):
        raise guard.GuardRefused("not the personal account")

    monkeypatch.setattr(guard, "enforce", refuse)
    with pytest.raises(guard.GuardRefused):
        run(repo)
    assert keys(s3) == []


def test_an_upload_that_does_not_read_back_stops_with_the_reason(s3, repo, monkeypatch):
    """Mutation: drop the read-back comparison in private_backup.back_up and this fails."""
    real = s3.head_object

    class Short:
        def __getattr__(self, name):
            return getattr(s3, name)

        def head_object(self, **kw):
            h = real(**kw)
            return {**h, "ContentLength": h["ContentLength"] - 1}

    with pytest.raises(RuntimeError, match="did not read back"):
        private_backup.back_up(Short(), BUCKET, [(repo / "PLAN.md", "private/PLAN.md")])
