# web/ - the static site

`dist/` is GENERATED: `web/build.py --spool <spool>` turns the poller's records (cycle.json,
witness.json, daily roots, the heartbeat history, the scored reports) into `dist/ledger.json` and
the pages of D20: the front page, `finding/`, `scored/`, `archive/`, `check/`, `globe/` and
`404.html`. `build.py` assembles the ledger; `pages.py` renders every page from it and owns the
stylesheet, the tab bar, the figures and the month sections; `brand.py` draws the mark and icons.
Hand edits to `dist/` are overwritten by the next build, and any HTML under `dist/` the build did
not write is removed, so a retired page cannot keep shipping with a frozen stamp. Change
`pages.py` instead. The globe keeps its own full-screen page under `web/globe/`; the build injects
the shared masthead and tab bar in place of the `<!-- ephemera:chrome -->` marker.

The committed `dist/` is the publication of record: `web/publish.py` (run by the Ephemera-Ledger
scheduled task and by hand) builds, claims-lints the output, commits only `web/dist`, and pushes -
the push-to-deploy workflow serves it from Cloudflare Pages (D19). Every figure that was ever
public is therefore in git history. No server, no runtime inference (D08).

Rules the page obeys: every number carries the build's as-of time and the method note; a gapped
cycle is a loud red row, never a missing one; witnessing losses are printed with their reasons;
coverage shorter than its 24-hour window says "not yet measured" instead of a flattering partial
figure (D18). The tables that grow, one row per cycle, live on their own pages (`scored/`,
`archive/`) in month sections with an only-defects toggle; row ids `s-<sha12>` and `c-<sha12>`
never move, so a link to a row keeps working as the archive grows (D20). `web/tests/test_build.py`
and `test_build_visibility.py` pin the printed truths from a synthetic spool containing every
uncomfortable state, `test_pages.py` pins the page map, canonicals, tab state, pruning and the
layout at phone, laptop and desktop widths in a real browser, and the claims lint runs over every
built page (all part of `make test`).
