# Claims register

Binding on every outward artefact: the site, bulletins, preprints, abstracts, emails to allies, and
any handout. Checked against each artefact before it goes out; the prohibitions will be asserted in
the site's browser tests so a regression cannot ship.

## Prohibited wording

- "Independent check of SpaceX's manoeuvre count", "confirms", "refutes", or any ratio of a detected
  quantity to the FCC figure. (D04)
- "Covariance realism" for the overlap scoreboard. (D05)
- "Anyone can re-fetch the inputs" or "reproducible from SpaceX" for anything older than one cycle.
  (D07)
- "Ground truth" for operator ephemerides. They are predictions; say "operator truth" or
  "operator-published trajectory", and say once per page that it is a prediction.
- "Every manoeuvre in the catalogue", "catalogue-wide detection".
- "Audit of 18 SDS", "operator transparency index", or any per-operator grade, until allies exist and
  the wording has been reviewed with them.
- "Validated", "human-validated", "playtested" for anything not yet validated by a named external
  party.
- Any precise figure without its as-of date and measurement method.

## Required caveats (once per page, verbatim or equivalent)

- "Operator ephemerides are predictions, not observations."
- "Starlink is the only operator with public covariance; other operators enter via CelesTrak SupGP
  without covariance." (until that changes)
- "Public GP data is too noisy to test sub-metre covariance; the self-consistency scoreboard measures
  prediction-versus-later-prediction."
- "Inputs are archived by this project and witnessed by OpenTimestamps and the Wayback Machine; they
  are not re-fetchable from the source after one cycle."
- Truth-health indicator on every scored day: file count received, poller uptime, mean element age,
  Space-Track status.

## Unverified as of 2026-08-30 (resolve in week one)

- SpaceX public-files terms of use (README states none; it describes the folder as "a mirror of the ephemeris files Starlink uploads to space-track.org"). Draft written `probes/p5_spacex_terms/email-draft.md`; rewritten 30 Aug 2026 so that it claims only what runs at send time. Request sent: *not yet*. Answer: *pending*.
- Whether CelesTrak will share or co-publish a SupGP / ephemeris history archive. Ask: *date*.
- Whether Space-Track's blanket redistribution approval covers bulk `gp_history` pulls at the stated
  rate limits (30 requests/min, 300/hour). Approval covers redistribution, not rate.
- Whether the header line `ephemeris_source:blend` is the only manoeuvre-content marker (checked on
  one file only).
- Cold-storage and egress cost: desk-priced 30 Aug 2026 for 0.82 and 1.32 TB/month
  (`probes/p4_cost/README.md`; S3 Deep Archive eu-west-1 ≈ USD 10–17/month at month 12); not yet
  compared against a real bill; Hetzner prices unverified.
- SpaceOps 2027 abstract deadline (STAR); UT Austin STC 2027 call date.
- The exact definition in SpaceX's 1 July 2026 semi-annual report (read the filing, not the press
  paraphrase, before any reconciliation note).

## Established 2026-08-30 (probes P1, P2)

- Conditional requests are supported: `ETag`, `Last-Modified`, and HTTP 304 on `If-None-Match`.
- Full-cycle pull projects to 45–116 min at 16 connections from a Cape Town residential link (116 from `curl` slices, 45–80 from the poller on 50- and 30-file runs; both in the P1 canonical table); no gain at 32. A sustained 11,099-file pull from a datacentre IP is not yet measured.
- Wayback Machine Save-Page-Now captures the manifest on demand (capture 20260829232117 exists).
- The OpenTimestamps client does not run on Windows (python-bitcoinlib / libssl); stamping runs on Linux.
- `celestrak.org` is unreachable (TCP timeout) from this machine's residential IP; `space-track.org` is reachable. See `probes/p3_six_digit/README.md`.

## Measurements to re-take before quoting

- Files per cycle (11,099 in the morning manifest; **17,861** in the 15:28 UTC manifest, 11,027
  distinct satellites), bytes per file (2,041,931 raw / ~821,000 gz), seconds per file from Cape
  Town on one connection (4.9 s) — all from 30 Aug 2026; the canonical table with methods is
  `probes/p1_cycle_pull/README.md`. Any per-cycle or per-month volume is a range (0.82–1.32 TB/month
  gzipped) until the watcher has recorded a day of cycles.
- June 2026 degradation figures (2.49 d mean element age; 4,366 of 10,684 beyond 30 km) — from
  CelesTrak history statistics as quoted by a third party; re-derive from CelesTrak directly.

## Corrections log

Every correction is appended here with date, what was wrong, and what replaced it. Nothing below
was public at the time; the entries exist so the first public version already carries its history.

- 2026-08-30 — Gzipped bytes per file was quoted as 848,660 in `DOCS/concept.md` and here; the only
  measurement in the repository is ~821,000 (`gzip -6`, one file, P1). Replaced everywhere; the
  derived monthly volume moves from ~0.85 to ~0.82 TB.
- 2026-08-30 — Seconds per file on one connection was quoted as 5.3 s in `DOCS/concept.md` and here;
  P1 measured 4,892 ms. Replaced; the sequential-pull projection moves from ~16 h to ~15 h.
- 2026-08-30 — The full-cycle projection appeared as three figures (116 / 45–80 / 80–116 min) across
  four documents. Replaced by the range 45–116 min with both measurements shown in the P1 table.
- 2026-08-30 — `README.md` said the request to SpaceX had been sent; it had not. Replaced with the
  drafted-not-sent status and this register as the place the send date will be recorded.
- 2026-08-30 — `README.md` said "no public archive exists" / "zero public archives"; a one-week
  public sample (25 Nov–1 Dec 2024, arXiv 2506.13034) exists and D06 relies on it. Replaced with
  "no continuous public archive".
- 2026-08-30 — `probes/p1_cycle_pull/README.md` said the residential IP was recorded in this
  register; it never was, by choice. Replaced with "deliberately not recorded".
- 2026-08-30 — The P5 email draft described a daily Merkle root, a hash chain, cold storage and DOIs
  in the present tense before any of them existed. Rewritten to state only what runs at send time.
