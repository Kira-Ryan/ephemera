"""The account guard (D02): a foreign AWS identity must stop a guarded script before it does
anything; only an allowlisted identity passes; a missing or empty allowlist refuses; no override
path exists in any of the four guards, including the two Python ones production runs; every infra
script actually sources the guard first (the call-site rule); the Cloudflare guard evaluates the
zone binding on a host that has python3 and no python; and the credential paths the VPS runbook
writes inside the checkout are ignored by git."""
from __future__ import annotations

import ast
import re
import shutil
import stat
import subprocess
import sys
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


def run_probe(work: Path, script: str = "probe.sh", *,
              hide_python: bool = False) -> subprocess.CompletedProcess:
    """Run a staged probe with the sandbox's fake bin first on PATH.

    hide_python drops every other PATH entry that provides a `python`, which is the shape of a
    stock Debian or Ubuntu host: python3 and no python. The VPS this project is moving to is that
    shape, and a developer machine that has both cannot otherwise exercise it."""
    import os
    env = dict(os.environ)
    rest = env["PATH"].split(os.pathsep)
    if hide_python:
        rest = [p for p in rest if p and not shutil.which("python", path=p)]
    env["PATH"] = os.pathsep.join([str(work.parent / "bin"), *rest])
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


# `(?<![a-z])` stops `enforce`, the entry point of both Python guards, from matching on `force`.
OVERRIDE = re.compile(r"(?i)(?<![a-z])(override|force|skip[_-]?guard|EPHEMERA_GUARD_DISABLE)")

# Every module outside infra/tests that calls a Python guard, as of 13 Sep 2026.
GUARDED_ENTRY_POINTS = {"archive/ship.py", "infra/cf_site.py", "infra/cf_traffic.py",
                        "infra/s3_bucket.py"}


def executable_source(path: Path) -> str:
    """The file with its comments, and for Python its docstrings, taken out.

    Both Python guards say in prose that they have no override flag. Searching a guard's own
    documentation for the word would make the test below pass on the sentence rather than on the
    code, which is the shape of failure it exists to catch."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if path.suffix == ".py":
        for node in ast.walk(ast.parse("\n".join(lines))):
            body = getattr(node, "body", None)
            if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            first = body[0] if body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                for i in range(first.lineno - 1, first.end_lineno):
                    lines[i] = ""
    return "\n".join(l for l in lines if not l.strip().startswith("#"))


def test_guards_have_no_override_path():
    """All four guards. The shell pair is what a person runs by hand; guard.py and guard_cf.py are
    what production runs (archive/ship.py, infra/s3_bucket.py, infra/cf_site.py, infra/cf_traffic.py),
    and they were not covered here at all."""
    for name in ("guard.sh", "guard_cf.sh", "guard.py", "guard_cf.py"):
        assert not OVERRIDE.search(executable_source(INFRA / name)), name


def test_production_call_sites_pass_no_arguments_to_the_python_guards():
    """The Python guards take injection parameters so the tests can drive them - enforce(env,
    identity) at guard.py:43, enforce(opener) at guard_cf.py:81. Passing one is also the only way to
    make either guard return without asking STS or Cloudflare anything, so a word search of the
    guards proves nothing about them; what is worth pinning is that no production entry point passes
    one, which leaves every real run on the defaulted path the other tests cover.

    Parsed, not grepped: cf_site.py's module docstring names guard_cf.enforce() in prose and a grep
    would count that as a call site. The >= keeps the test from passing on an empty search.

    Mutation: give any of these call sites an argument and this goes red."""
    found: dict[str, int] = {}
    for area in ("archive", "infra", "score", "tools", "web"):
        for py in sorted((REPO / area).rglob("*.py")):
            rel = py.relative_to(REPO).as_posix()
            if "/tests/" in rel or "__pycache__" in rel:
                continue
            for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "enforce"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id in ("guard", "guard_cf")):
                    found[f"{rel}:{node.lineno}"] = len(node.args) + len(node.keywords)
    assert {k.split(":")[0] for k in found} >= GUARDED_ENTRY_POINTS, found
    assert all(n == 0 for n in found.values()), found


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
INTERPRETER_LOG = "interpreter-calls.txt"


def interpreter_ran(tmp_path: Path) -> bool:
    """Whether guard_cf.sh actually invoked the interpreter shim stage_cf() put on PATH."""
    return (tmp_path / INTERPRETER_LOG).exists()


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
    # The guard reads the zone answer with an interpreter, and it must find one under the name a
    # stock Debian or Ubuntu host actually provides. This shim is named python3 only, and it appends
    # to INTERPRETER_LOG before handing over to the real interpreter, so a refusal that never read
    # the answer can be told apart from one that read it and disagreed with it.
    py3 = fake_bin / "python3"
    py3.write_text("#!/usr/bin/env bash\n"
                   f'echo "called" >> "{(tmp_path / INTERPRETER_LOG).as_posix()}"\n'
                   f'exec "{Path(sys.executable).as_posix()}" "$@"\n')
    py3.chmod(py3.stat().st_mode | stat.S_IEXEC)
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
    """The API answer is authoritative: a work token pasted by mistake dies here, before any write.

    The last two assertions are what stop this passing for the wrong reason. The guard used to call
    a bare `python`, which a stock Ubuntu host does not have; the shell's exit 127 was caught by the
    zone check's own || block and printed the same refusal, so this test was green on a host where
    the zone was never looked at. A missing interpreter cannot run the shim and cannot print an
    account id that only exists inside the fake curl's answer."""
    work = stage_cf(tmp_path, api_id=CF_OTHER)
    r = run_probe(work, script="probe_cf.sh")
    assert r.returncode == 1
    assert not (work / "sentinel.txt").exists()
    assert interpreter_ran(tmp_path), f"the zone answer was never read: {r.stderr}"
    assert CF_OTHER in r.stderr and "belongs to account" in r.stderr, r.stderr


def test_the_cf_guard_runs_on_a_host_that_has_python3_and_no_python(tmp_path):
    """The shape of the VPS this project is moving to (DOCS/migration-runbook.md:101, Ubuntu 24.04).

    Mutation: put the bare `python` back in guard_cf.sh and this goes red - the interpreter is never
    reached, the zone binding is never evaluated, and the guard refuses a run it should have passed."""
    work = stage_cf(tmp_path)
    r = run_probe(work, script="probe_cf.sh", hide_python=True)
    assert r.returncode == 0, r.stderr
    assert interpreter_ran(tmp_path), f"the zone answer was never read: {r.stderr}"
    assert (work / "sentinel.txt").read_text().strip() == CF_ID


def test_a_zone_answer_the_interpreter_cannot_read_is_a_refusal(tmp_path):
    """The guard reads the owning account out of the answer rather than exiting on a comparison
    inside the interpreter, so a body that will not parse has to refuse on its own account instead
    of leaving _owner empty and falling into a message about a token that cannot see the zone."""
    work = stage_cf(tmp_path)
    (tmp_path / "bin" / "curl").write_text("#!/usr/bin/env bash\necho 'not json at all'\n")
    r = run_probe(work, script="probe_cf.sh")
    assert r.returncode == 1 and "could not read the Cloudflare zone answer" in r.stderr, r.stderr
    assert not (work / "sentinel.txt").exists()


def test_cf_guard_refuses_empty_credentials(tmp_path):
    work = stage_cf(tmp_path)
    (work / "personal.env").write_text('CLOUDFLARE_API_TOKEN=""\nCLOUDFLARE_ACCOUNT_ID=""\nEPHEMERA_CF_ACCOUNT_IDS=""\n')
    r = run_probe(work, script="probe_cf.sh")
    assert r.returncode == 1 and "refusal" in r.stderr and not (work / "sentinel.txt").exists()


# DOCS/migration-runbook.md puts the checkout at /opt/ephemera and points the units at an
# AWS_CONFIG_FILE and a GIT_SSH_COMMAND identity by absolute path. It now recommends keeping both
# outside the checkout, but these are where a reader following an older draft, or anyone working by
# hand on the host, would put them: inside it, relative to the repository root. .aws/credentials is
# the file boto3 reads beside that config.
RUNBOOK_CREDENTIAL_PATHS = (".aws/config", ".aws/credentials", ".ssh/id_ed25519",
                            ".ssh/known_hosts")


def test_the_runbooks_credential_paths_are_ignored_by_git():
    """Those paths are inside the checkout and this repository is public, so an untracked-files
    listing that shows them is one `git add` away from publishing a credential.

    Asked of git rather than read out of .gitignore: .gitignore already carries a negation for
    web/dist, and a later one can undo a pattern that is still sitting in the file.

    Mutation: drop /.aws/ or /.ssh/ from .gitignore and this goes red."""
    git = shutil.which("git") or pytest.skip("git not on PATH")
    for rel in RUNBOOK_CREDENTIAL_PATHS:
        r = subprocess.run([git, "check-ignore", "-v", rel], cwd=REPO, capture_output=True, text=True)
        assert r.returncode == 0, f"{rel} is not ignored by git: {r.stdout}{r.stderr}"
