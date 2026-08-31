# web/ - the static site

`dist/` is GENERATED: `web/build.py --spool <spool>` turns the poller's records (cycle.json,
witness.json, daily roots, the heartbeat history) into `dist/index.html` and `dist/ledger.json`.
Hand edits to `dist/` are overwritten by the next build - change `build.py`'s template instead.

The committed `dist/` is the publication of record: `web/publish.py` (run by the Ephemera-Ledger
scheduled task and by hand) builds, claims-lints the output, commits only `web/dist`, and pushes -
the push-to-deploy workflow serves it from Cloudflare Pages (D19). Every figure that was ever
public is therefore in git history. No server, no runtime inference (D08).

Rules the page obeys: every number carries the build's as-of time and the method note; a gapped
cycle is a loud red row, never a missing one; witnessing losses are printed with their reasons;
coverage shorter than its 24-hour window says "not yet measured" instead of a flattering partial
figure (D18). `web/tests/test_build.py` pins all of that from a synthetic spool containing every
uncomfortable state, checks the built page in a real browser, and runs the claims lint over the
output (also part of `make test`).
