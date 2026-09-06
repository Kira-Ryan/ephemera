"""web/publish.py runs unattended every four hours on a machine where other work is in progress.

It staged web/dist and then called a bare `git commit`, which takes the whole index: unfinished
code, or anything staged by accident, pushed to a public branch by a scheduled task.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "web"))
import publish  # noqa: E402


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A throwaway repository standing in for the real one, so no test can touch it."""
    repo = tmp_path / "repo"
    (repo / "web" / "dist").mkdir(parents=True)
    git(repo.parent, "init", str(repo))
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    (repo / "web" / "dist" / "index.html").write_text("<p>first</p>", encoding="utf-8")
    (repo / "README.md").write_text("readme\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "initial")
    monkeypatch.setattr(publish, "REPO", repo)
    return repo


def test_publish_commits_only_web_dist(sandbox, monkeypatch):
    """Mutation: drop the pathspec from the commit and this goes red.

    A secret staged by hand, or a half-finished module, must not be swept into an automated
    publish just because it happened to be in the index when the timer fired."""
    repo = sandbox
    (repo / "web" / "dist" / "index.html").write_text("<p>second</p>", encoding="utf-8")
    (repo / "secret.env").write_text("TOKEN=hunter2\n", encoding="utf-8")
    (repo / "half_written.py").write_text("def broken(:\n", encoding="utf-8")
    git(repo, "add", "secret.env", "half_written.py")          # staged, and nothing to do with the site

    monkeypatch.setattr(publish, "build", _stub_build(), raising=False)
    monkeypatch.setattr(publish.subprocess, "run", _passthrough_lint(publish.subprocess.run))
    rc = publish.main(["--spool", str(repo / "spool"), "--no-push"])
    assert rc == 0

    committed = git(repo, "show", "--name-only", "--pretty=format:", "HEAD").stdout.split()
    assert committed == ["web/dist/index.html"], f"the automated commit swept up {committed}"
    assert "secret.env" in git(repo, "diff", "--cached", "--name-only").stdout, \
        "the unrelated file should still be staged, not published"


def _stub_build():
    class _B:
        @staticmethod
        def main(argv):
            return 0
    return _B()


def _passthrough_lint(real_run):
    """The claims lint runs as a subprocess against the sandbox; let it pass without a register."""
    def run(cmd, *a, **k):
        if any("claims_lint.py" in str(c) for c in cmd):
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, *a, **k)
    return run


def test_nothing_is_committed_when_the_site_did_not_change(sandbox, monkeypatch):
    repo = sandbox
    before = git(repo, "rev-parse", "HEAD").stdout.strip()
    monkeypatch.setattr(publish, "build", _stub_build(), raising=False)
    monkeypatch.setattr(publish.subprocess, "run", _passthrough_lint(publish.subprocess.run))
    assert publish.main(["--spool", str(repo / "spool"), "--no-push"]) == 0
    assert git(repo, "rev-parse", "HEAD").stdout.strip() == before
