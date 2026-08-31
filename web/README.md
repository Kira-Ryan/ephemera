# web/ - the static site

`dist/` is what gets deployed (Cloudflare Pages, personal account - D19). For now `dist/index.html`
is a hand-written placeholder; once the ledger and scoreboard exist, `dist/` becomes build output
and hand edits stop. No server, no runtime inference (D08). Every page here is an outward artefact:
the claims lint scans `web/dist` as part of `make test`, and the Playwright claims tests (PLAN item
10) will assert the register's rules against the built pages in a real browser.
