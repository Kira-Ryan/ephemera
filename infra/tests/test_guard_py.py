"""infra/guard.py must refuse exactly what guard.sh refuses: missing file, empty allowlist, missing
profile, forbidden (employer) account even if allowlisted, unlisted account, failed identity - and
it must pin AWS_PROFILE before asking for the identity."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guard  # noqa: E402

PERSONAL, EMPLOYER, OTHER = "111111111111", "222222222222", "999999999999"
GOOD = {"EPHEMERA_AWS_PROFILE": "personal", "EPHEMERA_AWS_ACCOUNT_IDS": PERSONAL,
        "EPHEMERA_AWS_FORBIDDEN_IDS": EMPLOYER}


@pytest.fixture(autouse=True)
def _clean_profile(monkeypatch):
    monkeypatch.delenv("AWS_PROFILE", raising=False)


def test_allowlisted_identity_passes_and_profile_is_pinned_first():
    seen = {}

    def identity():
        seen["profile_at_call"] = os.environ.get("AWS_PROFILE")
        return PERSONAL

    assert guard.enforce(GOOD, identity) == {"profile": "personal", "account": PERSONAL}
    assert seen["profile_at_call"] == "personal"      # pinned BEFORE the identity call


def test_forbidden_wins_over_allowlist():
    env = dict(GOOD, EPHEMERA_AWS_ACCOUNT_IDS=f"{EMPLOYER} {PERSONAL}")
    with pytest.raises(guard.GuardRefused, match="FORBIDDEN"):
        guard.enforce(env, lambda: EMPLOYER)


def test_unlisted_account_is_refused():
    with pytest.raises(guard.GuardRefused, match="not on the personal allowlist"):
        guard.enforce(GOOD, lambda: OTHER)


def test_empty_allowlist_and_missing_profile_refuse():
    with pytest.raises(guard.GuardRefused, match="empty allowlist"):
        guard.enforce(dict(GOOD, EPHEMERA_AWS_ACCOUNT_IDS=""), lambda: PERSONAL)
    with pytest.raises(guard.GuardRefused, match="EPHEMERA_AWS_PROFILE is empty"):
        guard.enforce(dict(GOOD, EPHEMERA_AWS_PROFILE=""), lambda: PERSONAL)


def test_identity_failure_is_a_refusal_not_a_pass():
    def boom():
        raise ConnectionError("no network")

    with pytest.raises(guard.GuardRefused, match="could not establish"):
        guard.enforce(GOOD, boom)


def test_env_file_parsing_and_missing_file(tmp_path):
    p = tmp_path / "personal.env"
    p.write_text('# comment\nEPHEMERA_AWS_PROFILE="latentsky"\nEPHEMERA_AWS_ACCOUNT_IDS="1 2"\nX=3\n')
    env = guard.load_env(p)
    assert env == {"EPHEMERA_AWS_PROFILE": "latentsky", "EPHEMERA_AWS_ACCOUNT_IDS": "1 2", "X": "3"}
    with pytest.raises(guard.GuardRefused, match="missing"):
        guard.load_env(tmp_path / "nope.env")


def test_no_override_path_in_source():
    body = "\n".join(l for l in (Path(guard.__file__).read_text().splitlines())
                     if not l.strip().startswith("#"))
    import re
    assert not re.search(r"(?i)override|skip[_-]?guard|EPHEMERA_GUARD_DISABLE", body)
