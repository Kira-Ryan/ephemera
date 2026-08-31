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
- [ ] **2. Send the P5 email** (owner). Draft rewritten 30 Aug to true tense. Record the send date
      in `DOCS/claims-register.md`.

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

- [~] **P1b — manifest composition.** Four complete cycles (31 Aug): steady state ~9,000 files ≈
      7.4 GB gz/cycle ≈ 0.67 TB/month; 17,861 was an outlier; cadence ~8 h, none missed. Still to
      do: count file names repeated across consecutive manifests (same name = same bytes → dedup in
      D15's storage unit), and watch whether the count tracks manoeuvre activity.

## Days 2–8

- [ ] **6b. Poller A on a non-AWS VPS** (owner provisions; agent bootstraps). First full datacentre
      pull = the P1 rate-limit probe; CelesTrak reachability recorded for P3. Then systemd watcher +
      heartbeat + dead-man ping.
- [~] **7. Witnessing**: P2b probe DONE (31 Aug): P2 proof upgraded — Bitcoin block 964715; clean
      `ots verify` needs a Bitcoin node (no explorer fallback) — VERIFY.md must say so; SPN accepts
      a full 2 MB file and the `id_` copy gunzips to exactly the recorded sha (so the witness check
      is sha256(gunzip(id_))). Next: `archive/witness.py` (stamp, hourly upgrade, Wayback manifest +
      10 root-seeded files), daily root over cycle roots (D16). Authenticated SPN2 waits on the
      owner's archive.org keys.
- [ ] **8. Cold storage** `archive/ship.py`: one tar per cycle, streamed, S3 full-object SHA-256
      verified before local delete, gapped cycles shipped, 3-day local retention, put-only IAM,
      versioning + Object Lock (governance), billing alarm.
- [ ] **9. Poller B** on a second provider/region; uploads unless A has an equal non-null root.

## Days 7–14

- [ ] **10. Ledger + status page + site skeleton** (`web/`), built on poller A, static to
      S3 + CloudFront under the guard; Playwright claims tests; `VERIFY.md` + `verify.py`.
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
- 2026-08-31 — `ephemera.space` registered (personal Cloudflare); D01 accepted. Naming panel run
  first: the only rival domains (`ephem.space`, `ephemer.is`, `ephemeris.space`) were already taken. Known gap: `heartbeat.json` is only written between ticks, so during a long pull
  it goes stale for the whole pull — FIXED 31 Aug: the watcher now pulses `action: "pulling"` into
  heartbeat.json every 60 s during a pull (`--pulse`; caller-level test, mutation red).
