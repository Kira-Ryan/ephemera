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
EMPLOYER_ID = "222222222222"
GOOD_ENV = (f'EPHEMERA_AWS_PROFILE="personal"\nEPHEMERA_AWS_ACCOUNT_IDS="{PERSONAL_ID}"\n'
            f'EPHEMERA_AWS_FORBIDDEN_IDS="{EMPLOYER_ID}"')


def stage(tmp_path: Path, *, account: str, env: str | None = GOOD_ENV) -> Path:
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
                     'echo "did-the-thing profile=$AWS_PROFILE" > "$(dirname "${BASH_SOURCE[0]}")/sentinel.txt"\n')
    return work


def run_probe(work: Path, script: str = "probe.sh") -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ)
    env["PATH"] = str(work.parent / "bin") + os.pathsep + env["PATH"]
    return subprocess.run([BASH, str(work / script)], capture_output=True, text=True, env=env)


def test_foreign_account_is_refused_before_any_action(tmp_path):
    work = stage(tmp_path, account=FOREIGN_ID)
    r = run_probe(work)
    assert r.returncode == 1 and "REFUSED" in r.stderr and FOREIGN_ID in r.stderr
    assert not (work / "sentinel.txt").exists()  # the guarded script never reached its own body


def test_allowlisted_account_passes_and_pins_the_profile(tmp_path):
    """The guard exports AWS_PROFILE from personal.env before any call, so the machine's default
    (employer) profile is never consulted. Mutation: drop the export -> the probe sees no profile."""
    work = stage(tmp_path, account=PERSONAL_ID)
    r = run_probe(work)
    assert r.returncode == 0, r.stderr
    assert (work / "sentinel.txt").read_text().strip() == "did-the-thing profile=personal"


def test_missing_profile_is_a_refusal(tmp_path):
    work = stage(tmp_path, account=PERSONAL_ID, env=f'EPHEMERA_AWS_ACCOUNT_IDS="{PERSONAL_ID}"')
    r = run_probe(work)
    assert r.returncode == 1 and "EPHEMERA_AWS_PROFILE is empty" in r.stderr
    assert not (work / "sentinel.txt").exists()


def test_forbidden_employer_id_is_refused_even_if_allowlisted(tmp_path):
    """The forbidden list wins over everything. Mutation: check the allowlist first -> red."""
    env = (f'EPHEMERA_AWS_PROFILE="personal"\nEPHEMERA_AWS_ACCOUNT_IDS="{EMPLOYER_ID} {PERSONAL_ID}"\n'
           f'EPHEMERA_AWS_FORBIDDEN_IDS="{EMPLOYER_ID}"')
    work = stage(tmp_path, account=EMPLOYER_ID, env=env)
    r = run_probe(work)
    assert r.returncode == 1 and "FORBIDDEN" in r.stderr and EMPLOYER_ID in r.stderr
    assert not (work / "sentinel.txt").exists()


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


def test_guards_have_no_override_path():
    for name in ("guard.sh", "guard_cf.sh"):
        text = (INFRA / name).read_text()
        body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
        assert not re.search(r"(?i)override|force|skip[_-]?guard|EPHEMERA_GUARD_DISABLE", body), name


def test_every_infra_script_sources_a_guard_first():
    """The call-site rule (CLAUDE.md rule 2). Mutation: drop the source line from any script -> red."""
    scripts = [p for p in INFRA.glob("*.sh") if p.name not in ("guard.sh", "guard_cf.sh")]
    assert len(scripts) >= 3, "expected whoami.sh, site-bootstrap.sh, deploy-site.sh at least"
    for s in scripts:
        lines = [l.strip() for l in s.read_text().splitlines()
                 if l.strip() and not l.strip().startswith("#") and not l.strip().startswith("#!")]
        assert lines and re.match(r'^\.\s+.*guard(_cf)?\.sh"$', lines[0]), \
            f"{s.name}: first non-comment line must source guard.sh or guard_cf.sh, got: {lines[:1]}"


CF_ID = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
CF_OTHER = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def stage_cf(tmp_path: Path, *, account: str = CF_ID, allow: str = CF_ID, api_id: str | None = None) -> Path:
    """Sandbox with a fake `curl` answering the account-verification call with api_id (default:
    whatever account was configured), and a guarded probe script that records the exported id."""
    work = tmp_path / "infra"
    shutil.copytree(INFRA, work, ignore=shutil.ignore_patterns("tests", "__pycache__", "personal.env"))
    (work / "personal.env").write_text(
        f'CLOUDFLARE_API_TOKEN="tok-test"\nCLOUDFLARE_ACCOUNT_ID="{account}"\n'
        f'EPHEMERA_CF_ACCOUNT_IDS="{allow}"\n')
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    answer = api_id if api_id is not None else account
    curl = fake_bin / "curl"
    curl.write_text("#!/usr/bin/env bash\n"  # the guard's zone lookup: one zone owned by `answer`
                    f"echo '{{\"success\": true, \"result\": [{{\"id\": \"zone1\", \"account\": {{\"id\": \"{answer}\"}}}}]}}'\n")
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    probe = work / "probe_cf.sh"
    probe.write_text('#!/usr/bin/env bash\n. "$(dirname "${BASH_SOURCE[0]}")/guard_cf.sh"\n'
                     'echo "$CLOUDFLARE_ACCOUNT_ID" > "$(dirname "${BASH_SOURCE[0]}")/sentinel.txt"\n')
    return work


def test_cf_guard_passes_and_exports_for_the_allowlisted_account(tmp_path):
    work = stage_cf(tmp_path)
    r = run_probe(work, script="probe_cf.sh")
    assert r.returncode == 0, r.stderr
    assert (work / "sentinel.txt").read_text().strip() == CF_ID


def test_cf_guard_refuses_an_account_not_on_the_allowlist(tmp_path):
    work = stage_cf(tmp_path, account=CF_OTHER, allow=CF_ID)
    r = run_probe(work, script="probe_cf.sh")
    assert r.returncode == 1 and "REFUSED" in r.stderr and not (work / "sentinel.txt").exists()


def test_cf_guard_refuses_a_token_whose_zone_belongs_to_another_account(tmp_path):
    """The API answer is authoritative: a work token pasted by mistake dies here, before any write."""
    work = stage_cf(tmp_path, api_id=CF_OTHER)
    r = run_probe(work, script="probe_cf.sh")
    assert r.returncode == 1 and "cannot see the ephemera.space zone" in r.stderr
    assert not (work / "sentinel.txt").exists()


def test_cf_guard_refuses_empty_credentials(tmp_path):
    work = stage_cf(tmp_path)
    (work / "personal.env").write_text('CLOUDFLARE_API_TOKEN=""\nCLOUDFLARE_ACCOUNT_ID=""\nEPHEMERA_CF_ACCOUNT_IDS=""\n')
    r = run_probe(work, script="probe_cf.sh")
    assert r.returncode == 1 and "refusal" in r.stderr and not (work / "sentinel.txt").exists()
