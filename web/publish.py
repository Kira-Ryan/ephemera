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
import logging
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
log = logging.getLogger("ephemera.publish")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, errors="replace")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spool", type=Path, required=True)
    ap.add_argument("--no-push", action="store_true", help="build and commit only")
    ap.add_argument("--log-file", type=Path, default=None)
    args = ap.parse_args(argv)
    handlers = [logging.FileHandler(args.log_file, encoding="utf-8")] if args.log_file else None
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)

    import build  # noqa: PLC0415 - sibling module
    rc = build.main(["--spool", str(args.spool)])
    if rc != 0:
        log.error("build failed (rc %s) - nothing published", rc)
        return rc

    lint = subprocess.run([sys.executable, str(REPO / "tools" / "claims_lint.py"), str(REPO / "web" / "dist")],
                          capture_output=True, text=True)
    if lint.returncode != 0:
        log.error("claims lint FAILED on the built page - refusing to publish:\n%s", lint.stdout[-800:])
        return 1

    git("add", "web/dist")
    if not git("diff", "--cached", "--quiet", "--", "web/dist").returncode:
        log.info("no change in web/dist - nothing to publish")
        return 0
    c = git("commit", "-m", "ledger build\n\nAutomated site build from the spool "
                            "(web/publish.py; the committed dist is the publication of record).\n\n"
                            "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>")
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
