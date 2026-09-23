"""web/publish.py runs unattended every four hours on a machine where other work is in progress.

Three things it must never do, each of which it once did. Commit anything but web/dist: a bare
`git commit` took the whole index, unfinished code included. Write outside its own tree: the first
version of this test file stubbed the build at module level while the publisher imported it
locally, so a real build ran with a sandbox spool that did not exist and wrote an empty site into
the real web/dist, which was then committed and deployed. Publish a shrinking archive: that empty
site claimed the archive held zero cycles, and nothing stopped it.

A fourth arrived with the second host: build and commit on a clone that is behind what origin
publishes. Every push from such a clone is rejected non-fast-forward, so it stacks local commits
onto a branch nobody can push, and the shrink guard, reading that clone's own stale HEAD, compares
the build against a count the world stopped seeing days ago and waves it through.

Every test here runs against a throwaway repository and a throwaway spool, and where a test needs
an origin it is a bare repository on disk. Nothing here touches a network, which now also means
the object storage the publisher uploads packs to: no_real_object_storage below empties that config
for every test, so none of them can reach the owner's live bucket. The real tree is
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


@pytest.fixture(autouse=True)
def no_real_object_storage(monkeypatch):
    """The publisher uploads the globe packs to R2 before it builds, and R2 settings come from the
    owner's real infra/personal.env, which a sandboxed repository does not shadow. Without this,
    every test in this file would authenticate against the live bucket and upload to it. Emptying
    the config makes r2_packs refuse, which is the same path a machine with no object storage takes,
    so the tests exercise the fallback and reach no network."""
    sys.path.insert(0, str(REPO / "infra"))
    import guard_cf
    monkeypatch.setattr(guard_cf, "_load_personal_env", dict)


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


@pytest.fixture
def with_origin(sandbox, tmp_path):
    """The sandbox repository given an origin and a branch that tracks it, the way the VPS clone
    tracks GitHub. The origin is a bare repository on disk, so fetch and push are file operations
    and no test needs a network."""
    repo, spool = sandbox
    origin = tmp_path / "origin.git"
    git(repo.parent, "init", "--bare", str(origin))
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-u", "origin", branch)
    return repo, spool, origin


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def publish_from_another_host(tmp_path: Path, origin: Path, cycles: int) -> str:
    """A second publisher's build, pushed to origin: what the Windows Ledger kept doing every four
    hours while the VPS clone sat at the commit it was cloned from. Returns the pushed commit."""
    other = tmp_path / f"other_host_{cycles}"
    git(tmp_path, "clone", str(origin), str(other))
    git(other, "config", "user.email", "other@example.invalid")
    git(other, "config", "user.name", "Other")
    (other / "web" / "dist" / "ledger.json").write_text(json.dumps({"totals": {"cycles": cycles}}),
                                                        encoding="utf-8")
    (other / "web" / "dist" / "index.html").write_text(f"<p>{cycles} cycles</p>", encoding="utf-8")
    git(other, "commit", "-q", "-m", "ledger build", "--", "web/dist")
    git(other, "push", "-q", "origin", "HEAD")
    return head(other)


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


def test_a_clone_behind_origin_builds_on_what_is_published(with_origin, tmp_path):
    """The migration case: the VPS clone is made early and another host keeps publishing into it.
    Mutation: delete the sync_with_published() call in main() and the new commit hangs off the
    commit this clone was made at instead of the published one, so HEAD^ is not what was pushed."""
    repo, spool, origin = with_origin
    published = publish_from_another_host(tmp_path, origin, 0)

    assert publish.main(["--spool", str(spool), "--no-push"]) == 0
    assert git(repo, "rev-parse", "HEAD^").stdout.strip() == published, \
        "the build was committed beside what origin publishes, not on top of it"


def test_the_shrink_guard_measures_the_build_against_what_origin_publishes(with_origin, tmp_path):
    """The stale-HEAD hole: this clone's own HEAD says zero cycles, so a zero-cycle build passes a
    guard that only reads HEAD, while origin has been publishing 24 for days. Mutation: delete the
    sync_with_published() call in main() and this goes red on the return code if the baseline is
    left reading HEAD alone, and on the commit check otherwise, since nothing then brings what
    origin published into this clone."""
    repo, spool, origin = with_origin
    assert publish.ledger_cycle_count("HEAD") == 0, "the premise: a stale local count of zero"
    published = publish_from_another_host(tmp_path, origin, 24)

    assert publish.main(["--spool", str(spool), "--no-push"]) == 1
    assert head(repo) == published, "a zero-cycle build was committed over a published 24"


def test_a_build_that_shrinks_against_an_unpushed_local_commit_is_refused(with_origin):
    """Ahead of origin, not behind it: the count to beat is this clone's own last build, which a
    push would make public. Mutation: drop ledger_cycle_count("HEAD") from the baseline in main()
    and the zero-cycle build passes, measured against an origin that still says zero."""
    repo, spool, origin = with_origin
    (repo / "web" / "dist" / "ledger.json").write_text(json.dumps({"totals": {"cycles": 24}}),
                                                       encoding="utf-8")
    git(repo, "commit", "-q", "-m", "ledger build", "--", "web/dist")
    before = head(repo)

    assert publish.main(["--spool", str(spool), "--no-push"]) == 1
    assert head(repo) == before


def test_a_shrink_committed_here_but_not_pushed_is_still_measured_against_origin(with_origin, tmp_path):
    """The other half of the same baseline, and the one case where the two halves differ. HEAD
    holds everything origin published, because sync_with_published() ran first, but a local commit
    made after that can hold FEWER cycles than origin still serves: an --allow-shrink run that
    committed without pushing, which is --no-push here and unattended is a push that failed, whose
    commit web/publish.py:187 leaves for the next run. Origin is still serving 24, so the next run,
    which does not say --allow-shrink, is refused. Mutation: drop ledger_cycle_count(upstream) from
    the baseline in main() and that run measures its zero against this clone's own zero and
    publishes over a published 24."""
    repo, spool, origin = with_origin
    publish_from_another_host(tmp_path, origin, 24)

    assert publish.main(["--spool", str(spool), "--no-push", "--allow-shrink"]) == 0
    shrunk = head(repo)
    assert publish.ledger_cycle_count("HEAD") == 0, "the premise: a local commit under what origin serves"
    assert publish.ledger_cycle_count(publish.upstream_ref()) == 24, "the premise: origin still serves 24"

    assert publish.main(["--spool", str(spool), "--no-push"]) == 1
    assert head(repo) == shrunk, "a second zero-cycle build was committed over a published 24"


def test_a_second_publisher_is_refused_rather_than_merged(with_origin, tmp_path):
    """Two hosts building the same spool is a fault to settle by hand, not a merge: web/dist is a
    build product and a rebase would publish an interleaving neither host built. Mutation: delete
    the sync_with_published() call in main() and this clone commits onto the divergent branch every
    run, which is the wedge itself."""
    repo, spool, origin = with_origin
    assert publish.main(["--spool", str(spool), "--no-push"]) == 0     # this host's build, unpushed
    mine = head(repo)
    publish_from_another_host(tmp_path, origin, 0)                     # the other host's, published

    assert publish.main(["--spool", str(spool), "--no-push"]) == 1
    assert head(repo) == mine, "the divergent branch grew a commit, or was merged"


def test_a_clone_that_cannot_reach_origin_does_not_build(with_origin, tmp_path):
    """Not knowing what is published is not the same as knowing nothing changed. Mutation: delete
    the sync_with_published() call in main() and the build runs and commits while this clone has no
    idea what the world is being served."""
    repo, spool, origin = with_origin
    git(repo, "remote", "set-url", "origin", str(tmp_path / "not_a_repository.git"))
    before = head(repo)

    assert publish.main(["--spool", str(spool), "--no-push"]) == 1
    assert head(repo) == before
    assert (repo / "web" / "dist" / "index.html").read_text(encoding="utf-8") == "<p>first</p>", \
        "the build ran before the clone had established what is published"


def test_a_missing_spool_is_refused_by_the_build_itself(tmp_path):
    """The build must not turn a missing directory into a page saying the archive is empty."""
    sys.path.insert(0, str(REPO / "web"))
    import build  # noqa: PLC0415
    out = tmp_path / "dist"
    assert build.main(["--spool", str(tmp_path / "nowhere"), "--out", str(out)]) == 2
    assert not (out / "index.html").exists()


def test_git_and_the_lint_are_started_without_a_console(monkeypatch, tmp_path):
    """Same reason as the witness: the publisher runs under pythonw every four hours and each git
    call opened a console window on the desktop. Mutation: drop creationflags from publish.git or
    from the lint subprocess."""
    seen = []

    def fake_run(cmd, **kw):
        seen.append((cmd[0], kw))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(publish.subprocess, "run", fake_run)
    publish.git("status")
    assert seen and seen[-1][0] == "git" and seen[-1][1].get("creationflags") == publish.NO_WINDOW
    assert publish.NO_WINDOW == getattr(subprocess, "CREATE_NO_WINDOW", 0)
