"""requirements.txt has to describe what a clean machine actually needs.

It drifted: a patch wrote a literal backslash-n into it, and four packages the code imports
(boto3, moto, skyfield, sgp4) were never declared, so a fresh clone could not run the gate the
README points at. This walks the repo's own imports rather than trusting a list.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REQ = REPO / "requirements.txt"

# Import names that are not distribution names, and the distribution that provides them.
PROVIDED_BY = {"PIL": "pillow", "yaml": "pyyaml"}
# Directories that are not part of what a clean machine has to run.
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "web/dist", "data"}


def declared() -> dict[str, str]:
    out = {}
    for line in REQ.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split("==")[0].split(">=")[0].split("<")[0].strip()
        out[name.lower()] = line
    return out


def imported() -> set[str]:
    names: set[str] = set()
    for path in REPO.rglob("*.py"):
        rel = path.relative_to(REPO).as_posix()
        if any(rel.startswith(d) or f"/{d}/" in f"/{rel}" for d in SKIP_DIRS):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def third_party(names: set[str]) -> set[str]:
    local = {p.stem for p in REPO.rglob("*.py")} | {p.name for p in REPO.iterdir() if p.is_dir()}
    return {n for n in names
            if n not in sys.stdlib_module_names and n not in local and not n.startswith("_")}


def test_no_stray_escape_sequence_survived_a_patch():
    text = REQ.read_text(encoding="utf-8")
    assert "\\n" not in text, "a literal backslash-n is in requirements.txt, so pip cannot parse it"
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            assert any(op in stripped for op in ("==", ">=", "<")), f"unpinned or malformed line: {line!r}"


def test_every_third_party_import_in_the_repo_is_declared():
    """Mutation: delete the boto3 or skyfield line and this goes red."""
    missing = sorted(m for m in third_party(imported())
                     if PROVIDED_BY.get(m, m).lower() not in declared())
    assert not missing, f"imported but not in requirements.txt: {missing}"


def test_the_declared_set_is_importable_here():
    """The pins describe the environment the suite was actually run against."""
    import importlib.metadata as md

    for name in declared():
        md.version(name)          # raises PackageNotFoundError if the pin names nothing real
