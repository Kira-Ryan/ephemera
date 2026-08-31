#!/usr/bin/env python3
"""PreToolUse hook: mechanical enforcement of the clean-room rule (D02, CLAUDE.md rule 1).

Denies any tool call whose target path lies under a *sibling* of this repository - another folder
under the same parent directory (GitHub/) - so an agent cannot open employer or client code. This
repository itself, and everything outside the parent directory (memory dirs, temp, home), are left
alone. Reads the hook JSON on stdin, prints a deny decision on stdout when a sibling is targeted,
prints nothing otherwise. Never raises: a hook crash would be a silent allow, so any parse failure is
treated as "no opinion" and logged to stderr.

Scope: this is a fence for the built-in tools and for paths that appear literally in shell commands.
It does not follow symlinks, `cd ..` chains or scripts that open files themselves.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # .claude/hooks/x.py -> repo root
PARENT = REPO.parent
SELF = REPO.name.lower()

PATH_FIELDS = ("file_path", "path", "notebook_path", "pattern")
COMMAND_FIELDS = ("command",)


def norm(p: str) -> str:
    """POSIX-ish lowercase form: backslashes to slashes, '/c/x' and 'c:/x' both become 'c:/x'."""
    s = p.replace("\\", "/").lower()
    m = re.match(r"^/([a-z])/(.*)$", s)
    if m:
        s = f"{m.group(1)}:/{m.group(2)}"
    return s


PARENT_N = norm(str(PARENT)).rstrip("/") + "/"


def sibling_of(path_text: str, cwd: str) -> str | None:
    """Return the sibling folder name if path_text resolves under a sibling of the repo, else None."""
    raw = path_text.strip().strip("\"'")
    if not raw:
        return None
    if not re.match(r"^([a-zA-Z]:[/\\]|[/\\])", raw):
        raw = os.path.join(cwd, raw)
    try:
        resolved = norm(os.path.normpath(raw))
    except (ValueError, OSError):
        return None
    if not resolved.startswith(PARENT_N):
        return None
    first = resolved[len(PARENT_N):].split("/", 1)[0]
    if not first or first == SELF:
        return None
    return first


def siblings_in_command(cmd: str) -> set[str]:
    """Sibling names for every absolute path under the parent directory that appears in a command."""
    hits: set[str] = set()
    esc = re.escape(PARENT_N.rstrip("/"))
    for m in re.finditer(esc + r"/([^/\\\s\"';|&)]+)", norm(cmd)):
        name = m.group(1)
        if name and name != SELF:
            hits.add(name)
    return hits


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as e:  # noqa: BLE001 - a crash here would silently allow; log and stand aside
        print(f"clean_room_guard: could not parse hook input: {e}", file=sys.stderr)
        return 0
    tool = payload.get("tool_name", "")
    inp = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()

    offenders: set[str] = set()
    for f in PATH_FIELDS:
        v = inp.get(f)
        if isinstance(v, str):
            s = sibling_of(v, cwd)
            if s:
                offenders.add(s)
    for f in COMMAND_FIELDS:
        v = inp.get(f)
        if isinstance(v, str):
            offenders |= siblings_in_command(v)

    if offenders:
        reason = (f"Clean-room rule D02: {tool} targets sibling repository "
                  f"{sorted(offenders)} under {PARENT}. Only {REPO.name} and its open-source "
                  f"dependencies may be read. See CLAUDE.md rule 1.")
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
