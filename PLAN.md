# Ephemera — build plan and progress

Agent-maintained task ledger. Decisions live in `DOCS/decisions.md`; this file only tracks work.
Status marks: `[ ]` not started · `[~]` in progress · `[x]` done (with date) · `[!]` blocked (with what on).

Accepted defaults (owner, 30 Aug 2026): personal AWS account (Latent Sky's, guarded by ID) for
buckets/CDN only; pollers on non-AWS VPSs; storage tier decided after P4; D11 `cycle_<sha12>`;
D12 root.txt = 64 hex + LF; archive.org account for SPN2; repo private until Kelso + IP clause.
**D01 accepted 31 Aug**: name Ephemera, domain `ephemera.space` registered on the personal
Cloudflare account.

## Day 0 — 30 Aug 2026

- [x] **0. Commit + push to a private remote** (31 Aug). `main` at **github.com/Kira-Ryan/ephemera**
      (private; personal account confirmed). Per-repo author identity `Kira Ryan
      <kiraryan27@gmail.com>` — the employer address stays out of the history. `.gitattributes`
      keeps the P2 evidence byte-exact (autocrlf had silently LF-normalised the stamped CRLF
      root.txt in the first commit; the committed bytes now hash to the OTS-committed digest).
- [x] **1. Start capturing from home** (agent, stable from 30 Aug 15:40 UTC). `archive/run_cycle.py`
      running as the Windows scheduled task `Ephemera-Watcher` under `pythonw.exe` (at logon, no
      console window; `--log-file Z:\ephemera\run_cycle.log`; spool `Z:\ephemera\spool`, 1.18 TB
      free). Two earlier starts (15:32, 15:37) opened visible console windows that were closed,
      which killed the process — hence pythonw. Contact address in the User-Agent is the repo's
      git author address. First manifest seen: 17,861 files.
- [x] **2. Send the P5 email** (owner, 31 Aug). Sent to space-safety-onboarding@spacex.com from
      the personal address; recorded in the claims register. D06 closes on an answer or 30 Sep 2026.

## Days 1–2

- [~] **3. Harden `archive/poll.py`** (agent)
  - [x] `--limit` never writes `root.txt`; `partial: {"limit": N}`; exit 3; under `<spool>/partial/`
  - [x] cycle identity by manifest sha only: `cycle_<sha12>` (D11); `first_seen_utc` preserved on resume
  - [x] ETag cache flushed atomically every 200 completions under a lock; `cycle.json` at start
        (`in-progress`) and on interrupt (`interrupted`, exit 4); queued futures cancelled; SIGTERM → interrupt
  - [x] `root.txt` written as bytes: 64 lowercase hex + LF (D12)
  - [x] manifest names validated as single path components; duplicates and bad names are gaps
  - [x] manifest re-fetched at end; `manifest_changed_during_pull` recorded; root still written (D09)
  - [x] disk-free preflight (`--min-free-gb`, default 25); exit 5
  - [x] contact address in User-Agent from `--contact` / `EPHEMERA_CONTACT`; refuse without one
  - [x] `requirements.txt`; `.pytest_cache/`, `heartbeat.json` in `.gitignore`
  - [x] 16 caller-level tests in `archive/tests/test_poll.py`, 4 in `test_run_cycle.py`; 13 named
        mutations each turn a test red (scratch script, 30 Aug); suite green 3/3 runs
  - [x] `archive/run_cycle.py` watcher: conditional manifest GET, skip complete, retry incomplete, heartbeat
  - [x] live smoke test: 5-file `--limit` slice from the real feed, 11 s, partial record, no root
  - [x] adversarial review (16 agents, 12 confirmed / 0 refuted / 27 unverified). Fixed with a failing
        test first, 30 Aug: watcher skipped retries after a manifest 304 (live bug); OSError in the
        download loop orphaned the pool (now `status: error` + re-raise); interrupted pull did not stop
        the watcher; anomalies counted per line, case-insensitive duplicates, strict name allowlist,
        BOM/CR-safe manifest parsing; stale `root.txt` removed on a gapped re-run; atomic root write;
        untrusted 304 without a validator; manifest fetch failure → exit 5; second Ctrl-C path;
        completed futures dropped (memory). Suite 43/43 ×3; 12/12 fix mutations red.
  - [ ] review items left open, judged low: no spool lock between two pollers on one spool
        (single writer by design; document); SIGTERM mapping inert when SIGINT is SIG_IGN (nohup) -
        systemd does not do that; retry-abort via `stop` not pinned by a test; 1.6 GB RSS on a
        100k-line all-404 manifest (now reduced by dropping completed futures; not re-measured).
- [~] **4. Doc truth pass + claims lint** (agent; DOCS/ edits need owner acceptance)
  - [x] canonical measurements table in `probes/p1_cycle_pull/README.md`; other docs cite it
  - [x] README: "request sent" → drafted; "zero public archives" → no continuous public archive;
        status block matches reality (capture running since 15:32 UTC)
  - [x] `probes/p5_spacex_terms/email-draft.md` in true tense
  - [x] corrections-log entries (7) in `DOCS/claims-register.md`
  - [x] `tools/claims_lint.py` in `make test`, quoted-mention and "say …" handling, `<!-- lint:allow -->`
  - [x] D11–D18 appended to `DOCS/decisions.md` as *proposed* — **owner to accept**
  - [ ] owner sign-off on the DOCS/ edits (concept.md numbers, claims-register entries, D11–D18)
- [x] **5. P4 desk pricing** (agent, 30 Aug) → `probes/p4_cost/README.md`, both 0.82 and 1.32 TB/month.
      Result: S3 Glacier Deep Archive eu-west-1, one tar per cycle, 512 MB parts, build from the
      VPS's local copy = USD 10.3 / 16.5 per month at month 12, 20.0 / 32.2 at month 24 — under the
      USD 60 kill line; every hot store (R2, B2, Wasabi) breaches on storage alone by month 4–11.
      Traps: whole-archive restore out of AWS ≈ USD 906 / 1,436 (restore in-region instead);
      per-file objects cost USD 55–88/month in PUTs alone. Hetzner prices unverified (client-side
      rendering). Under the larger volume no two-copy layout stays under USD 60 at month 24.
      Not yet compared against a real bill.
- [x] **6a. Account guard** (31 Aug). `infra/guard.sh`: allowlist in gitignored `infra/personal.env`
      (template committed), STS identity check, refusal on missing/empty allowlist, no override path
      (a test greps for one); every infra script must source it first (call-site test; mutation red).
      **Owner: put the personal AWS account ID into `infra/personal.env`** (copy the .example).

### New since the plan was written

- [x] **P1b — manifest composition** (closed 31 Aug). Steady state ~9,000 files ≈ 7.4 GB
      gz/cycle ≈ 0.67 TB/month; cadence ~8 h, none missed. Overlap measured across the first four
      cycles: **zero repeated names between consecutive manifests** — every cycle is 100% fresh
      bytes, so D15 keeps the plain per-cycle tar and dedup is dropped. Residual watch: whether
      the count tracks manoeuvre activity.

## Days 2–8

- [ ] **6b. Poller A on a non-AWS VPS** (owner provisions; agent bootstraps). First full datacentre
      pull = the P1 rate-limit probe; CelesTrak reachability recorded for P3. Then systemd watcher +
      heartbeat + dead-man ping.
- [x] **7. Witnessing** (closed 31 Aug, except SPN2 auth). P2b probe done; archive/witness.py
      deployed as the Ephemera-Witness task: OTS stamp + hourly upgrade with block heights
      recorded; Wayback manifest + 10 root-seeded files verified via sha256(gunzip(id_));
      superseded losses recorded honestly; and the daily root (D16) - each past UTC day's
      complete-cycle roots, first_seen order, same stamping lifecycle, never rebuilt. Remaining:
      authenticated SPN2 once the owner's archive.org keys exist.
- [ ] **8. Cold storage** `archive/ship.py`: one tar per cycle, streamed, S3 full-object SHA-256
      verified before local delete, gapped cycles shipped, 3-day local retention, put-only IAM,
      versioning + Object Lock (governance), billing alarm.
- [ ] **9. Poller B** on a second provider/region; uploads unless A has an equal non-null root.

## Days 7–14

- [x] **10. Ledger + status page** (1 Sep). web/build.py: spool records -> ledger.json + status
      page (cycle rows with roots/OTS blocks/Wayback state, daily roots, D18 coverage from the
      watcher's new heartbeat history, cadence holds; gaps loud, losses printed, as-of on every
      figure). web/publish.py: build -> claims-lint -> dist-only commit -> push -> auto-deploy;
      the committed dist is the publication of record. Tests from a synthetic all-uncomfortable
      spool + real-browser DOM check; three page mutations red. Earlier: VERIFY.md + verify.py.
      Remaining for the full item: Playwright-grade browser tests can wait; the scoreboard
      (score/) is its own item.
- [ ] **11. Allies**: Kelso email once ≥3 witnessed cycles exist; P3 from the VPS; bulletin #1 to
      Kelso and McDowell with a 5-day window; CelesTrak OMM archived per cycle as a separate feed
      with its own root.
- [ ] **Public launch gate** (owner): IP clause checked; Kelso replied or 7 days; docs truthful;
      ≥7 days of ledger; domain live.

## Weeks 3–6

- [ ] **12. `score/` v0**: RTN error by element age, visibility fraction, from archived OMM only.

## Log

- 2026-08-30 — plan accepted with all defaults; batch 1/3/4/5 + email rewrite started.
- 2026-08-30 15:28 UTC — live smoke test of the rewritten poller: 5/5 files, partial record, no root.
  Manifest listed 17,861 files (morning count 11,099) → P1b opened; P4 re-briefed for both volumes.
- 2026-08-30 15:32 UTC — home capture started (`Ephemera-Watcher`), first cycle `cycle_72bcd7796b49`.
- 2026-08-30 13:40 UTC — watcher moved to `pythonw` (two console-window kills). 7,117 files in the
  first 31 min ≈ 3.8 files/s ≈ 78 min per 17,861-file cycle from the home link.
- 2026-08-30 14:11 UTC — watcher restarted onto the review-fixed code; resumed the same cycle via
  the ETag cache.
- 2026-08-31 — four complete overnight cycles with roots (~9k files ≈ 7.4 GB gz each, ~8 h cadence,
  none missed). First commits pushed to the private personal repo.
- 2026-08-31 — P2b: OTS proof Bitcoin-attested (block 964715); 2 MB Wayback capture verified via
  gunzip. Guard + in-pull heartbeat landed.
- 2026-08-31 — witness.py first live pass: all 4 cycle roots Docker-stamped; current cycle's
  manifest + 7/10 samples captured and verified; 3 samples hit Wayback's unauthenticated 429
  limiter (~8 rapid captures trips it — hence --capture-gap 12 s; authenticated SPN2 keys remain
  the real fix). The 3 superseded cycles record "captures never made" as designed. Deployed as
  scheduled task Ephemera-Witness (pythonw, 300 s interval, Z:\ephemera\witness.log).
- 2026-08-31 — `ephemera.space` registered (personal Cloudflare); D01 accepted. Naming panel run
  first: the only rival domains (`ephem.space`, `ephemer.is`, `ephemeris.space`) were already taken. Known gap: `heartbeat.json` is only written between ticks, so during a long pull
  it goes stale for the whole pull — FIXED 31 Aug: the watcher now pulses `action: "pulling"` into
  heartbeat.json every 60 s during a pull (`--pulse`; caller-level test, mutation red).
- 2026-08-31 — coming-soon page built and linted (web/dist); D19 proposed (site on Cloudflare
  Pages); awaiting owner deploy + custom domain before the P5 email goes out.
- 2026-08-31 — Cloudflare deploy pipeline built and pushed: guard_cf (token-only; the machine's
  wrangler OAuth is the employer identity and is never used), cf_site.py, site-bootstrap.sh,
  deploy-site.sh, push-to-deploy workflow. Waiting on the owner's personal API token to go live.
- 2026-08-31 — ephemera.space LIVE on Cloudflare Pages (personal account, guarded token).
  wrangler retired after a sentinel test proved it ignores CLOUDFLARE_ACCOUNT_ID for pages deploy
  and targets an employer account from machine state; deploys now go through infra/cf_site.py's
  direct-upload client, locally and in the push-to-deploy workflow alike. Apex DNS live; custom-
  domain certificate provisioning at the time of the log entry.
- 2026-08-31 — ephemera.space certificate active; zone answers on Google and Cloudflare public
  DNS (Status 0, correct A records); push-to-deploy proven end-to-end (runner deployed by itself,
  identical blake3 hashes cross-OS). Local machine briefly saw NXDOMAIN afterwards: the ISP
  resolver negative-cached the pre-creation answer and 15-second probe retries kept re-priming it
  (negative TTL 300 s) - lesson: after creating a DNS record, wait out the negative TTL before
  probing in a tight loop. DNSSEC ruled out (disabled, no DS).
- 2026-08-31 - P5 email SENT (owner). D06 30-day clock running; site and README reframed
  appreciatively toward SpaceX the same day.
- 2026-08-31 - P1b closed (zero overlap between manifests); verify.py + VERIFY.md landed and
  passed against a real cycle; daily root (D16) implemented and deployed; 71 tests green.
- 2026-08-31 - first daily root built and stamped (2026-08-30, two cycle roots; independent
  recompute matches). All four cycles Bitcoin-attested. Feed cadence anomaly observed: one
  manifest held 9.6+ h (watcher healthy, independently confirmed) - recorded in P1. The
  archive already holds a SIX-DIGIT catalogue object (MEME_100224 / STARLINK-38164): a
  ready-made datapoint for bulletin #1 (P3).
- 2026-09-01 - ledger + status page live pipeline: build/publish/deploy chain, D18 coverage
  from heartbeat history, first real publish committed by publish.py itself.
- 2026-09-02 - status check, day three: 11 cycles archived (10 complete, 10 attested, 224 GB raw),
  three daily roots attested, ledger republished every 4 h on schedule, 1.1 TB free. Two fixes:
  the watcher had never been restarted after the heartbeat-history change (coverage stayed "not
  yet measured"; restarted, history accumulating, measurable from 3 Sep); and manifest captures
  were failing every other cycle because Wayback de-duplicates an unchanged URL and returns the
  previous snapshot - each cycle's manifest now gets its own capture URL (?cycle=<sha12>).
  Losses on record: cycle 513b92 (Wayback 523 upstream failure, 10 samples), d03dc5 (6 samples,
  throttling). Authenticated SPN2 (owner's archive.org keys) remains the real cure for throttling.
  Runway: ~30 GB/day gzipped -> cold storage (item 8) needed within about a month.
