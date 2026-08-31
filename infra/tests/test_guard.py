"""The account guard (D02): a foreign AWS identity must stop a guarded script before it does
anything; only an allowlisted identity passes; a missing or empty allowlist refuses; no override
path exists; and every infra script actually sources the guard first (the call-site rule)."""
from __future__ import annotations

import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
INFRA = REPO / "infra"
BASH = shutil.which("bash") or pytest.skip("bash not on PATH", allow_module_level=True)

PERSONAL_ID = "111111111111"
FOREIGN_ID = "999999999999"


def stage(tmp_path: Path, *, account: str, env: str | None = f'EPHEMERA_AWS_ACCOUNT_IDS="{PERSONAL_ID}"') -> Path:
    """Copy infra/ to a sandbox with a fake `aws` on PATH answering `account`, and a guarded probe
    script that creates sentinel.txt only if the guard lets it through."""
    work = tmp_path / "infra"
    shutil.copytree(INFRA, work, ignore=shutil.ignore_patterns("tests", "__pycache__", "personal.env"))
    if env is not None:
        (work / "personal.env").write_text(env + "\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    aws = fake_bin / "aws"
    aws.write_text("#!/usr/bin/env bash\n"
                   'if [ "$1 $2" = "sts get-caller-identity" ]; then\n'
                   f'  case "$*" in *"--query Account"*) echo {account};; *) echo \'{{"Account": "{account}"}}\';; esac\n'
                   "else\n  echo unexpected-aws-call >&2; exit 9\nfi\n")
    aws.chmod(aws.stat().st_mode | stat.S_IEXEC)
    probe = work / "probe.sh"
    probe.write_text('#!/usr/bin/env bash\n. "$(dirname "${BASH_SOURCE[0]}")/guard.sh"\n'
                     'echo did-the-thing > "$(dirname "${BASH_SOURCE[0]}")/sentinel.txt"\n')
    return work


def run_probe(work: Path) -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ)
    env["PATH"] = str(work.parent / "bin") + os.pathsep + env["PATH"]
    return subprocess.run([BASH, str(work / "probe.sh")], capture_output=True, text=True, env=env)


def test_foreign_account_is_refused_before_any_action(tmp_path):
    work = stage(tmp_path, account=FOREIGN_ID)
    r = run_probe(work)
    assert r.returncode == 1 and "REFUSED" in r.stderr and FOREIGN_ID in r.stderr
    assert not (work / "sentinel.txt").exists()  # the guarded script never reached its own body


def test_allowlisted_account_passes(tmp_path):
    work = stage(tmp_path, account=PERSONAL_ID)
    r = run_probe(work)
    assert r.returncode == 0, r.stderr
    assert (work / "sentinel.txt").read_text().strip() == "did-the-thing"


def test_missing_personal_env_is_a_refusal(tmp_path):
    work = stage(tmp_path, account=PERSONAL_ID, env=None)
    r = run_probe(work)
    assert r.returncode == 1 and "personal.env is missing" in r.stderr
    assert not (work / "sentinel.txt").exists()


def test_empty_allowlist_is_a_refusal_not_a_pass(tmp_path):
    work = stage(tmp_path, account=PERSONAL_ID, env='EPHEMERA_AWS_ACCOUNT_IDS=""')
    r = run_probe(work)
    assert r.returncode == 1 and "empty allowlist is a refusal" in r.stderr
    assert not (work / "sentinel.txt").exists()


def test_guard_has_no_override_path():
    text = (INFRA / "guard.sh").read_text()
    body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
    assert not re.search(r"(?i)override|force|skip[_-]?guard|EPHEMERA_GUARD_DISABLE", body)


def test_every_infra_script_sources_the_guard_first():
    """The call-site rule (CLAUDE.md rule 2). Mutation: drop the source line from whoami.sh -> red."""
    scripts = [p for p in INFRA.glob("*.sh") if p.name != "guard.sh"]
    assert scripts, "no guarded scripts found - whoami.sh should exist"
    for s in scripts:
        lines = [l.strip() for l in s.read_text().splitlines()
                 if l.strip() and not l.strip().startswith("#") and not l.strip().startswith("#!")]
        assert lines and re.match(r'^\.\s+.*guard\.sh"?$', lines[0]), \
            f"{s.name}: first non-comment line must source guard.sh, got: {lines[:1]}"
