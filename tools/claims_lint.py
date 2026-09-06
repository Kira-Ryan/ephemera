#!/usr/bin/env python3
"""Claims lint: fail when an outward document uses wording the claims register prohibits.

Rules come from the "Prohibited wording" section of DOCS/claims-register.md: every double-quoted
phrase in that section is a prohibited phrase. A phrase that appears in a scanned document inside
double quotes, backticks or *emphasis* is a *mention* (the README saying it is not "covariance
realism") and is allowed; an unquoted use is a violation. Two phrases, "confirms" and "refutes",
are only violations in a sentence that also talks about the FCC / SpaceX / manoeuvre figure, which
is the sense D04 prohibits. The register itself is never scanned.

In HTML there is no quoting-as-mention convention: attribute values and script string literals are
the page's own words, so only backticks and *emphasis* count as mentions there. Without that, the
whole of an interactive page's prose is invisible to this lint.

The register's "Required caveats" are checked as well, on the built home page and the globe: each
bullet must appear, whitespace-insensitive, or the build fails. A caveat that quietly stops being
rendered is a failure no amount of looking for bad words can catch.

A line carrying `<!-- lint:allow -->` is skipped: a deliberate mention that the quoting rule
cannot express. Use it sparingly and only for mentions, never for uses.

Usage: python tools/claims_lint.py [paths...]   (default: the outward documents listed below)
Exit 1 on any violation, listing file:line and the phrase. Exit 2 if no rules could be parsed -
an empty rule set must never pass silently.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REGISTER = REPO / "DOCS" / "claims-register.md"
# Outward artefacts only (the register's own scope): the rulebook under DOCS/ and the task ledger
# PLAN.md discuss the prohibited wording by name and are not scanned.
DEFAULT_TARGETS = ["README.md", "VERIFY.md", "archive/README.md", "probes", "web/dist", "bulletins"]
# Built pages that must each carry every required caveat, relative to a scanned directory.
ALLOW_MARKER = "<!-- lint:allow -->"   # a line carrying this is skipped (a deliberate mention)
CONTEXT_BOUND = {"confirms", "refutes"}
CONTEXT_WORDS = re.compile(r"\b(fcc|spacex|manoeuvre|maneuver|manoeuvres|maneuvers|declared|census|207,152)\b", re.I)


def load_rules(register: Path | None = None) -> list[str]:
    """Prohibited phrases = the double-quoted phrases in each bullet of the "Prohibited wording"
    section, up to the word "say" - what follows "say" in a bullet is the wording the register
    asks for instead (e.g. say "operator truth") and must not be treated as prohibited."""
    text = (register or REGISTER).read_text(encoding="utf-8")
    m = re.search(r"^## Prohibited wording\s*$(.*?)^## ", text, re.S | re.M)
    if not m:
        return []
    bullets = re.split(r"^- ", m.group(1), flags=re.M)[1:]
    phrases: set[str] = set()
    for b in bullets:
        flat = " ".join(b.split())
        cut = re.search(r"\bsay\b", flat)
        scope = flat[: cut.start()] if cut else flat
        phrases.update(p.strip() for p in re.findall(r'"([^"]+)"', scope) if p.strip())
    return sorted(phrases, key=len, reverse=True)


def load_required(register: Path | None = None) -> list[str]:
    """The bullets of the "Required caveats" section: the longest quoted span in each."""
    text = (register or REGISTER).read_text(encoding="utf-8")
    m = re.search(r"^## Required caveats[^\n]*$(.*?)^## ", text, re.S | re.M)
    if not m:
        return []
    out = []
    for b in re.split(r"^- ", m.group(1), flags=re.M)[1:]:
        quoted = re.findall(r'"([^"]+)"', " ".join(b.split()))
        if quoted:
            out.append(max(quoted, key=len))
    return out


def strip_mentions(line: str, html_mode: bool = False) -> str:
    """Blank out quoted / code / emphasised spans so a mention of a phrase is not a use of it.

    HTML has no quoting-as-mention convention: a double-quoted span there is an attribute value or a
    script string literal, which is the page speaking in its own voice. So in HTML only backticks and
    emphasis mark a mention, and a deliberate mention uses the allow marker."""
    if html_mode:
        # Backticks in HTML are JavaScript template literals, which is exactly where a page writes
        # its visible text; asterisks are multiplication. Neither marks a mention here.
        return line
    out = re.sub(r'"[^"\n]*"', lambda mm: " " * len(mm.group(0)), line)
    out = re.sub(r"`[^`\n]*`", lambda mm: " " * len(mm.group(0)), out)
    out = re.sub(r"\*[^*\n]+\*", lambda mm: " " * len(mm.group(0)), out)
    return out


def missing_caveats(root: Path, required: list[str]) -> list[tuple[Path, str]]:
    """Required caveats absent from a built page. Whitespace-insensitive, because the generator
    wraps prose wherever the template happens to break."""
    out = []
    # Every built page, wherever it sits. A fixed list of two paths was fine while the site was
    # two pages; a page added later would have shipped with no caveat check at all.
    for page in sorted(root.rglob("*.html")):
        if not page.is_file() or page.name.startswith("probe"):
            continue
        flat = " ".join(page.read_text(encoding="utf-8", errors="replace").split())
        for caveat in required:
            if " ".join(caveat.split()) not in flat:
                out.append((page, caveat))
    return out


def violations_in(path: Path, rules: list[str]) -> list[tuple[int, str, str]]:
    found = []
    for no, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if ALLOW_MARKER in raw:
            continue
        line = strip_mentions(raw, path.suffix.lower() == ".html")
        low = line.lower()
        for phrase in rules:
            pl = phrase.lower()
            if pl not in low:
                continue
            if pl in CONTEXT_BOUND and not CONTEXT_WORDS.search(raw):
                continue
            if not re.search(r"(?<![a-z])" + re.escape(pl) + r"(?![a-z])", low):
                continue
            found.append((no, phrase, raw.strip()))
    return found


def iter_files(targets: list[str]):
    for t in targets:
        p = REPO / t
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.suffix.lower() in (".md", ".html", ".txt") and f.resolve() != REGISTER.resolve():
                    yield f


def main(argv: list[str]) -> int:
    rules = load_rules()
    if not rules:
        print("claims_lint: no prohibited phrases parsed from the register - refusing to pass", file=sys.stderr)
        return 2
    targets = argv or DEFAULT_TARGETS
    required = load_required()
    if not required:
        print("claims_lint: no required caveats parsed from the register - refusing to pass", file=sys.stderr)
        return 2
    bad = 0
    for t in targets:
        root = Path(t) if Path(t).is_absolute() else REPO / t
        if not root.is_dir():
            continue
        for page, caveat in missing_caveats(root, required):
            bad += 1
            shown = page.relative_to(REPO) if page.resolve().is_relative_to(REPO) else page
            print(f'{shown}: MISSING required caveat: "{caveat[:90]}"')
    for f in iter_files(targets):
        if f.resolve() == REGISTER.resolve():
            continue
        shown = f.relative_to(REPO) if f.resolve().is_relative_to(REPO) else f
        for no, phrase, text in violations_in(f, rules):
            bad += 1
            print(f"{shown}:{no}: prohibited phrase \"{phrase}\": {text[:120]}")
    print(f"claims_lint: {len(rules)} prohibited phrases, {len(required)} required caveats, "
          f"{bad} violation(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
