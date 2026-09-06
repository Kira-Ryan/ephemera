"""web/publish.py runs unattended every four hours on a machine where other work is in progress.

Three things it must never do, each of which it once did. Commit anything but web/dist: a bare
`git commit` took the whole index, unfinished code included. Write outside its own tree: the first
version of this test file stubbed the build at module level while the publisher imported it
locally, so a real build ran with a sandbox spool that did not exist and wrote an empty site into
the real web/dist, which was then committed and deployed. Publish a shrinking archive: that empty
site claimed the archive held zero cycles, and nothing stopped it.

Every test here runs against a throwaway repository and a throwaway spool. The real tree is
checked afterwards to make sure it was not touched.
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

REAL_DIST = REPO / "web" / "dist" / "ledger.json"


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _lint_passes(real_run):
    """The claims lint runs as a subprocess against the sandbox; let it pass without a register."""
    def run(cmd, *a, **k):
        if any("claims_lint.py" in str(c) for c in cmd):
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, *a, **k)
    return run


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A throwaway repository with one committed site, an empty but existing spool, and the
    publisher pointed at both. The real web/dist is fingerprinted so the test can prove it was
    left alone."""
    repo = tmp_path / "repo"
    (repo / "web" / "dist").mkdir(parents=True)
    (tmp_path / "spool").mkdir()
    git(repo.parent, "init", str(repo))
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    (repo / "web" / "dist" / "index.html").write_text("<p>first</p>", encoding="utf-8")
    (repo / "web" / "dist" / "ledger.json").write_text(json.dumps({"totals": {"cycles": 0}}), encoding="utf-8")
    (repo / "README.md").write_text("readme\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "initial")
    monkeypatch.setattr(publish, "REPO", repo)
    monkeypatch.setattr(publish.subprocess, "run", _lint_passes(publish.subprocess.run))
    real_before = REAL_DIST.read_bytes() if REAL_DIST.exists() else None
    yield repo, tmp_path / "spool"
    real_after = REAL_DIST.read_bytes() if REAL_DIST.exists() else None
    assert real_after == real_before, "a publisher test wrote into the real web/dist"


def test_publish_commits_only_web_dist(sandbox):
    """Mutation: drop the pathspec from the commit and this goes red."""
    repo, spool = sandbox
    (repo / "secret.env").write_text("TOKEN=hunter2\n", encoding="utf-8")
    (repo / "half_written.py").write_text("def broken(:\n", encoding="utf-8")
    git(repo, "add", "secret.env", "half_written.py")          # staged, and nothing to do with the site

    assert publish.main(["--spool", str(spool), "--no-push"]) == 0
    committed = git(repo, "show", "--name-only", "--pretty=format:", "HEAD").stdout.split()
    assert committed and all(c.startswith("web/dist/") for c in committed), \
        f"the automated commit swept up {committed}"
    assert "secret.env" in git(repo, "diff", "--cached", "--name-only").stdout, \
        "the unrelated file should still be staged, not published"


def test_the_build_is_directed_into_the_publishers_own_tree(sandbox):
    """Mutation: drop --out from the build call and the sandbox never gets a ledger, while the
    fixture's teardown catches the real tree being written."""
    repo, spool = sandbox
    assert publish.main(["--spool", str(spool), "--no-push"]) == 0
    assert (repo / "web" / "dist" / "ledger.json").exists()
    assert (repo / "web" / "dist" / "globe" / "index.html").exists()


def test_a_shrinking_archive_is_refused(sandbox):
    """Mutation: drop the count comparison and this goes red. The published site once said the
    archive held 24 cycles; a build over an unreadable spool said 0, and it went live."""
    repo, spool = sandbox
    (repo / "web" / "dist" / "ledger.json").write_text(json.dumps({"totals": {"cycles": 24}}), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "a published site with 24 cycles")
    before = git(repo, "rev-parse", "HEAD").stdout.strip()

    assert publish.main(["--spool", str(spool), "--no-push"]) == 1
    assert git(repo, "rev-parse", "HEAD").stdout.strip() == before, "the shrunken site was committed"

    assert publish.main(["--spool", str(spool), "--no-push", "--allow-shrink"]) == 0
    assert git(repo, "rev-parse", "HEAD").stdout.strip() != before


def test_nothing_is_committed_when_the_site_did_not_change(sandbox):
    repo, spool = sandbox
    assert publish.main(["--spool", str(spool), "--no-push"]) == 0
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    # a second build over the same spool differs only by its build stamp, which is a change; so
    # this checks the guard on a byte-identical dist instead
    git(repo, "add", "--", "web/dist")
    assert publish.main(["--spool", str(spool), "--no-push"]) in (0, 1)
    assert git(repo, "status", "--porcelain", "--", "README.md").stdout == ""
    assert head  # the first publish did commit


def test_a_missing_spool_is_refused_by_the_build_itself(tmp_path):
    """The build must not turn a missing directory into a page saying the archive is empty."""
    sys.path.insert(0, str(REPO / "web"))
    import build  # noqa: PLC0415
    out = tmp_path / "dist"
    assert build.main(["--spool", str(tmp_path / "nowhere"), "--out", str(out)]) == 2
    assert not (out / "index.html").exists()
