"""The claims lint must fail on a prohibited use, pass on a quoted mention and on the register's own
recommended wording, and refuse to pass when it can parse no rules."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import claims_lint  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def test_rules_come_from_the_real_register_and_exclude_recommended_wording():
    rules = claims_lint.load_rules()
    assert "Covariance realism" in rules and "Ground truth" in rules and "confirms" in rules
    assert "operator truth" not in rules and "operator-published trajectory" not in rules


@pytest.mark.parametrize("text, expect", [
    ("The scoreboard measures covariance realism by lead time.", 1),          # use -> violation
    ('It is not "covariance realism"; it is self-consistency.', 0),          # quoted mention
    ("Scored against operator truth at common epochs.", 0),                  # recommended wording
    ("This confirms the FCC manoeuvre figure.", 1),                          # D04 sense
    ("The availability API confirms the capture exists.", 0),                # ordinary sense
    ("Ground truth for the satellites is the operator file.", 1),
    ("an operator transparency index is out of scope <!-- lint:allow -->", 0),
    ("The refutation was ground-truthed.", 0),                               # not the phrase
])
def test_violations(tmp_path, text, expect):
    f = tmp_path / "doc.md"
    f.write_text(text + "\n", encoding="utf-8")
    hits = claims_lint.violations_in(f, claims_lint.load_rules())
    assert len(hits) == expect, hits


def test_cli_fails_the_build_on_a_planted_phrase(tmp_path):
    """Mutation: make the CLI return 0 regardless -> this test goes red."""
    doc = tmp_path / "page.html"
    doc.write_text("<p>Our covariance realism score is 0.9.</p>\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(REPO / "tools" / "claims_lint.py"), str(doc)],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 1 and "Covariance realism" in r.stdout


def test_current_outward_documents_pass():
    r = subprocess.run([sys.executable, str(REPO / "tools" / "claims_lint.py")], capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout


def test_empty_rule_set_refuses_to_pass(tmp_path, monkeypatch):
    reg = tmp_path / "claims-register.md"
    reg.write_text("# Claims register\n\n## Something else\n\ntext\n", encoding="utf-8")
    monkeypatch.setattr(claims_lint, "REGISTER", reg)
    assert claims_lint.main([str(tmp_path)]) == 2


def test_html_attributes_and_script_strings_are_not_treated_as_mentions(tmp_path):
    """In Markdown a double-quoted phrase is a mention. In HTML it is an attribute value or a
    script literal, which is the page speaking. Mutation: drop the html_mode argument in
    violations_in and the second and third of these stop being reported."""
    md = tmp_path / "a.md"
    md.write_text('The project is not "an independent check of SpaceX\'s manoeuvre count".\n', encoding="utf-8")
    assert claims_lint.violations_in(md, claims_lint.load_rules()) == []

    page = tmp_path / "b.html"
    page.write_text(
        "<p>an independent check of SpaceX's manoeuvre count</p>\n"
        "<p title=\"an independent check of SpaceX's manoeuvre count\">x</p>\n"
        "<script>var s = \"an independent check of SpaceX's manoeuvre count\";</script>\n", encoding="utf-8")
    lines = [no for no, _, _ in claims_lint.violations_in(page, claims_lint.load_rules())]
    assert lines == [1, 2, 3], f"HTML prose, attribute and script must all be checked, got {lines}"


def test_required_caveats_are_parsed_and_asserted_on_built_pages(tmp_path):
    required = claims_lint.load_required()
    assert len(required) >= 4
    assert any(c.startswith("Operator ephemerides are predictions") for c in required)

    (tmp_path / "globe").mkdir()
    full = " ".join(required)
    (tmp_path / "index.html").write_text(f"<p>{full}</p>", encoding="utf-8")
    (tmp_path / "globe" / "index.html").write_text(f"<p>{full}</p>", encoding="utf-8")
    assert claims_lint.missing_caveats(tmp_path, required) == []

    # whitespace differences are fine; a dropped caveat is not
    (tmp_path / "index.html").write_text("<p>" + full.replace(required[0], "") + "</p>", encoding="utf-8")
    missing = claims_lint.missing_caveats(tmp_path, required)
    assert [c for _, c in missing] == [required[0]]

    # wrapped across lines, as the generator emits it, still counts as present
    wrapped = full.replace(" ", "\n  ", 3)
    (tmp_path / "index.html").write_text(f"<p>{wrapped}</p>", encoding="utf-8")
    assert claims_lint.missing_caveats(tmp_path, required) == []


def test_a_directory_missing_a_caveat_fails_the_run(tmp_path, capsys):
    (tmp_path / "index.html").write_text("<p>nothing required here</p>", encoding="utf-8")
    rc = claims_lint.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1 and "MISSING required caveat" in out


def test_javascript_template_literals_are_not_treated_as_mentions(tmp_path):
    """A page that writes its visible text from a template literal must still be checked.
    Mutation: restore the backtick strip in html_mode and this stops being reported."""
    page = tmp_path / "x.html"
    page.write_text("<script>el.innerHTML = `this is covariance realism`;</script>\n", encoding="utf-8")
    hits = [phrase for _, phrase, _ in claims_lint.violations_in(page, claims_lint.load_rules())]
    assert any("realism" in h.lower() for h in hits), hits
    # in Markdown a backticked span is still a mention
    md = tmp_path / "x.md"
    md.write_text("The register forbids `covariance realism` for this scoreboard.\n", encoding="utf-8")
    assert claims_lint.violations_in(md, claims_lint.load_rules()) == []
