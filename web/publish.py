#!/usr/bin/env python3
"""Build the site from the spool and publish it: commit the regenerated web/dist and push, which
triggers the push-to-deploy workflow. The committed dist is the publication of record - every
figure that was ever public is in git history (claims discipline made mechanical).

Run by the Ephemera-Ledger scheduled task (pythonw, no console) and by hand. Refuses to touch
anything but web/dist; if the push fails (offline, or the branch moved) it logs loudly and leaves
the commit for the next attempt - it never rebases or force-pushes on its own.
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
log = logging.getLogger("ephemera.publish")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, errors="replace")


def committed_cycle_count() -> int | None:
    """How many cycles the published ledger claims, from the last commit; None if there is none."""
    r = git("show", "HEAD:web/dist/ledger.json")
    if r.returncode != 0:
        return None
    try:
        return int(json.loads(r.stdout)["totals"]["cycles"])
    except (ValueError, KeyError, TypeError):
        return None


def built_cycle_count(dist: Path) -> int:
    return int(json.loads((dist / "ledger.json").read_text(encoding="utf-8"))["totals"]["cycles"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spool", type=Path, required=True)
    ap.add_argument("--no-push", action="store_true", help="build and commit only")
    ap.add_argument("--allow-shrink", action="store_true",
                    help="publish even if the built page holds fewer cycles than the published one")
    ap.add_argument("--log-file", type=Path, default=None)
    args = ap.parse_args(argv)
    handlers = [logging.FileHandler(args.log_file, encoding="utf-8")] if args.log_file else None
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)

    import build  # noqa: PLC0415 - sibling module
    # The output directory is stated, never defaulted: build.py's default is its own repository's
    # web/dist, and a test that pointed this module at a sandbox once let the build write an empty
    # site into the real tree, which was then committed and deployed.
    rc = build.main(["--spool", str(args.spool), "--out", str(REPO / "web" / "dist")])
    if rc != 0:
        log.error("build failed (rc %s) - nothing published", rc)
        return rc

    lint = subprocess.run([sys.executable, str(REPO / "tools" / "claims_lint.py"), str(REPO / "web" / "dist")],
                          capture_output=True, text=True)
    if lint.returncode != 0:
        log.error("claims lint FAILED on the built page - refusing to publish:\n%s", lint.stdout[-800:])
        return 1

    # An archive does not shrink. A build with fewer cycles than the one already published means
    # the spool was unreadable or the build was pointed somewhere empty, and publishing it would
    # tell the world the archive is gone. Refused unless the operator says the shrink is real.
    before, after = committed_cycle_count(), built_cycle_count(REPO / "web" / "dist")
    if before is not None and after < before and not args.allow_shrink:
        log.error("REFUSING to publish: the built page has %d cycles, the published one has %d. "
                  "If the archive really did shrink, rerun with --allow-shrink.", after, before)
        return 1

    git("add", "--", "web/dist")
    if not git("diff", "--cached", "--quiet", "--", "web/dist").returncode:
        log.info("no change in web/dist - nothing to publish")
        return 0
    # The pathspec is the point. This runs unattended every four hours on a machine where other
    # work is in progress, and a bare `git commit` takes the whole index with it: unfinished code,
    # or worse, something staged by accident. Only web/dist is ever published from here.
    c = git("commit", "--only", "-m", "ledger build\n\nAutomated site build from the spool "
                                      "(web/publish.py; the committed dist is the publication of record).\n\n"
                                      "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>",
            "--", "web/dist")
    if c.returncode != 0:
        log.error("commit failed: %s", (c.stderr or c.stdout)[-400:])
        return 1
    log.info("committed ledger build")
    if args.no_push:
        return 0
    p = git("push")
    if p.returncode != 0:
        log.error("push failed (will retry on the next run): %s", (p.stderr or p.stdout)[-400:])
        return 1
    log.info("pushed - the deploy workflow takes it from here")
    return 0


if __name__ == "__main__":
    sys.exit(main())
