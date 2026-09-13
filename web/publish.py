#!/usr/bin/env python3
"""Build the site from the spool and publish it: fast-forward onto whatever origin already
publishes, commit the regenerated web/dist and push, which triggers the push-to-deploy workflow.
The committed dist is the publication of record - every figure that was ever public is in git
history (claims discipline made mechanical).

Run by the Ephemera-Ledger scheduled task (pythonw, no console) and by hand. Refuses to touch
anything but web/dist. It never merges, rebases or force-pushes: a clone that cannot reach its
upstream, or whose branch has diverged from it because a second host is publishing its own build
of the same spool, refuses to build at all and says why. web/dist is a build product, so two
hosts' builds of one spool are not two halves of one change; reconciling them by rebase would
publish an interleaving neither host ever built. If the push itself fails, the commit is left for
the next run.
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Where the sibling modules live, resolved once at import. REPO is redirected by the tests to a
# throwaway repository, and the code to import does not move with it.
INFRA = Path(__file__).resolve().parents[1] / "infra"
log = logging.getLogger("ephemera.publish")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, errors="replace")


def ledger_cycle_count(ref: str) -> int | None:
    """How many cycles the ledger committed at this git ref claims; None if that ref has no
    readable ledger.json."""
    r = git("show", f"{ref}:web/dist/ledger.json")
    if r.returncode != 0:
        return None
    try:
        return int(json.loads(r.stdout)["totals"]["cycles"])
    except (ValueError, KeyError, TypeError):
        return None


def upstream_ref() -> str | None:
    """The remote-tracking branch this clone pushes to and reads the published state from, e.g.
    'origin/main'. None when the branch tracks nothing, which is a repository with no remote: there
    is nothing to be behind of, and `git push` would have nowhere to go either."""
    r = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.strip()


def sync_with_published() -> tuple[int, str | None]:
    """Make this clone contain everything origin publishes, or refuse to build at all.

    Returns (0, upstream) when the build may go ahead and (1, upstream) when it may not. Fetches,
    then: a branch strictly behind its upstream is fast-forwarded, which moves the branch pointer
    and nothing else because there is nothing local to replay; a branch that is both ahead and
    behind is a second publisher pushing its own build, and is refused rather than reconciled; a
    clone that cannot fetch does not know what is published, so it does not build. Called before
    the build, so a refusal leaves web/dist exactly as it was and costs a cycle of nothing.
    """
    inside = git("rev-parse", "--is-inside-work-tree")
    if inside.returncode != 0:
        log.error("REFUSING to build: git will not operate on %s (%s). Nothing could be committed "
                  "and there is no published state to compare the build against.",
                  REPO, (inside.stderr or inside.stdout).strip()[-200:])
        return 1, None

    upstream = upstream_ref()
    if upstream is None:
        log.info("this branch tracks no upstream - building against this clone's own history only")
        return 0, None

    f = git("fetch")
    if f.returncode != 0:
        log.error("REFUSING to build: could not fetch %s, so this clone cannot tell what is "
                  "published: %s", upstream, (f.stderr or f.stdout)[-400:])
        return 1, upstream

    r = git("rev-list", "--left-right", "--count", f"{upstream}...HEAD")
    if r.returncode != 0:
        log.error("REFUSING to build: could not compare HEAD with %s: %s",
                  upstream, (r.stderr or r.stdout)[-400:])
        return 1, upstream
    behind, ahead = (int(n) for n in r.stdout.split())

    if behind and ahead:
        log.error("REFUSING to build: this clone and %s have diverged - %d commit(s) published "
                  "there are not here, and %d local commit(s) are not published. That is a second "
                  "publisher building the same spool, which is a fault to settle by hand: this "
                  "script never merges, rebases or force-pushes. Check that one host only runs the "
                  "ledger, then reconcile this branch.", upstream, behind, ahead)
        return 1, upstream
    if behind:
        # web/dist is generated and the build rewrites it a few lines later, so a copy left dirty
        # by a run that refused after building must not be the thing that stops this clone taking
        # what origin published. The pathspec keeps the restore off everything else in the tree,
        # and its own failure is not fatal: if the tree still blocks the fast-forward, the merge
        # below prints why.
        git("checkout", "HEAD", "--", "web/dist")
        m = git("merge", "--ff-only", upstream)
        if m.returncode != 0:
            log.error("REFUSING to build: %d commit(s) published on %s are missing here and the "
                      "fast-forward onto them failed: %s",
                      behind, upstream, (m.stderr or m.stdout)[-400:])
            return 1, upstream
        log.info("fast-forwarded %d commit(s) published on %s", behind, upstream)
    return 0, upstream


def publish_packs(spool: Path) -> tuple[int, str | None]:
    """Put every globe pack in object storage and return the base URL the build should record.

    (0, url) when they are published, (0, None) when no object storage is configured, and non-zero
    when it is configured and the upload failed. That last case deliberately stops the publish
    rather than falling back to copying the pack into the site: the fallback would put a 5.2 MB blob
    back into web/dist and therefore into git, which is the thing moving the packs to R2 removed.
    The site keeps serving its previous build until the storage comes back, which is loud and
    recoverable, where a silent 3 GB a year is neither."""
    sys.path.insert(0, str(INFRA))
    import r2_packs  # noqa: PLC0415 - optional, and only on the host that publishes

    try:
        env = r2_packs.settings()
    except r2_packs.R2Refused as e:
        log.info("globe packs stay in the site: %s", e)
        return 0, None
    r = r2_packs.sync(spool)
    if r["failed"]:
        log.error("globe pack upload failed for %d of %d - nothing published", len(r["failed"]), r["local"])
        for f in r["failed"]:
            log.error("  %s", f)
        return 1, None
    log.info("globe packs: %d uploaded, %d already published", len(r["uploaded"]), len(r["skipped"]))
    return 0, r2_packs.public_url(env, "").rsplit("/", 1)[0] + "/"


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

    # Before the build, because a commit made on a branch that is behind origin cannot be pushed,
    # and because the shrink guard below is only a guard if the ledger it compares against is the
    # one the world is being served.
    rc, upstream = sync_with_published()
    if rc != 0:
        return rc

    # The packs go up before the build, because the build records their URLs and must never
    # record a URL for an object that is not there yet.
    rc, pack_base = publish_packs(args.spool)
    if rc != 0:
        return rc

    import build  # noqa: PLC0415 - sibling module
    # The output directory is stated, never defaulted: build.py's default is its own repository's
    # web/dist, and a test that pointed this module at a sandbox once let the build write an empty
    # site into the real tree, which was then committed and deployed.
    rc = build.main(["--spool", str(args.spool), "--out", str(REPO / "web" / "dist")]
                    + (["--pack-base-url", pack_base] if pack_base else []))
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
    # The baseline is the larger of what origin publishes and what this clone has already
    # committed, because a successful push makes both of them public. Reading HEAD alone let a
    # clone that was behind origin measure itself against a stale published count and pass, and
    # reading the upstream alone misses a build committed here and not yet pushed. The two halves
    # can only differ one way: sync_with_published() has already put everything origin published
    # into HEAD, so HEAD is never the older history, but a commit made here after that can hold
    # fewer cycles than origin still serves - which is what one --allow-shrink run whose push
    # failed, or which was told not to push, leaves for the next run to measure itself against.
    counts = [c for c in (ledger_cycle_count(upstream) if upstream else None,
                          ledger_cycle_count("HEAD")) if c is not None]
    before, after = (max(counts) if counts else None), built_cycle_count(REPO / "web" / "dist")
    if before is not None and after < before and not args.allow_shrink:
        log.error("REFUSING to publish: the built page has %d cycles, the archive already "
                  "published or committed holds %d. If the archive really did shrink, rerun with "
                  "--allow-shrink.", after, before)
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
