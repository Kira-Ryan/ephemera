"""The Cloudflare guard for Python entry points.

The shell guard only runs where personal.env exists. The deploy workflow runs on a GitHub runner
with two secrets and no personal.env, so it called the deploy client directly and no guard ran at
all. These tests cover the rules that replace it, and that the deploy client cannot be run without
them.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "infra"))
import guard_cf  # noqa: E402


class FakeZones:
    """Stands in for the Cloudflare zones endpoint."""

    def __init__(self, account: str | None, success: bool = True):
        self.account, self.success = account, success

    def __call__(self, req, timeout=None):
        body = {"success": self.success,
                "result": ([{"account": {"id": self.account}}] if self.account else [])}
        return io.BytesIO(json.dumps(body).encode())

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener(account: str | None, success: bool = True):
    def _open(req, timeout=None):
        body = {"success": success, "result": ([{"account": {"id": account}}] if account else [])}
        return io.BytesIO(json.dumps(body).encode())
    return _open


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for v in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "EPHEMERA_CF_ACCOUNT_IDS"):
        monkeypatch.delenv(v, raising=False)
    # never read the developer's real personal.env during a test
    monkeypatch.setattr(guard_cf, "_load_personal_env", lambda: {})
    yield


def test_the_zone_must_belong_to_the_account_being_used(monkeypatch):
    """The rule that does the work on a runner: a token for another account cannot see this zone.

    Mutation: return without comparing owner to account and this goes red."""
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "personal-account")
    assert guard_cf.enforce(opener("personal-account")) == "personal-account"

    with pytest.raises(guard_cf.GuardRefused, match="belongs to account"):
        guard_cf.enforce(opener("some-employer-account"))


def test_a_token_that_cannot_see_the_zone_is_refused(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "personal-account")
    with pytest.raises(guard_cf.GuardRefused, match="cannot see"):
        guard_cf.enforce(opener(None))


def test_an_unreachable_api_means_no_action(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "personal-account")

    def boom(req, timeout=None):
        raise OSError("network down")

    with pytest.raises(guard_cf.GuardRefused, match="unreachable"):
        guard_cf.enforce(boom)


def test_missing_credentials_are_refused(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    with pytest.raises(guard_cf.GuardRefused, match="must both be set"):
        guard_cf.enforce(opener("personal-account"))


def test_the_allowlist_is_enforced_when_one_is_available(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "personal-account")
    monkeypatch.setenv("EPHEMERA_CF_ACCOUNT_IDS", "another-account")
    with pytest.raises(guard_cf.GuardRefused, match="not on the allowlist"):
        guard_cf.enforce(opener("personal-account"))

    monkeypatch.setenv("EPHEMERA_CF_ACCOUNT_IDS", "another-account personal-account")
    assert guard_cf.enforce(opener("personal-account")) == "personal-account"


def test_an_empty_allowlist_in_personal_env_is_a_refusal(monkeypatch):
    """guard_cf.sh treats an empty allowlist as a refusal, never a pass, and so does this."""
    monkeypatch.setattr(guard_cf, "_load_personal_env",
                        lambda: {"CLOUDFLARE_API_TOKEN": "t", "CLOUDFLARE_ACCOUNT_ID": "a",
                                 "EPHEMERA_CF_ACCOUNT_IDS": ""})
    with pytest.raises(guard_cf.GuardRefused, match="empty"):
        guard_cf.enforce(opener("a"))


def test_an_unset_secret_is_absent_rather_than_empty(monkeypatch):
    """An unset GitHub secret arrives as an empty string. Treating that as an empty allowlist would
    refuse every deploy, so in the environment empty means absent and the zone binding stands
    alone. personal.env keeps the stricter reading, which the test above covers."""
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "personal-account")
    monkeypatch.setenv("EPHEMERA_CF_ACCOUNT_IDS", "")
    assert guard_cf.enforce(opener("personal-account")) == "personal-account"


def test_the_deploy_client_runs_the_guard_before_anything_else():
    """Mutation: remove the enforce() call from cf_site.py's entry point and this goes red.

    Run as a subprocess with credentials that cannot pass, so if the guard is skipped the client
    proceeds to a real API call instead of refusing."""
    r = subprocess.run([sys.executable, str(REPO / "infra" / "cf_site.py"), "deploy"],
                       capture_output=True, text=True, cwd=REPO,
                       env={"PATH": "", "SYSTEMROOT": "C:\\\\Windows",
                            "CLOUDFLARE_API_TOKEN": "definitely-not-a-token",
                            "CLOUDFLARE_ACCOUNT_ID": "definitely-not-an-account",
                            "EPHEMERA_CF_ACCOUNT_IDS": "some-other-account"})
    assert r.returncode != 0
    assert "guard_cf: REFUSED" in (r.stdout + r.stderr), (r.stdout + r.stderr)[-500:]


def test_the_workflow_pins_its_dependency_and_installs_it_away_from_the_secrets():
    """An unpinned `pip install` in the step that holds the deploy token takes whatever was
    published that morning and runs it beside a credential."""
    wf = (REPO / ".github" / "workflows" / "deploy-site.yml").read_text(encoding="utf-8")
    install = wf.index("Install the deploy dependency")
    deploy = wf.index("Deploy web/dist via the Pages direct-upload API")
    assert install < deploy, "the dependency is installed in the step that holds the secrets"
    assert "pip install -q blake3\n" not in wf, "blake3 is installed unpinned"
    assert "grep -E '^blake3==' requirements.txt" in wf, "the pin is not taken from requirements.txt"
    secret_step = wf[deploy:]
    assert "pip install" not in secret_step, "a pip install still runs in the secret-bearing step"
