#!/usr/bin/env python3
"""Claims lint: fail when an outward document uses wording the claims register prohibits.

Rules come from the "Prohibited wording" section of DOCS/claims-register.md: every double-quoted
phrase in that section is a prohibited phrase. A phrase that appears in a scanned document inside
double quotes, backticks or *emphasis* is a *mention* (the README saying it is not "covariance
realism") and is allowed; an unquoted use is a violation. Two phrases, "confirms" and "refutes",
are only violations in a sentence that also talks about the FCC / SpaceX / manoeuvre figure, which
is the sense D04 prohibits. The register itself is never scanned.

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


def strip_mentions(line: str) -> str:
    """Blank out quoted / code / emphasised spans so a mention of a phrase is not a use of it."""
    out = re.sub(r'"[^"\n]*"', lambda mm: " " * len(mm.group(0)), line)
    out = re.sub(r"`[^`\n]*`", lambda mm: " " * len(mm.group(0)), out)
    out = re.sub(r"\*[^*\n]+\*", lambda mm: " " * len(mm.group(0)), out)
    return out


def violations_in(path: Path, rules: list[str]) -> list[tuple[int, str, str]]:
    found = []
    for no, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if ALLOW_MARKER in raw:
            continue
        line = strip_mentions(raw)
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
    bad = 0
    for f in iter_files(targets):
        if f.resolve() == REGISTER.resolve():
            continue
        shown = f.relative_to(REPO) if f.resolve().is_relative_to(REPO) else f
        for no, phrase, text in violations_in(f, rules):
            bad += 1
            print(f"{shown}:{no}: prohibited phrase \"{phrase}\": {text[:120]}")
    print(f"claims_lint: {len(rules)} rules, {bad} violation(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
