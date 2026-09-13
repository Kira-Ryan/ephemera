# Migration runbook: Ephemera on one Linux VPS (drafted 9 Sep 2026, corrected 13 Sep 2026)

Status: **PROPOSED, pending the owner.** Nothing here has been executed: no host exists, no
credential has moved, no scheduled task has been stopped.

What this document is now. It was drafted 9 Sep from a six-component survey, then attacked on three
lenses (cutover, secrets, portability). Those passes found nineteen defects in the draft. All
nineteen are folded into the procedure below, and the last section is a record of where each one
was addressed rather than a list of live defects: follow the steps as written, and use that section
to audit that every finding was handled.

Two things changed under the draft and are reflected throughout.

- **Probe P8 has run and passed** (`probes/p8_vps_bootstrap/README.md`, 12 Sep 2026). The feed
  serves a datacentre address at full rate for a whole cycle, and a second poller reproduced the
  home poller's Merkle root from the same manifest. Section 1 is now what was measured, not what to
  measure.
- **Three findings were code defects and the code is fixed**, in this checkout and not in this
  text: the ledger publishes the pack's name rather than the build machine's absolute path, and the
  build finds that pack from any working directory (`web/build.py:157,318`); the publisher
  fast-forwards onto what origin publishes before it builds, refuses when the branch has diverged,
  and measures the shrink guard against the published count (`web/publish.py:54-110,131,159-166`);
  and the Cloudflare shell guard resolves an interpreter before its zone check, so a host with
  `python3` and no `python` is no longer told its token cannot see the zone
  (`infra/guard_cf.sh:40-50,63-79`). Sections 3.2, 3.9, 4, 5.6 and 6 describe the new behaviour.

Owner decisions of 12 Sep 2026 this is written to: hosting stays non-AWS (D14), cost is a factor at
the Hetzner class of EUR 15 to 30 a month, and the same host builds and pushes the site. No
decision entry names a provider yet; section 2 says what one would have to record.

---

# Ephemera on one Linux VPS: migration runbook

Written 9 September 2026, corrected 13 September 2026. Every claim below is cited to a file and line read in this checkout, or marked as unverified. Where a survey was wrong or imprecise, section 9 says so rather than quietly correcting it.

Measured on the live spool on 13 Sep 2026 with `du`, so the runbook is sized against the present: **44** `cycle_*` directories under `Z:\ephemera\spool`, **9** of which still hold a `files/` directory (on 9 Sep it was 33 and 10). The 44 cycle directories excluding `files/` total 396 MB, `spool/score` is 443 MB, `spool/gp` is 215 MB, `spool/daily` is under 1 MB, `heartbeats.jsonl` is 3,134,754 bytes. The per-cycle record set is about 9 MB (`cycle.json` 4.44 MB, `etag_cache.json` 3.71 MB, `MANIFEST.txt` 821 KB, `witness.json` 7.5 KB, `ship.json` 924 B, `root.txt` 65 B, measured on `cycle_0e700520864b`, 9 Sep). The orphaned `outbox/cycle_03329cf37459.tar` is 9,277,429,760 bytes and is still there.

---

## 0. The shape of the plan

Six components move: watcher, witness, shipper, catalogue, score, ledger. Five are pure single-writer jobs where running two copies is either wasteful or actively dangerous. One, the poller, is the exception: D10 (`DOCS/decisions.md`, D10) makes cycle identity the SHA-256 of `MANIFEST.txt`, so two pollers on the same manifest produce the same cycle id and, when complete, the same root. That is the whole reason a second poller is a check and not a duplicate, and it is what lets the archive run continuously across the cutover with no gap.

So the order is: re-measure the link on the host actually bought (P8 already proved a datacentre link works, section 1), build the real host out, start the VPS poller alongside the home poller, cut the other five over one at a time while both pollers run, then stop the home poller last. Each of those five is stopped on Windows, has its own records re-synced, and is only then started on the VPS.

One VPS satisfies "off Windows" and "non-AWS". It does not satisfy D14's "two providers/regions" or D03's two geographically separate pollers. Poller B stays PLAN item 9. Do not let this runbook be read as closing it.

---

## 1. The probe has run: what P8 measured, and what is still open

CLAUDE.md says the cheapest probe that can kill the plan runs first, with a measured result and a
date under `probes/`. That probe is `probes/p8_vps_bootstrap/README.md`, run 12 Sep 2026 on a
throwaway `t3.small` in eu-west-1 (Ubuntu 24.04.4, Python 3.12.3, 2 vCPU, 2 GB, public address
34.242.139.192, AS16509), created and destroyed by the probe's own `ec2_probe_host.sh`, holding no
AWS credential, for under USD 0.10. It ran on AWS address space deliberately: D14 keeps continuous
compute off AWS, but an AWS range is the most commonly blocked hosting range there is, so a pass
there is the harder pass.

**None of the kill conditions triggered.** The canonical table is in the probe. The results that
decide this runbook:

- **Rate.** A sustained full-cycle pull with the production poller: 11,132 files in 24 min 3 s, 0
  failed, 22.6 GB raw, which is 7.7 files/s and 15.7 MB/s. The kill line was more than 6 hours per
  cycle (`probes/README.md:9`, row P1); home takes 45 to 116 min. No 403, no 429, and no collapse
  after the first few hundred files, which is the failure a short slice could not have shown.
- **The root reproduces.** The same manifest (`34e224670e92`) pulled at home from 12:18 UTC and on
  the probe host from 16:50 UTC produced the identical Merkle root `3a1dc167948cd8c8...`. That is
  the property the overlapping-poller cutover rests on, now observed rather than argued from D10.
- **Conditional GET.** HTTP 304 on `If-None-Match`, so D17's 120 s tick stays cheap.
- **S3.** A 2 GiB single PUT to eu-west-1 at 55.7 MB/s, against a 3 MB/s floor. A 9.3 GB tar is
  about three minutes, so the S3 leg is nowhere near the bottleneck.
- **OpenTimestamps runs natively.** `opentimestamps-client` 0.7.2, `ots stamp` in 1.5 s, 735-byte
  proof. Docker leaves the project.
- **Wayback.** Three captures at the code's 12 s `--capture-gap` (`archive/witness.py:352`): one
  HTTP 523 from Wayback's own side, two clean, no 429. SPN2 keys are not a cutover blocker.
- **Reachability.** Every endpoint answered, including `celestrak.org`, which the home IP cannot
  reach (P3). The host had no IPv6 default route, so the AAAA-record-with-no-route failure mode the
  draft worried about did not arise and remains untested.
- **Memory.** 578 MB peak RSS for the full pull on a 2 GB host, at 179 percent of two vCPU.
- **`requirements.txt`** installs on Ubuntu 24.04 / Python 3.12.3 in 15.9 s, every wheel present.

**Still open, and these are day-one gates on the real host, not optional extras.** P8 measured AWS,
not Hetzner or OVH or netcup.

1. **The chosen provider's own rate to `api.starlink.com`.** Re-run the probe's `probe.sh` and then
   a sustained full pull on the real host before anything is cut over, and record both under a
   second dated heading in `probes/p8_vps_bootstrap/README.md`. The kill lines stand unchanged: a
   projected cycle over 6 h kills the region; a 403 from the operator kills the poller half of the
   migration, in which case the home poller stays as poller A and the VPS becomes witness plus
   shipper plus score plus ledger, which is a decision entry and not a workaround; S3 under 3 MB/s
   kills the single-host plan.
2. **Space-Track from a second IP.** P8 reached the front page and **did not log in**: two clients
   on one account is an owner decision. `archive/gp_pull.py:59-60` raises on any non-200 with no
   retry and no backoff, so a soft block looks exactly like a maintenance page. This is why the
   catalogue cutover (C7) is a single atomic switch and never an overlap.
3. **Behaviour over weeks.** Whether 27.8 GB a day from one hosting address draws an abuse
   complaint or a quiet throttle. Only the real host shows that, which is the other reason the home
   poller stays up through the cutover.

---

## 2. VPS spec and provider shortlist

### Sizing, from the measured numbers

**Disk.** The shipper keeps `files/` for `--keep-days`, default 3.0 (`archive/ship.py:275`), and the feed rolls about every 8 hours, so the steady-state working set is about 10 cycles at 9.26 GB, which is 93 GB. On top of that:

| Item | Size | Source |
|---|---|---|
| Retention window, 10 cycles of `files/` | 93 GB | measured, 9.26 GB per cycle |
| One tar in `outbox/` during a ship | 9.3 GB | `archive/ship.py:126,189`; transient but real |
| Poller preflight floor, `--min-free-gb` | 25 GB | `archive/poll.py:247-248`, refuses below it with exit 5 |
| Cycle records, 44 cycles at 9 MB | 0.40 GB | measured 13 Sep |
| `spool/score`, growing about 12 MB per scored cycle | 0.44 GB on 13 Sep, +13 GB/year | measured, 3 cycles/day |
| `spool/gp`, never pruned, never shipped | 0.22 GB on 13 Sep, +8 GB/year | measured; nothing in the repo deletes it |
| Repo checkout with history, growing 5.2 MB per scored cycle | ~1 GB, +5.7 GB/year | the committed globe pack, PLAN follow-up (b) |
| OS and packages | 10 GB | |

That is about **140 GB with zero slack**. The number that decides the size is not the steady state, it is a shipper outage: at 27.8 GB a day, a 160 GB disk breaches the preflight floor inside two days of the shipper being stuck, and the poller then refuses to start a cycle, loudly, and the cycle is gone. **Buy 320 GB.** That gives about eight days of grace. Note that `shutil.disk_usage(...).free` is `f_bavail` on POSIX (`archive/poll.py:259`, `archive/ship.py:193-195`), so ext4's default 5 percent root reserve is invisible to the preflight: on a 320 GB volume that is 16 GB you paid for and cannot use. Either size up or set `tune2fs -m 1` on the spool filesystem at build time.

**RAM: 8 GB.** Justification, and the honest gaps in it. Score's rows list alone was measured at 111 MB resident and 148 MB peak for 143,101 rows, and the parent additionally holds the catalogue, the whole `results` list materialised at `score/visibility.py:281-283`, and the 5.2 MB pack, beside four forked workers. Full-process peak was never measured. The poller's only recorded peak is 1.6 GB RSS on a 100k-line all-404 manifest (PLAN.md, review items left open), which was reduced by dropping completed futures and **not re-measured**, and all 11,134 futures are still submitted up front (`archive/poll.py:360-361`). Six units run concurrently. P8 has since measured the poller directly: 578 MB peak RSS for a full 11,132-file pull on a 2 GB host, so the 1.6 GB figure was the all-404 pathology and not the normal path. 4 GB is probably enough and still has no margin against score's unmeasured full-process peak; 8 GB costs a few euro and removes the question. Measure peak RSS for score on the first real cycle and record it in the probe.

**vCPU: 4.** Score is the only real consumer, measured at about 8 minutes per cycle at 4 workers on the home PC while the watcher was pulling (PLAN.md, 2026-09-03), which is about 24 minutes of work a day at 3 cycles a day. The poller is IO-bound across 16 threads (`archive/poll.py:242`). Two vCPU would work and would roughly double score's wall time, which matters only when draining a backlog.

**Traffic: about 0.85 TB in and 0.85 TB out per month.** In: 9.26 GB per cycle times 3 cycles a day is 27.8 GB/day, plus the catalogue at up to 12 times 14.6 MB a day, plus Wayback `id_` re-fetches at roughly 22 MB per cycle. Out: the 9.28 GB tar per cycle to S3, same 27.8 GB/day, plus git pushes carrying a 5.2 MB pack per scored cycle. Choose a provider that either includes multi-TB egress or does not meter it. Do not choose a metered cloud with a 1 TB allowance.

### Shortlist, and the honesty about prices

The owner decided on 12 Sep 2026: **non-AWS, and cost is a factor** - the Hetzner class, EUR 15 to
30 a month - and the same host builds and pushes the site. D14 already puts pollers, witnessing,
shipping and the daily build on non-AWS Linux, so this is a choice inside D14 rather than a change
to it. What does not exist yet is a decision entry naming a provider and a region. Record one when
the account is opened, with the price actually paid, so the estimates below stop being the only
numbers in the repository.

**No VPS price in this repository is verified.** `probes/p4_cost/README.md:48` excludes "the VPS
itself" from the cost table entirely, and line 68 records that Hetzner's own prices were **not
captured**, because hetzner.com renders them client-side, with the numbers taken from a third-party
snapshot dated 13 Feb 2026 and marked "Unverified against hetzner.com". P8 measured no provider's
price either. Every figure below is a desk estimate to confirm at purchase.

- **Hetzner Cloud** (Falkenstein, Nuremberg, Helsinki). CPX31 class, 4 vCPU AMD / 8 GB / 160 GB,
  plus a 200 GB volume; or CPX41, 8 vCPU / 16 GB / 240 GB. 20 TB egress included on EU locations.
  Estimate EUR 16 to 30 a month, which is the band the owner's decision names. Caveat beyond price:
  Hetzner is known for acting quickly on abuse complaints, which matters precisely because open
  question 3 in section 1 is whether 27.8 GB a day from one address draws one.
- **OVHcloud VPS** (Gravelines, Frankfurt). Unmetered bandwidth. Estimate EUR 12 to 25.
- **Netcup** (Nuremberg, Vienna). Large disks cheaply. Estimate EUR 10 to 20.
- **Scaleway** (Paris, Amsterdam, Warsaw). Already priced in P4 for storage, so the account may
  already exist. Estimate EUR 15 to 30.

Excluded by decision, not by price: any AWS instance (D14, nothing on AWS runs continuously), and
any Cloudflare compute (D08 zero-ops, and no Workers path exists for a 9 GB pull).

Region: EU, near eu-west-1 for the S3 leg. But the deciding input is the rate measured from that
region on day one, not proximity to Ireland.

**Rough monthly cost:** VPS EUR 15 to 30 (unverified), plus S3 Glacier Deep Archive at USD 10.3 to
16.5 at month 12 (P4 desk pricing, never checked against a real bill). Combined, roughly USD 27 to
50 a month at month 12. P4's USD 60 kill line was set for storage alone; if the owner wants one
number covering compute too, that needs a new decision entry raising or restating the line.

Image: Ubuntu 24.04 LTS, which is what P8 measured. `python3.12` is the distro Python and satisfies
everything, including `pool.shutdown(cancel_futures=...)` at `archive/poll.py:386`.

---

## 3. Code changes

Deploy by `git clone` on the VPS, never by copying this working tree. `git ls-files --eol` shows the index is LF for everything, but the working tree here is CRLF for `Makefile`, `infra/deploy-site.sh`, `infra/guard_cf.sh` and `infra/site-bootstrap.sh` because this machine has `core.autocrlf=true`. A CRLF `Makefile` or shell script fails on Linux with `$'\r': command not found`. A fresh clone is clean. Also: every tracked file is mode 100644, so nothing has the executable bit; every `ExecStart` must name the interpreter and every shell script must be run as `bash infra/whatever.sh`.

### Required, blocks Linux operation

**3.1 `Makefile:24,27,30,34,38,42,46`** all invoke `python`, which does not exist on stock Ubuntu 24.04. Add `PY ?= python3` near `SPOOL ?=` and replace each bare `python` with `$(PY)`. Without this `make test`, the only gate that runs `score/tests` and the browser tests, fails at once. In practice the systemd units use the venv interpreter, so this is about the test gate and hand-running, which is exactly where you need it.

**3.2 Bare `python` in the shell scripts. `infra/guard_cf.sh` is fixed in code; two scripts are not.** A stock Ubuntu 24.04 host has no `python` command at all, only `python3`. The guard resolves its interpreter once, preferring `python3`, before the API call (`infra/guard_cf.sh:40-50`), refuses in its own words when there is none, and the interpreter now prints the zone's owning account rather than exiting on the comparison, so a body it cannot parse, a token that sees no zone and a zone owned by another account are three distinct refusals (`infra/guard_cf.sh:63-79`).

This mattered more than a missing interpreter usually does. Measured before the fix, on a PATH with `python3` and no `python`, and with a fake API answer naming the allowlisted account so the correct outcome was a **pass**: the bare `python -c` printed `python: command not found`, the zone check's own `|| { ... }` block caught it, and the guard exited 1 with `REFUSED - the token cannot see the ephemera.space zone under the allowlisted account`, while the zone binding had never been evaluated. `infra/tests/test_guard.py`'s refusal test asserted on that exact wording, so it passed for entirely the wrong reason: green while the guard was inoperative. The test now stages a `python3` shim that logs when it runs, asserts it ran, and asserts the refusal names an account id that exists only inside the fake API answer (`infra/tests/test_guard.py:241-256`), and two new tests cover the no-`python` host and an unparseable answer (`:257-279`).

Correcting the draft's reasoning while we are here. It said "none of these run on the VPS under the recommended deploy path". `infra/guard_cf.sh` **does** run on the VPS, in the C2 gate: `infra/tests/test_guard.py:198-227` stages a copy of `infra/` with a fake `curl` and `infra/tests/test_guard.py:228-293` executes the guard under bash, and `make test` is C2.

**Not fixed, outside this change, same one word:** `infra/deploy-site.sh:9` and `infra/site-bootstrap.sh:13,14,15` each call a bare `python infra/cf_site.py ...`. Both source `guard_cf.sh` first, so on a stock Ubuntu host the guard now passes and the script dies one line later. `.github/workflows/deploy-site.yml:47,54` also call a bare `python`, and that is **not** a defect: the job runs `actions/setup-python@v5` at `:36`, which puts `python` on the runner's PATH.

**3.3 `archive/witness.py:72-73`, drop the silent Docker fallback.** Today `--ots auto` picks `ots` if `shutil.which("ots")` finds it and otherwise `docker`. Under systemd the unit's PATH is not a login shell PATH, so an `ots` installed into `/opt/ephemera/.venv/bin` is invisible and `auto` silently selects Docker, which is the exact dependency this migration removes. Two edits:

- At `archive/witness.py:80`, the native command is the bare string `["ots", *ots_args]`. Add an `--ots-bin` argument (default `"ots"`), store it on the runner, and use it here, so the unit can name `/opt/ephemera/.venv/bin/ots` absolutely and never depend on PATH.
- At `archive/witness.py:72-73`, make `auto` mean native-or-refuse: if `which(ots_bin)` finds nothing, raise rather than falling through to Docker. Docker stays reachable, but only when explicitly asked for with `--ots docker`, which is what `Makefile:51,55,59` still want on Windows. This converts a silent dependency into a loud refusal, which is the project's rule.

**3.4 `archive/witness.py`, persist the stamp before the Wayback loop.** `witness_cycle` calls `ots_step` at line 279 and writes `witness.json` once, at line 336, after a Wayback loop that can run eleven captures at a 12 s gap with 300 s timeouts each. A kill in that window leaves `root.txt.ots` on disk with no `stamped_utc` in `witness.json`. The next pass sees `proof.exists()` and `proof_matches()` both true (`archive/witness.py:184,191`) and goes straight to the upgrade branch, so `stamped_utc` is **never backfilled** and `web/build.py:78` renders the cycle as never stamped, permanently. The fix is one inserted line: `poll.write_json_atomic(w_path, w)` immediately after line 279. Under Task Scheduler this window was rare. Under systemd, restarts are routine.

**3.5 `score/run.py:96-107`, write the pack before the report, atomically.** Order today is: build pack in memory (96), write the report via `visibility.write_outputs` (97), write the pack file (105). `candidates()` treats the report's existence as "this cycle is done" (`score/run.py:61`), so a kill between 97 and 105 marks the cycle scored forever with no pack, and it is never retried. The comment at lines 90 to 95 (duplicated, and worth deduplicating while you are in there) claims the ordering prevents this. Traced, the claim holds for `build_pack` **raising**, and does not hold for the process dying. This is a live example of CLAUDE.md rule 10: a comment describing intent that reads exactly like a comment describing behaviour.

The consequence is worse than one missing pack. `web/build.py:315-323` takes the headline report's pack, and `headline_report` (`web/pages.py:78-84`) does not require a pack to exist. If the headline cycle's pack is missing, `head["pack"]` is `None` (`web/build.py:157`) and `web/build.py:322-323` **deletes** `web/dist/globe/pack.json`, shipping a globe page with no data and no error anywhere. That branch survived the 3.9 fix unchanged and still has no test; it is the one part of 3.5 that is not covered.

Edit: move the pack write above `write_outputs`, and write it through a temp file plus `os.replace` rather than `Path.write_text`. `archive/poll.py:139-148` already has exactly this helper; `score/` cannot import it without pulling `requests` in, so write the four lines locally. Then prove it: mutate the call site by deleting the pack write and confirm a test goes red.

**3.6 `archive/ship.py`, reclaim an orphaned outbox tar.** The tar is unlinked only inside the `if why:` upload branch. Once `needs_upload()` returns `None`, the file is unreachable forever. That is not theoretical: `outbox/cycle_03329cf37459.tar` is 9.28 GB of dead weight on the spool right now, for a cycle already shipped and verified whose `files/` are deleted, so it can never even be repacked (`pack()` calls `verify_local_files()`, which raises `CorruptCycle`). Under Task Scheduler this happened once. Under systemd, `TimeoutStartSec` and `systemctl stop` reproduce it on a schedule. Edit: in `ship_cycle`, when `why` is falsy, delete `<spool>/outbox/<cycle>.tar` if it exists and log that you did.

**3.7 `archive/poll.py:141`**, `tmp.write_text(json.dumps(obj, indent=1))` with no `encoding=`. Add `encoding="utf-8"`. This is cheap determinism, not a live bug: `json.dumps` defaults to `ensure_ascii=True`, so the bytes are ASCII either way. The real exposure is the readers with no encoding under a systemd unit that has no `LANG`, where Python's locale encoding can be ASCII. Do not shotgun `encoding=` into every `read_text` in the tree; set `LANG=C.UTF-8` in every unit (section 5), which covers those and also covers `web/publish.py:144-145`, the one `subprocess.run(..., text=True)` in the publish path with neither `encoding=` nor `errors=`, decoding page text and register phrases. (`git()` at `web/publish.py:28-29` already passes `errors="replace"`.)

**3.8 `infra/personal.env.example`.** Verified: it names only `EPHEMERA_AWS_PROFILE`, `EPHEMERA_AWS_ACCOUNT_IDS`, `EPHEMERA_AWS_FORBIDDEN_IDS`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `EPHEMERA_CF_ACCOUNT_IDS`. It does **not** name `SPACETRACK_USER`, `SPACETRACK_PASS` or `EPHEMERA_CONTACT`. Provision the VPS from this template and `archive/gp_pull.py:49-50` raises, the broad handler at line 138 logs it, and the pass returns 1 every two hours forever: the component never works and never crashes. Add the three names, commented, with empty values.

### Recommended, not blocking

**3.9 Done in code: the ledger no longer publishes the build machine's filesystem layout.** `web/build.py` used to publish `str(pack)`, the absolute spool path, so every visibility report in the committed public `web/dist/ledger.json` read `Z:\ephemera\spool\score\globe_<sha12>.json` - 40 of 40 in the 2026-09-13T08:20:00Z build. It now publishes `pack.name` (`web/build.py:157`).

The draft proposed that one-word change on its own, and **as written it was wrong**: `web/build.py` reads its own output. `ledger["visibility"]["reports"]` is `load_scores()`, and `main()` takes the headline report's `pack` field and copies that file to `web/dist/globe/pack.json`. With only the producer changed, the copy resolves a bare `globe_<sha12>.json` against the process CWD, which under the unit's `WorkingDirectory=/opt/ephemera` is not where the file is. Measured on a scratch copy with only that line changed: the build died at the `shutil.copyfile` with `FileNotFoundError: 'globe_cb82167ca7de.json'`, exit 1. Nothing in `build.main` or in `web/publish.py` catches it, so the 4-hourly ledger run would have ended in a traceback before the lint, the commit and the push, and the published site would have frozen silently at whatever it last held. The consumer is therefore changed too: `main()` rejoins the published name to the spool it just read (`web/build.py:318`). Two tests pin the two halves (`web/tests/test_build_visibility.py:479,498`), the second by running the whole build from an empty working directory.

Two things a reader should still know. The committed `web/dist/ledger.json` keeps the old `Z:\` strings until the next publish rebuilds it, and in git history the leak is permanent: 71 of the 91 committed versions of that file contain `Z:`, the earliest being commit `583531f` of 3 Sep 2026. And whether anything outside this repository consumes that field is still unverified - only this repository can be grepped, clean-room - so if some external consumer reads it as a path, this is a breaking change for it and not a cosmetic one.

**3.10 `web/tests/test_build.py:22-25`.** The browser is located at two `C:/Program Files` chrome paths plus `/usr/bin/google-chrome` and `/usr/bin/chromium-browser`. Neither `/usr/bin/chromium` nor `/snap/bin/chromium` is listed, so on a VPS with a snap Chromium every browser test calls `pytest.skip` and `make test` goes green with CLAUDE.md's "a green flag is not a picture" silently unenforced. Add both paths, and install a real browser on the VPS. (The draft cited these lines as 21 to 24 and said so in the section certifying its own citations; line 21 is `REPO = ...`, and the `CHROME` assignment runs 22 to 25.)

**3.11 `requirements.txt`.** `opentimestamps-client` is not in it; it appears only inside the Docker shell string at `archive/witness.py:83` and the `Makefile` stamp targets. On Linux it becomes a first-class dependency. Do not add it to `requirements.txt` unless you have confirmed it installs on Windows too, or the owner's dev machine loses `pip install -r requirements.txt`. Install it explicitly in the bootstrap at the version P8 measured, 0.7.2, and add a comment in `requirements.txt` naming it and saying where it is installed.

**3.12 Proxy and CA environment.** There are **four** sessions built with default `trust_env`, not two: `archive/poll.py:264`, `archive/run_cycle.py:167`, `archive/witness.py:372` and `archive/gp_pull.py:131`. A VPS image that sets `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, `REQUESTS_CA_BUNDLE` or `CURL_CA_BUNDLE` changes routing or trust in all four with no log line. None are set on this machine.

The session that matters most is the one the draft did not name. `archive/gp_pull.py:55` posts the Space-Track identity and password to `/ajaxauth/login`; it is the only session in the archive that ever transmits a credential, so a `REQUESTS_CA_BUNDLE` or `HTTPS_PROXY` inherited by `ephemera-catalogue` is credential interception, which is a different order of consequence from a re-routed manifest GET.

Rather than editing code, assert in the bootstrap that none of the five is set, for **all six units** and not only the watcher, and record the assertion. Read the running process's own environment (`tr '\0' '\n' < /proc/<pid>/environ`), not `systemctl show -p Environment`: `show` reports `Environment=` directives only, so it cannot see a variable arriving through an `EnvironmentFile=` or through the manager's `DefaultEnvironment`, which is exactly how this runbook sets its own variables.

### Does the Windows console suppression still matter?

No. `pythonw.exe` disappears entirely: every `ExecStart` names the venv interpreter, and the reason `pythonw` existed at all was two console windows that were closed and killed the watcher on 30 Aug (PLAN.md, Day 0 item 1).

The artefact it left in code is `run_cycle.configure_logging` at `archive/run_cycle.py:49-50`: `if log_file is None and sys.stderr is None: log_file = spool / "run_cycle.log"`. Under systemd, stderr is always a valid file descriptor, so that branch is dead. Leave it; it is the Windows path's only protection and removing it is out of scope.

What still matters is the consequence, and it is a unit-file rule, not a code edit. **Never pass `--log-file` on Linux, and never set `StandardError=null`.** With a real-but-null stderr the fallback does not fire, and every log line from both modules goes to `/dev/null` with no complaint. Note also that the fallback file is named `run_cycle.log` regardless of which program is running, so `witness.py`, `ship.py` and `gp_pull.py` given `--log-file` would interleave into the watcher's file. There is no rotation anywhere in the code, only a plain `logging.FileHandler` at `archive/run_cycle.py:53`, and the current `run_cycle.log` is 509 KB over seven days, so journald is strictly better on both counts.

---

## 4. Secrets

Names only. Nothing below prints a value, and nothing in this migration adds an override to any guard.

### What must exist on the VPS

**`/opt/ephemera/infra/personal.env`**, mode 0600, owned by the service user, gitignored by `.gitignore:23` (`infra/*.env`). The path is fixed by `infra/guard.py:16` relative to `guard.py` itself, so it must live inside the checkout, not in `/etc`. Contents:

| Name | Read by | Consequence if missing |
|---|---|---|
| `EPHEMERA_AWS_PROFILE` | `infra/guard.py:48`, `infra/guard.sh:24` | `GuardRefused`, shipper exits with a traceback |
| `EPHEMERA_AWS_ACCOUNT_IDS` | `infra/guard.py:46` | empty is a refusal by design, not a pass |
| `EPHEMERA_AWS_FORBIDDEN_IDS` | `infra/guard.py:47` | checked before the allowlist (`:59-62`); a match wins |
| `SPACETRACK_USER` | `archive/gp_pull.py:44,48` | catalogue fails silently forever, exit 1 every 2 h |
| `SPACETRACK_PASS` | same | same |

Write this file **on the VPS with a heredoc, naming those five and nothing else**. Two reasons, and the draft got the second one badly wrong.

- CRLF. `infra/guard.sh:18` sources it with `.`, so a trailing CR becomes part of `AWS_PROFILE` and the `aws` CLI then fails at `guard.sh:32`. `infra/guard.py:28` is immune because it uses `splitlines()`, which drops the CR. Note the parser at `infra/guard.py:17` cannot represent a value containing a double quote and strips trailing whitespace, which constrains what a Space-Track password may contain.
- **The draft offered an `scp` of the live file as a safe shortcut. That sentence is struck.** The live `infra/personal.env` is not the five-name file the table describes: measured with `grep -oE '^[A-Z_]+=' infra/personal.env` (names only, no values read), it holds eight, including `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` and `EPHEMERA_CF_ACCOUNT_IDS`. `scp` copies the whole file, so the shortcut would put the Cloudflare token on the one host that already holds the AWS credential, the Space-Track credential and a GitHub write key, and would destroy the property this runbook advertises most. The heredoc is not a stylistic preference, it is the control.

**Suppress the shell history while you type it.** A heredoc typed at an interactive prompt is stored as one multi-line history entry and written to `~/.bash_history` when that shell exits, so the Space-Track password would sit in a second plaintext file that nothing here cleans up and that survives into the provider's snapshots, outliving any rotation of `personal.env`. Run `set +o history` first (or set `HISTCONTROL=ignorespace` and put a leading space on every line), write the file, then `history -c`. Asserted from shell behaviour, not measured on a VPS.

**AWS profile section.** `infra/guard.py:54` sets `os.environ["AWS_PROFILE"]` unconditionally before the first API call, so a `[profile <name>]` section must exist in a config file the service user can read. Under systemd `HOME` is unset unless the unit provides it, so `~/.aws/config` is not found and the failure surfaces as `guard: could not establish the AWS identity` (`infra/guard.py:57-58`), which reads like a credentials problem. Name the file explicitly in the shipper unit: `Environment=AWS_CONFIG_FILE=/etc/ephemera/aws-config`.

**The keys themselves go in that file at mode 0600, and never in a unit's `Environment=` or `EnvironmentFile=`.** The draft said either would do. They are not equivalent. Measured offline against botocore 1.43.81, no AWS call: with `AWS_PROFILE` naming a profile section that carries no keys and `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` in the environment, the credentials actually used resolve by method `env` - so `guard.py:54` pins the profile *name* only and the section becomes decorative. The refusal itself still holds, because `infra/guard.py:59-62` checks the account STS actually returns. But a long-lived secret access key in a unit environment is readable by any local user through `systemctl show -p Environment`, out of a unit file that is 0644 by default. The same measurement settles the question the draft left open: with no `[profile <name>]` section at all, boto3 raises `ProfileNotFound` even when env keys are present, and `guard.py:57-58` reports it as "could not establish the AWS identity". So the section must exist, and the keys belong in it and nowhere else.

**The same rule, and the same mechanism, for the Space-Track pair.** `archive/gp_pull.py:44` reads `SPACETRACK_USER` and `SPACETRACK_PASS` from `os.environ` first and only falls back to `infra/personal.env` when either is unset (`:46-48`, through `infra/guard.py:24-34`), so a unit carrying `Environment=SPACETRACK_PASS=...` would work - which is exactly what makes it the shortcut worth naming and refusing. The exposure does not depend on which credential it is: `Environment=` values are printed by `systemctl show -p Environment` to any local user, out of a unit file that is 0644 by default (asserted from systemd behaviour, not measured on a VPS). `EnvironmentFile=` only moves that exposure to the named file's own mode and owner, which is why `/etc/ephemera/ephemera.env` may be an `EnvironmentFile` at 0640: it holds no credential. **So no unit carries a credential value, of any kind.** The Space-Track pair lives in `personal.env` at 0600 and `gp_pull.py` reads it itself; the AWS keys live in the profile section of `/etc/ephemera/aws-config` at 0600; the SSH private half lives in `/etc/ephemera/ssh/`. What a unit may carry is a *path* to one of those files - `AWS_CONFIG_FILE=`, and the `-i /etc/ephemera/ssh/id_ed25519` in `GIT_SSH_COMMAND=` below - because a path is not a secret and the file's mode is the control.

**Blast radius, corrected.** `infra/guard.py:24-34` parses every `KEY=VALUE` line into an in-process dict, so the shipper process holds every name in the file, including Cloudflare and Space-Track, even though `enforce()` uses only the three `EPHEMERA_AWS_*` names and exports only `AWS_PROFILE`. That half stands. The draft then said `infra/guard.sh:18` is looser, because sourcing the whole file lets the `aws` CLI it spawns inherit everything. **That is measurably false.** `infra/personal.env` contains no `export` lines (`grep -c '^[[:space:]]*export' infra/personal.env` prints 0), so `.` sets shell variables that never enter the environment; in a sandbox, sourcing such a file and then running `bash -c 'echo ${SPACETRACK_PASS:-UNSET}'` printed `UNSET`, and `env | grep -c SPACETRACK` printed 0. `guard.sh:30` exports exactly one name, `AWS_PROFILE`, and that is all the `aws` CLI at `guard.sh:32` inherits (`guard_cf.sh:33` exports the Cloudflare pair, deliberately). The conclusion - do not put Cloudflare on the VPS - is unchanged. The supporting fact was wrong, and it was the fact the draft used to rank the two guards by risk.

**Credentials outside the checkout.** `.gitignore` now carries `/.aws/` and `/.ssh/` (`.gitignore:26-29`), because the draft put an SSH private key and an AWS credentials file inside the working tree of a public repository with no ignore rule for either: `git check-ignore -v` reported `.aws/config`, `.aws/credentials` and `.ssh/id_ed25519` as NOT IGNORED before that change, and a test now asks git rather than reading the file (`infra/tests/test_guard.py:295`). The automated committer could never have taken them, because `web/publish.py:168` and `:175-178` both carry a `-- web/dist` pathspec, but the VPS is where a human runs git by hand. Better still, do not put them there at all: unlike `personal.env`, whose location is pinned by `infra/guard.py:16`, both are named by absolute path in the units, so `/etc/ephemera/aws-config` and `/etc/ephemera/ssh/` cost nothing and are what this runbook's units use.

**`/etc/ephemera/ephemera.env`**, mode 0640, an `EnvironmentFile` for the units. Holds `EPHEMERA_CONTACT`, `LANG=C.UTF-8`, `PYTHONUNBUFFERED=1`, and no credential. `EPHEMERA_CONTACT` is not a credential, it is the address published in the User-Agent (`archive/poll.py:74-75`), but four entry points refuse to start without an address containing `@`: `archive/poll.py:255-257`, `archive/run_cycle.py:162-164`, `archive/witness.py:368-370`, `archive/gp_pull.py:128-130`, all returning exit 5. Put it in the `EnvironmentFile` rather than on the `ExecStart` line, because the command line is world-readable in `/proc`.

**Git push credential for `web/publish.py:185`.** The code runs a bare `git push` and delegates entirely to git's configuration; `remote.origin.url` in `.git/config` is HTTPS today, which on Windows resolves through Git Credential Manager. A systemd unit has no TTY and no credential helper, so the push fails and `web/publish.py:187` logs `push failed (will retry on the next run)`. Note what this now is and is not: a push failure is a credential problem, and a *rejected* push is not. Since the publisher fast-forwards before it builds (`web/publish.py:54-110`), a non-fast-forward rejection means a second publisher is pushing to the same branch, and the run before it would already have refused with "this clone and origin/main have diverged". Do not debug the deploy key on that message.

Use an **ed25519 SSH deploy key generated on the VPS**, added to the repository's Deploy Keys with write access, and set `git remote set-url origin git@github.com:Kira-Ryan/ephemera.git`. Over a PAT: the private half never leaves the VPS, it is scoped to this one repository, and it is revocable in the repository settings without touching the account. The unit needs `Environment=GIT_SSH_COMMAND=ssh -i /etc/ephemera/ssh/id_ed25519 -o IdentitiesOnly=yes -o UserKnownHostsFile=/etc/ephemera/ssh/known_hosts`, and that `known_hosts` must be seeded with GitHub's host keys at bootstrap, from GitHub's published fingerprints, not from a blind first connection.

**What that key can do, stated honestly.** The draft said no Cloudflare credential ever reaches the VPS and called that a real reduction in what one compromised host holds. True of the token at rest, false of the capability. `.github/workflows/deploy-site.yml:16` triggers on any push to `main` touching `web/dist/**`, `infra/cf_site.py`, `infra/guard_cf.py` or the workflow file itself, and `:51-54` puts `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` and `EPHEMERA_CF_ACCOUNT_IDS` into the environment and runs `python infra/cf_site.py deploy` from the tree that push just wrote. A repository deploy key with write access can push any ref, including changes to those exact paths, so **the VPS holds a credential that can cause chosen code to run with the Cloudflare token in scope**. The guard is not a barrier to that: `guard_cf.enforce()` is called at `infra/cf_site.py:169`, inside one of the four files such a push may rewrite. `web/publish.py:185` never force-pushes, but the key is not limited to what `publish.py` does with it. The deploy key is still the right choice over a PAT; the claim that has to be restated is "the token is not on the VPS", not "the VPS cannot reach the token". At minimum, add a `main` ruleset blocking force-push and deletion. Whether GitHub can path-restrict a deploy key's pushes on this plan is unverified.

Two more git settings that are not secrets and will otherwise stop the publisher dead:

- `git -C /opt/ephemera config user.name` and `user.email`. They are repo-local here, not global (deliberately: PLAN.md keeps the employer address out of the history), so a fresh clone has no identity and `git commit --only` at `web/publish.py:175-178` fails with "Please tell me who you are", logged as `commit failed` at line 180 and returning 1.
- Make the service user own the checkout, or add `git config --global --add safe.directory /opt/ephemera`. Without one of those, git refuses every command with "dubious ownership". In the draft that was worse than an inconvenience: the cycle count read `None` and the shrink guard disabled itself. It is now a refusal - `sync_with_published()` runs `git rev-parse --is-inside-work-tree` first and returns 1 with git's own message before anything is built (`web/publish.py:64-69`).

### The Cloudflare deploy: it stays on GitHub Actions

The site deploy does not need to happen on the VPS. `.github/workflows/deploy-site.yml` runs on `ubuntu-latest`, installs the pinned `blake3` from `requirements.txt` in its own step before any secret is in the environment, and runs `python infra/cf_site.py deploy` with `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` and the optional `EPHEMERA_CF_ACCOUNT_IDS` from GitHub secrets. `infra/cf_site.py:169` calls `guard_cf.enforce()` before its first write and exits on refusal. PLAN.md records this proven end to end on 31 Aug.

So the VPS pushes; the runner deploys. No Cloudflare **token** ever reaches the VPS, and nothing on the VPS deploys: `blake3` is a deploy-only import (`infra/cf_site.py:116`, pinned at `requirements.txt:25`) and is not installed there, `curl` is what the shell guard's zone check calls (`infra/guard_cf.sh:56`) and the gate stubs it (`infra/tests/test_guard.py:209-212`), and `infra/guard_cf.sh` runs there only inside that gate. Read that together with the deploy-key paragraph above: the token is not on the host, and the host can still cause a deploy to run. Both are true, and the second does not cancel the first - a host holding the token can act on Cloudflare alone and silently, a host holding a push credential has to go through a public commit on `main` and a workflow run that is visible in the Actions log.

A manual deploy from the VPS is deliberately not written up here, and the reason is what it costs rather than a preference. `infra/guard_cf.py:52-53` takes `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` from the environment or from `infra/personal.env`, so a hand deploy means the Cloudflare token at rest on the one host that already holds the AWS credential, the Space-Track credential and a GitHub write key - the whole property this section buys, spent to save a `git push`. It is not undone by deleting the two lines afterwards: whatever provider snapshot ran while they were there still holds them, so the price includes rotating the token. It also needs `blake3` installed on the VPS (`infra/cf_site.py:116`). It does not need `curl`: `cf_site.py` is stdlib `urllib` (`:18-19`, `:98-104`), and `curl` is `infra/guard_cf.sh:56`'s zone check. Never `wrangler`, on any machine: it was retired on 31 Aug after a sentinel test proved it ignores `CLOUDFLARE_ACCOUNT_ID` for a Pages deploy and targets an employer account from machine state.

### How the guards keep working

`infra/guard.py` has no platform dependency: `pathlib`, `re`, `os.environ`, and a `boto3` STS call. It works unchanged on Linux given the profile section and `AWS_CONFIG_FILE`. `archive/ship.py:289` calls `guard.enforce()` and nothing catches `GuardRefused`, so a misconfigured host fails loudly and terminally, which is correct.

`infra/guard.sh` needs bash (not dash: `#!/usr/bin/env bash`, `set -euo pipefail`, `${BASH_SOURCE[0]}`) and the AWS CLI on PATH (`guard.sh:32`). It invokes no interpreter at all, so it has nothing of 3.2's problem - checked by grepping every `.sh` in the repository. The shipper never touches it; only `infra/whoami.sh:4` does. **Correcting one survey:** the AWS CLI is *not* needed for the test gate. `infra/tests/test_guard.py:30-50` stages a copy of `infra/` with a **fake `aws` script** on PATH, and the module skips only when bash is absent (`:21`). So AWS CLI v2 on the VPS is optional and only for hand-running `whoami.sh`.

**No override path, and that is now actually checked.** The draft said "neither guard has an override flag, environment variable or argument, and `infra/tests/test_guard.py` greps for one". Two things were wrong with that sentence, in the paragraph an owner would read as the assurance. The grep iterated over `guard.sh` and `guard_cf.sh` only; it never read `guard.py` or `guard_cf.py`, which are the guards the VPS actually runs (`archive/ship.py:289`, `infra/cf_site.py:169`). And both Python guards take arguments that replace the check outright: `infra/guard.py:43` is `enforce(env=None, identity=sts_account)` and `infra/guard_cf.py:81` is `enforce(opener=None)`. Production passes neither, so this was a documentation defect and not a live hole. It is now covered: the grep runs over all four guards, over executable source with comments and docstrings stripped - so a guard's own sentence about having no override cannot be what makes the test green - and with a `(?<![a-z])` lookbehind so `enforce` does not match on `force` (`infra/tests/test_guard.py:114-147`); and a second test parses every production `.py` under `archive/ infra/ score/ tools/ web/` and asserts every `guard.enforce` / `guard_cf.enforce` call passes zero arguments, over the four call sites it found (`infra/tests/test_guard.py:150-176`). Nothing in this migration adds an override.

---

## 5. systemd units and timers

Layout assumed: clone at `/opt/ephemera`, venv at `/opt/ephemera/.venv`, spool at `/srv/ephemera/spool`, service user `ephemera` owning both. Every unit carries:

```
[Service]
User=ephemera
Group=ephemera
WorkingDirectory=/opt/ephemera
EnvironmentFile=/etc/ephemera/ephemera.env
```

and none of them sets `StandardError=`, so stderr goes to the journal (section 3, "console suppression"). Set `Storage=persistent` in `journald.conf` and confirm with `journalctl --disk-usage`. On the watcher, set `LogRateLimitIntervalSec=0` in the unit: journald's default drops bursts silently after 10,000 messages in 30 s, and the poller logs a warning per failed attempt (`archive/poll.py:220-224`), so a bad cycle would have its evidence quietly discarded, which is exactly what CLAUDE.md forbids.

### 5.1 `ephemera-watcher.service`, long-running

```
[Service]
Type=simple
ExecStart=/opt/ephemera/.venv/bin/python -u /opt/ephemera/archive/run_cycle.py \
  --spool /srv/ephemera/spool --workers 16 --min-free-gb 25 --interval 120
Restart=always
RestartSec=10
SuccessExitStatus=4
KillSignal=SIGINT
TimeoutStopSec=400
LogRateLimitIntervalSec=0
```

A service and not a timer, for three reasons that are in the code. The tick interval is internal: `--interval`, `type=float, default=120.0`, "seconds between manifest checks" at `archive/run_cycle.py:152`, slept at line 190, and the loop at 171 to 193 runs forever unless `--once` or `--ticks` is given, which exist for the tests. The conditional-GET state is in memory only: `state` is a local dict created at line 169 and used at 93 to 101, so a timer re-executing `--once` would lose the ETag every invocation and turn D17's conditional GET into 720 full 821 KB manifest downloads a day, about 590 MB a day of pointless traffic against the operator. And a tick can *be* the pull: `tick()` calls `poll.main()` inline at lines 118 to 119 and a full cycle takes 45 to 116 minutes, so a 120 s timer would start overlapping pollers on one spool, and there is no spool lock anywhere (PLAN.md records this as accepted, single-writer by design).

`--interval 120` stays at the code default because D17 fixes the number, and it bounds detection lag to two minutes against a 480 minute cadence for the cost of one conditional GET.

`SuccessExitStatus=4` because a graceful stop returns `poll.EXIT_INTERRUPTED = 4` (`archive/poll.py:61`, returned at `archive/run_cycle.py:178` and `:193`), so without it systemd marks the unit failed on every clean stop.

`Restart=always` because an interrupted pull **deliberately stops the watcher** (`archive/run_cycle.py:183-185`), so without a restart policy the poller stays down after any stop.

`KillSignal=SIGINT` rather than the default SIGTERM. `archive/poll.py:233` maps SIGTERM to `_thread.interrupt_main()`, which is one level of indirection, and `interrupt_main` is a no-op when SIGINT is `SIG_IGN`, which a background shell sets. SIGINT delivers a real signal and skips the question. It also makes explicit why you must **never launch this under `nohup`, `screen` or a background shell**: the SIGTERM handler still replaces the default terminate action, so the net effect there is a process that ignores SIGTERM and only dies to SIGKILL.

`TimeoutStopSec=400` because the default 90 s is wrong on two counts: a worst-case stop is up to `--interval` seconds asleep at `archive/run_cycle.py:190` plus up to `TIMEOUT_S=120` for an in-flight download (`archive/poll.py:56,185`; line 386 waits for in-flight futures on shutdown). A SIGKILL mid-pull means the "interrupted" record promised at `archive/poll.py:428,439-441` is never written and `cycle.json` stays `in-progress`. The next start re-pulls that cycle, so it self-heals, but the stop contract is not honoured.

**Unverified and worth testing first on the VPS:** the SIGTERM path has never been executed. `archive/tests/test_poll.py` fires `_thread.interrupt_main()` directly, which exercises the `KeyboardInterrupt` branch and not the wiring at `archive/poll.py:233`. Windows cannot deliver a real SIGTERM, so this is only testable on Linux. By the repository's own "test the caller" rule the handler is currently unverified. Write that test on the VPS before the cutover.

### 5.2 `ephemera-witness.service`, long-running

```
[Service]
Type=simple
ExecStart=/opt/ephemera/.venv/bin/python -u /opt/ephemera/archive/witness.py \
  --spool /srv/ephemera/spool --ots ots --ots-bin /opt/ephemera/.venv/bin/ots --interval 300
Restart=always
RestartSec=30
SuccessExitStatus=4
KillSignal=SIGINT
TimeoutStopSec=700
```

A service, not a timer. The loop at `archive/witness.py:381-404` ends in `pause(args.interval)` with `--interval` defaulting to 300.0 at line 360; `--once` and `--ticks` exist as seams for `Makefile:46` and the tests. Three reasons a timer is wrong: a pass has no upper bound, since one cycle submits a manifest plus ten samples at a 12 s gap with two 300 s-timeout HTTP calls each, so a bad pass exceeds an hour and a five-minute timer would spend its life skipping. The pass returns 1 whenever any step recorded an error (line 399), and permanent already-recorded losses are normal, so a timer would show the unit failed more or less forever. And all cadence state is on disk anyway: the hourly upgrade backoff is persisted as `last_upgrade_attempt_utc` against `--upgrade-every` default 3600.0, and daily roots are keyed by UTC date with a build-once guard.

300 s against an 8 hour feed cadence gives roughly 96 chances to capture inside a cycle's live window, which is the only window that exists.

`--ots ots` explicitly, so that even before edit 3.3 lands the Docker fallback cannot engage. Note that `witness.py` imports no `signal` and never calls `poll._install_sigterm_as_interrupt`, so today a `systemctl stop` kills it mid-pass. `KillSignal=SIGINT` improves this only during the sleep: `KeyboardInterrupt` is a `BaseException`, so a SIGINT during a pass is not caught by the per-cycle `except Exception` at line 389 and unwinds out of `main` with a traceback and a non-zero exit, which `Restart=always` covers. If you want a clean stop, install the poller's handler in `witness.py` and wrap the whole `while` loop in `except KeyboardInterrupt: return poll.EXIT_INTERRUPTED`.

### 5.3 `ephemera-ship.timer` plus `ephemera-ship.service`, oneshot

```
# .service
Type=oneshot
Environment=AWS_CONFIG_FILE=/etc/ephemera/aws-config
ExecStart=/opt/ephemera/.venv/bin/python -u /opt/ephemera/archive/ship.py \
  --spool /srv/ephemera/spool --once --max-cycles 1
TimeoutStartSec=2h
SuccessExitStatus=SIGTERM

# .timer
OnBootSec=5min
OnUnitActiveSec=30min
```

**Why `OnBootSec=` is in every timer block here and `Persistent=` is in none of them.** systemd.timer(5) defines `OnUnitActiveSec=` as "a timer relative to when the unit the timer unit is activating was last activated". On a freshly installed timer with no other trigger there is no such moment, so there is nothing to measure from and the timer has no next elapse. The same section says a timer set with `OnBootSec=` or `OnStartupSec=` that is already in the past "will immediately elapse and the configured unit is started", and then: "This is not the case for timers defined in the other directives." Measured with transient units on systemd 249 (Ubuntu 22.04 under WSL, 13 Sep 2026), not on the VPS: `systemd-run --user --on-unit-active=60` gave `NEXT n/a`, `LEFT n/a` in `systemctl list-timers --all` and `NextElapseUSecMonotonic=infinity`, with `ActiveState=active`. It is loaded, it looks healthy, and it never fires. Adding `Persistent=true` to that same unit changed nothing at all: still `infinity`. That is the second half of the correction, and systemd.timer(5) states it outright under `Persistent=`: "Note that this setting only has an effect on timers configured with `OnCalendar=`." Beside a monotonic timer it is inert, so any claim that it recovers a missed run is wrong. The same probe with `--on-boot=300 --on-unit-active=60` fired immediately (the machine had been up far longer than five minutes), then scheduled its next elapse 57 s later from `OnUnitActiveSec=`. That is the shape all three timers want: `OnBootSec=` gives the chain its first activation, at install and again after every reboot, and `OnUnitActiveSec=` holds the cadence from each activation after that. A consequence worth planning for rather than being surprised by: installing one of these timers also runs its service once, straight away, which is exactly what C7 and C10 want.

If you would rather have catch-up after a long power-off, that is the one thing `Persistent=` buys, and it needs a calendar expression to buy it: `OnCalendar=*-*-* 00/4:00:00` with `Persistent=true`, and no monotonic lines. Unmeasured here, and not what a host meant to stay up needs. Re-check whichever you choose on the VPS's own systemd at C2: `systemctl list-timers --all` is the whole test, and section 7 check 1 is where it is a gate.

This is a port, not a redesign: the live Windows task already runs `--once --max-cycles 1` on a PT30M repetition with a PT2H execution limit. `--interval` exists at `archive/ship.py:279` with default 1800.0 but production does not use it, and the code argues against it: in loop mode `main()` never returns and the per-pass result is only logged, whereas `--once` returns 0 or 1 and hands systemd a real exit status. Nothing survives in memory between passes.

Do **not** add `SuccessExitStatus=1`. A pass that recorded an error should show as a failed unit so you notice it in `systemctl --failed`; that is better observability than Task Scheduler ever gave. `SuccessExitStatus=SIGTERM` is there so a stop during an upload does not read as a defect, and it must be spelled as the **signal name**, which the draft got wrong. systemd parses a bare number in `SuccessExitStatus=` as an exit *status*: a process killed by SIGTERM is reported as CLD_KILLED with status SIGTERM and never as exit code 143, and for `Type=oneshot` the four signals SIGHUP, SIGINT, SIGTERM and SIGPIPE are explicitly not in the implicit clean-exit set the other types get. So `SuccessExitStatus=143` would have covered nothing that can actually happen here - `ship.py` only ever returns 0, 1 or 4 (`archive/ship.py:310,314`) - and a `systemctl stop` mid-upload would still have left the unit failed, under a gate (section 7, check 1) that requires `systemctl --failed` to be empty.

**`SuccessExitStatus=SIGTERM` covers the stop and only the stop.** A `TimeoutStartSec=2h` expiry is not reported as a signal: systemd fails the job on the timeout itself, whatever the process then does, so the directive cannot reach it. Measured with transient `Type=oneshot` units on systemd 249, the directive set on both: `systemctl stop` during the run gave `Result=success`, `ActiveState=inactive`, while the same unit with `TimeoutStartSec=2` on a sixty-second command gave `Result=timeout`, `ActiveState=failed`, with `ExecMainCode=2` and `ExecMainStatus=15`, that is, killed by exactly the SIGTERM the directive names, and failed anyway. Without the directive the stop case gave `Result=signal` and `ActiveState=failed`, which is what it is there to fix. So a pass killed at the two-hour limit does land in `systemctl --failed`, and it should: 9.3 GB that did not finish uploading in two hours is a fault to look at, not routine. Check 1 gates on that rather than contradicting it.

`--max-cycles 1` because one cycle is 9.28 GB and the pass duration from a datacentre uplink is unmeasured. Raise it only after the day-one S3 measurement on the real host; P8 measured 55.7 MB/s from eu-west-1 on AWS, which suggests the ceiling is the feed and not S3. Note that `--max-cycles` budgets uploads only (`archive/ship.py:302-307`): record re-syncs and the retention delete still run for every cycle every pass, which is what keeps a 30-minute cadence worth having when nothing new is ready.

`TimeoutStartSec=2h` mirrors PT2H, and accepts that the timeout kills mid-upload. Edit 3.6 is what makes that acceptable, because without it every such kill orphans another 9.3 GB tar.

Two things this unit does not solve. First, the in-flight S3 multipart upload is abandoned on any kill; D15's amendment says stale multipart uploads abort after 7 days, but I made no AWS call and did not verify that lifecycle rule exists on `ephemera-space-raw`. Check it. Second, `archive/ship.py`'s retention deletes `files/` at `--keep-days` without checking whether a visibility report exists, so a cycle not scored within 3 days becomes permanently unscoreable. At 48 score passes a day against 3 cycles a day the margin is enormous, but during a backlog drain raise `--keep-days` to 5.

### 5.4 `ephemera-catalogue.timer` plus `.service`, oneshot

```
# .service
Type=oneshot
ExecStart=/opt/ephemera/.venv/bin/python -u /opt/ephemera/archive/gp_pull.py \
  --spool /srv/ephemera/spool --once
TimeoutStartSec=10min

# .timer
OnBootSec=5min
OnUnitActiveSec=2h
RandomizedDelaySec=300
```

A timer, and the code says so four ways. A pass carries no state forward: the only survivor is the `requests.Session`, and `archive/gp_pull.py:55` re-authenticates every pass, so the session buys connection reuse within a pass and nothing across passes. `--once` surfaces failure as an exit code (`return 0 if ok else 1`, line 143), whereas in loop mode the identical failure is only logged at lines 138 to 141. The loop drifts, because `pause(args.interval)` starts after the pass completes, so the true period is 7200 s plus the pass duration; `OnUnitActiveSec=` holds the cadence from each activation instead, and `OnBootSec=5min` is what gives it a first activation to measure from, at install and again after a reboot. Without that line this timer never fires at all, and `Persistent=` would not have saved it (5.3). And SIGTERM is unhandled here (line 146 catches only `KeyboardInterrupt`), so a service would be killed mid-sleep with no clean path.

2 hours is a rate-policy choice stated in the docstring at `archive/gp_pull.py:13-14`: one login and one query per pass, 24 requests a day against the user agreement's 30 per minute and 300 per hour. `RandomizedDelaySec` because the code applies no jitter of its own.

One observability point: gp_pull writes **no heartbeat**. A dead catalogue puller does not move the D18 coverage figure and shows only as a stale "last fetched" on the site (`web/pages.py:620-621`). The unit's own state is the primary health signal, so wire `OnFailure=` to something that reaches the owner.

### 5.5 `ephemera-score.service`, long-running

```
[Service]
Type=simple
ExecStart=/opt/ephemera/.venv/bin/python -u /opt/ephemera/score/run.py \
  --spool /srv/ephemera/spool --interval 1800 --max-cycles 1 --workers 4
Restart=always
RestartSec=60
```

`--interval` defaults to 1800.0 at `score/run.py:128` and drives `while True: one_pass(...); time.sleep(...)` at lines 133 to 137, which is the same 30 minutes the Windows task already uses. A service rather than a timer because `score/run.py:136` returns 1 when `result["errors"]` is non-empty, but a per-cycle scoring failure is *designed* to be recorded and continue (lines 111 to 113): a timer with `Restart=on-failure` would treat an ordinary recorded error as a unit failure. The built-in loop is also sequential by construction, which is exactly the guarantee `MultipleInstances=IgnoreNew` gives today. The trade-off, stated plainly: a service never surfaces an exit code, so the only signal is the log and `run.json`, which nothing reads.

**Do not port `ExecutionTimeLimit=PT25M` as `RuntimeMaxSec`.** One cycle takes about 8 minutes at 4 workers on the home PC, and a VPS with fewer cores can exceed 25 minutes. A mid-pass kill is precisely what loses a globe pack. With edit 3.5 in place a mid-pass kill is safe and the cycle is retried; without it, a deadline is the thing that breaks the archive's derived layer.

One Linux-only behaviour change to watch, not a defect: `score/visibility.py:281-283` creates a `ProcessPoolExecutor` with no `mp_context`, so the start method flips from spawn on Windows to fork on Linux. On the normal path the parent is numpy-free at fork time, because numpy arrives with `from skyfield.api import ...` inside the children. The exception is a cycle yielding 0 or 1 tasks, where `score_one` runs in the parent (line 285) and imports numpy into a process that lives forever inside the `while True` loop, after which every later fork comes from a numpy-initialised parent. The mechanism is real; nobody has reproduced a hang. Flagged, not fixed.

### 5.6 `ephemera-ledger.timer` plus `.service`, oneshot

```
# .service
Type=oneshot
Environment=LANG=C.UTF-8
Environment=GIT_SSH_COMMAND=ssh -i /etc/ephemera/ssh/id_ed25519 -o IdentitiesOnly=yes -o UserKnownHostsFile=/etc/ephemera/ssh/known_hosts
ExecStart=/opt/ephemera/.venv/bin/python -u /opt/ephemera/web/publish.py --spool /srv/ephemera/spool
TimeoutStartSec=15min

# .timer
OnBootSec=5min
OnUnitActiveSec=4h
```

A timer driving a oneshot, never a service. `web/publish.py`'s argparse declares only `--spool`, `--no-push`, `--allow-shrink` and `--log-file`: there is **no** `--interval` flag and no default interval anywhere in the file. `main()` performs exactly one sync with origin, one build, one lint, one shrink check, one commit and one push, and returns. The 4 hour figure lives entirely in the scheduler, and it needs `OnBootSec=` beside it or the timer never elapses (5.3). Installing the timer at C10 therefore also runs the first publish immediately, which is what C10 verifies.

This unit now makes a network call before it builds. `sync_with_published()` (`web/publish.py:54-110`, called at `:131`) runs `git fetch`, fast-forwards the branch when it is strictly behind its upstream, and refuses to build at all when git cannot operate on the tree, when the fetch fails, or when the branch is both ahead and behind. That is what closes the C10 wedge in section 6. It also changes the failure mode for a host that cannot reach GitHub: the run now returns 1 before building, instead of building, committing locally and failing on the push. Both already returned 1, so the unit's own failure signal is unchanged.

`TimeoutStartSec` is mandatory here because every `subprocess.run` in the file is called with **no `timeout=`** - `git()` at `web/publish.py:28-29`, which is now also the `git fetch`, and the claims lint at `:144-145` - so a hung fetch or a hung push would otherwise run forever; on Windows the task's execution limit bounded it. A hung fetch specifically is unmeasured; `TimeoutStartSec` is what bounds it. There is also no lock file in `publish.py`, so overlap protection is entirely systemd's refusal to start a second instance of a running oneshot.

`ExecStart` must be the **absolute path to `web/publish.py`**, not `python -m web.publish`, because `web/publish.py:135` does a bare `import build` with no `sys.path` insertion; it works only because Python puts the script's own directory on `sys.path[0]`, and `PYTHONSAFEPATH=1` would kill it.

`LANG=C.UTF-8` because of the un-encoded subprocess decode at `web/publish.py:144-145`.

Cost is not the constraint: a full build against the real spool was timed at about 1.2 seconds when it held 33 cycles (9 Sep); it holds 44 now. 4 hours is a freshness choice against an 8 hour feed cadence, so the page is never more than half a cycle stale. `score/run.py` produces new reports every 30 minutes, so a scored cycle waits up to 4 hours to appear; tighten to 1 hour if that matters, the build cost is noise.

**One thing to install for this unit that is easy to miss:** `fonts-dejavu-core`. `web/brand.py:133-142` names `CascadiaMono.ttf`, `consola.ttf`, `DejaVuSansMono.ttf` and `georgia.ttf`, `DejaVuSerif.ttf`, catches `OSError` per name, and drops through to `ImageFont.load_default` with **no warning**. On Linux only the DejaVu names can ever resolve, so without that package the 1200x630 social card renders in Pillow's bundled default at whatever metrics it likes, on every deploy, silently.

---

## 6. Cutover without losing a cycle

The feed drops each set after about eight hours, so a gap is permanent. The whole point of the order below is that the poller is the one component where running two copies is safe, so it goes first with overlap and everything else follows behind it inside one cycle.

### Can both pollers run at once? Yes, and they should

They must be on **separate spools on separate machines**. There is no lock anywhere and single-writer is a design assumption (PLAN.md, open review items). Two pollers on one spool would race on `heartbeat.json.tmp` and on the cycle record.

On two spools, D10 does exactly what it was written for: identity is the manifest SHA-256, so both produce `cycle_<same sha12>`, and D11 removed the wall-clock date precisely so a resume or a second poller across UTC midnight does not produce a different identity. When both complete, both produce the same root under the D09 construction. That is not a duplicate, it is the first real cross-poller check this project has ever run, and it is direct evidence for PLAN item 9. P8 has already observed it once, on manifest `34e224670e92`, from Cape Town and eu-west-1. Record the C4 comparison in the probe as well.

Note that the case-insensitive duplicate rule at `archive/poll.py:111-129` and the colon rejection at `archive/poll.py:95` are Windows-shaped rules that now bind Linux. **Keep them.** A Linux poller must refuse exactly what the Windows poller refuses, or the two roots can differ and D10's guarantee evaporates. No live cycle has ever tripped either: all 44 `cycle.json` records show `manifest_anomalies = 0` (checked 13 Sep).

The one real cost of the overlap is doubled load on `api.starlink.com` from two IPs during the window, which is D03's intent anyway. Keep the window to one or two cycles, not a week.

### What must never run twice

**Shipper. Absolutely never.** Both hosts would PUT to the same key `cycles/<sha12>/files.tar`, and the tars are **not** byte-identical across hosts: the five record members are added with `tarfile.add` (`archive/ship.py:132-134`), which copies uid, gid, uname, gname and mode from the filesystem, and Linux records the service user's real values where Windows records mode 666, uid 0 and empty names. So two shippers would write two different objects to one versioned key, each host's `ship.json` claiming its own SHA-256, and a restore verified against one would fail against the other. This is the single most damaging thing that can go wrong in the cutover.

**Ledger publisher. Never.** Both would commit to `main` and the loser's `git push` would be rejected non-fast-forward. Since the fix at `web/publish.py:54-110` this no longer wedges silently: the second publisher's next run fetches, sees the branch both ahead and behind, and refuses to build with `REFUSING to build: this clone and origin/main have diverged`, naming the counts. It still never merges, rebases or force-pushes, because `web/dist` is a build product and reconciling two hosts' builds of one spool by rebase would publish an interleaving neither host ever built. A refusal is a fault to settle by hand, which is the point: one host runs the ledger.

**Witness. Never, in practice.** Two witnesses would double Save Page Now submissions inside the one window that cannot be redone, and P8 measured only three captures at the 12 s gap from one datacentre IP, which is not enough to say how much throttle headroom a second capturing host would have.

**Catalogue. Never.** Two clients logging into one Space-Track account from two IPs is undocumented and could look like abuse. The rate itself is trivial, 48 requests a day against 30 a minute and 300 an hour, but a soft block looks identical to a maintenance page because `archive/gp_pull.py:59-60` raises on any non-200 with no retry. A two-hour gap in catalogue snapshots costs a shifted pairing and nothing irreplaceable; an account lock costs the whole `score/` layer.

**Score. Wasteful, not dangerous.** Different spools, different outputs. Still cut it over as one switch.

### Moving the 44 cycles and their records

Total non-raw state is about **1.06 GB**, measured 13 Sep with `du`: 44 cycles of records excluding `files/` (396 MB), `spool/score` (443 MB), `spool/gp` (215 MB), `heartbeats.jsonl` (3.13 MB), `spool/daily` (under 1 MB). That is a single tar over ssh, minutes not hours.

**Transport, and it has to implement the per-file rule below rather than fight it.** Git for Windows ships GNU tar 1.34, `ssh`, `scp` and `sftp`, and no `rsync` (measured on the owner's machine, 13 Sep 2026). So the tar is the transport: build it on Windows excluding `files/`, `scp` it over, and extract it on the VPS with **`tar --skip-old-files -xvf`**, never a plain `tar -xf`. A plain extract overwrites, which is the exact opposite of the per-file rule that governs this whole section; `--skip-old-files` decides per file, on existence alone, which is that rule. Measured with GNU tar 1.34 on both ends: an archive holding `cyc/cycle.json`, `cyc/MANIFEST.txt` and `cyc/root.txt.ots`, extracted into a directory that already held the first two, left both existing files byte for byte untouched, extracted `root.txt.ots` into that same existing directory, named every skip on stderr as `tar: cyc/cycle.json: skipping existing file`, and exited 0. **Capture that stderr.** It is the per-file record of what the VPS already had, and C5 reads it.

Two neighbours of that flag, measured at the same time. `tar -kxvf` (`--keep-old-files`) leaves disk in the identical state but reports each existing file as `Cannot open: File exists` and exits 2, so a genuine error hides among the expected ones; prefer `--skip-old-files` with the captured log. And before extracting, run `tar -df <archive>` in the target directory: it lists every member whose bytes differ from what is on disk (`cyc/cycle.json: Size differs`), warns on every member that is absent, and exits 1. That is the pre-flight audit of precisely what the skip rule is about to withhold, and it is what turns "the VPS keeps its own copy" from an assumption into a list.

**If tar is all you have, tar is enough.** The per-file rule never needed rsync; it needed the extract flag. The one case that needs more is a tar too old to have `--skip-old-files`: then extract into an **empty** staging directory on the VPS and merge from there with `cp -rn`, which is also per file (`cp` measured at coreutils 8.32; on coreutils 9.x `--update=none` is the preferred spelling and `-n` is deprecated, unverified here). What you must never do on a populated spool is a plain `tar -xf` or a plain `cp -r`.

**Binary-safe only.** `score/resummarise.py:35-39` rebuilds every report's summary from the gzipped rows files, and `score/catalogue.py:53-56` hard-fails a snapshot whose bytes do not hash to its record, so any text-mode or CRLF-translating copy destroys both silently.

**The rule that governs every directory below: copy per FILE, never per directory.** The draft said to use "`--ignore-existing` semantics at the cycle-directory level: a cycle directory the VPS already pulled itself must never be overwritten by the Windows copy". **That rule is struck.** Per-directory skipping is what produced the two worst defects found in this runbook. For every cycle both hosts pulled, it would have withheld `ship.json`, so `needs_upload()` returns "not yet shipped" (`archive/ship.py:151-155`) and the VPS re-uploads a byte-different tar to a key S3 already holds; and it would have withheld `root.txt.ots` and `witness.json`, so `archive/witness.py:191-192` re-stamps a root that already carries a Bitcoin attestation and `archive/witness.py:282,294-296` records Wayback captures as never made that Windows had verified. On this pair of hosts the per-file rule is `tar --skip-old-files` at extract time (Transport, above); `rsync --ignore-existing` and `cp -rn` are the same rule wherever those tools exist. Inside a cycle directory the VPS pulled itself, every file the VPS lacks must land. `cycle.json` is the one file for which "the VPS's copy stays" is not automatically right, and the next paragraph is about that.

**Which host's `cycle.json` wins, and why it is not always the VPS's.** The draft's rule was "the VPS's `cycle.json` stays", unconditionally, and C4 compares exactly one cycle. Windows keeps polling until C11, so every overlap cycle after that first one gets no comparison at all, and the two records are not interchangeable. A pull that ends gapped writes `status: gaps` and `merkle_root: null` and **deletes any `root.txt` it had**; a complete one writes the root (`archive/poll.py:425-435`). Keeping the VPS's gapped record where Windows completed the same cycle keeps the worse of the two, and the consequences are not cosmetic:

- **The VPS never witnesses that cycle, ever.** `archive/witness.py:260-262` returns immediately for a record with no `merkle_root`, so no stamp and no Wayback capture, however many 300 s passes run. The Windows `root.txt.ots` and `witness.json` copied in at C6 then sit beside a record saying the cycle has no root.
- **Its day's root loses a leaf.** `archive/witness.py:228-232` takes each leaf from `rec["merkle_root"]` and counts a rootless cycle into `gapped_cycles_excluded` instead (`:244`), so a `daily/<D>` the VPS builds for that day is a root over fewer cycles than the one Windows already built, stamped and published for the same day.
- **The site publishes one fewer complete and one fewer anchored cycle.** `web/build.py:235` counts complete as `c["merkle_root"]` being set, and `:249-250` publishes both totals from that list.
- **And the shipper replaces the good tar in S3 with the gapped one.** A `gaps` record still ships (`archive/ship.py:179-180`). With Windows' `ship.json` re-synced at C9, `files_fingerprint()` over the VPS's gapped record (`archive/ship.py:83-92`) does not equal the `shipped.files_fingerprint` the complete tar was bound to, so `needs_upload()` returns "the record has changed since the tar was built" (`archive/ship.py:170-171`), the VPS packs the files it does have and PUTs a second version of `cycles/<sha12>/files.tar` over the complete one. Object Lock is in governance mode, so both versions then stay.

**So the better record wins, not the local one.** Before the copy, compare the two `cycle.json` files for every cycle both hosts hold. Both hosts pulled the same manifest, so `manifest_sha256` and `files_listed` agree by construction (D10) and the comparison is only about what each host actually got:

1. **One `status` is `complete` and the other is `gaps`: the complete record wins, always.** Take that host's `cycle.json` **and** its `root.txt` **and** the `files/*.gz` the other host lacks, as one move. A record without its files leaves a cycle naming files that are not on disk, and the next ship pass raises `CorruptCycle` at `archive/ship.py:107` and returns 1 every thirty minutes until someone fixes it.
2. **Both `complete`:** the roots are identical or C4 has already stopped the cutover. Either record will do; keep the earlier `first_seen_utc`, per C4.
3. **Both `gaps`:** the higher `files_recorded` wins; record `files_failed`, `files_not_attempted` and the `failures` map from both, because that is the only place the disagreement is written down. Neither poller can merge the other's files into its record, so do not hand-build a union: note it, and let a resumed pull on the surviving host heal the cycle while its manifest is still current. A rolled manifest is never retried (D17), so once the window has closed the gap is permanent and is published as a gap.
4. **`manifest_anomalies` must agree.** It is derived from the manifest bytes, so a difference means something is wrong with one host rather than with the feed. All 44 live records show 0 (checked 13 Sep).

`etag_cache.json` is the conditional-GET state for the stored `files/` (`archive/poll.py:186-194` returns the cached record on a 304), so it belongs with whichever host's `files/` you keep and moves with them.

**And the bulk copy is never the last word.** Windows keeps witnessing until C6 and keeps shipping until C9, so a `witness.json` or a `ship.json` copied at C5 is a snapshot that goes stale minutes later: the live spool's gap between `finished_utc` and `shipped.uploaded_utc` is **36 to 64 minutes, median 55**, across the 31 of 44 cycles uploaded once the shipper was current (measured 13 Sep over every `cycle_*` under `Z:\ephemera\spool`; all 44 are shipped). The draft's "45 to 70 minutes across every shipped cycle" was wrong in both directions: four cycles sit under 45 minutes, the fastest at 36.1, and thirteen sit over 70. Every one of those thirteen was uploaded inside a single backlog drain between 2026-09-02T16:53Z and 2026-09-03T04:35Z, when the shipper first worked through the cycles that predated it at `--max-cycles 1` per 30-minute pass with each 7 to 15 GB tar taking most of an hour on the home uplink; their gaps run from 49 minutes to 3.3 days, the longest being `cycle_72bcd7796b49`, finished 2026-08-30T15:22:53Z and uploaded 2026-09-02T23:33:20Z. That tail is a backlog signature, not a cadence. What it means for the cutover is unchanged and slightly sharper: the feed rolls about every 8 h, so a C5-to-C9 window covers one to three shipped cycles in steady state, and if you enter the cutover with a shipping backlog it covers however many that backlog holds. Each component's cutover step below therefore **re-syncs its own per-cycle files after the Windows unit for that component is stopped and before the VPS one is started.** C5 is a first pass, not the authority.

Per-directory rules:

- **`cycle_*/`**, everything except `files/`: `cycle.json`, `MANIFEST.txt`, `root.txt`, `root.txt.ots`, `root.txt.ots.bak`, any `root.txt.ots.stale-*`, `witness.json`, `ship.json`, `etag_cache.json`. Copy `root.txt.ots` **byte-exact and before the witness unit ever starts**: if it is absent, `proof_matches()` returns False, the cycle is stamped again, and its committed timestamp becomes the migration date. The Bitcoin attestation evidence for the original stamping time is destroyed and cannot be recovered (live example: `cycle_1b3b36972d57` carries `stamped_utc` 2026-09-08T05:02:06Z and attested block 966019). `ship.json` is equally critical in the other direction: without it `needs_upload()` returns "not yet shipped", and for the 35 cycles whose `files/` are already deleted that means `pack()` raises `CorruptCycle` and the pass returns 1 every thirty minutes forever. The witness files are re-synced at C6 and `ship.json` at C9; see those steps.
- **`daily/`**: complete or not at all, **and transferred at C6 after the Windows witness has been stopped**, not at C5. If `root.txt` exists for a day without `daily.json`, `archive/witness.py:238` raises `FileNotFoundError`, which the caller's blanket handler at `:394-396` catches, so the **entire** daily step aborts for **every** day on **every** pass with only "daily-root step crashed" in the log, unlike `witness_cycle`, which isolates per cycle. And if a day's `root.txt` is missing entirely, the day is rebuilt from whatever `cycle.json` files are then present; if any of that day's cycles did not migrate, the rebuilt root differs from the one already stamped and published, which is a silent falsification. The reason for moving the transfer is in C6: `archive/witness.py:212-233` builds a daily root for every UTC day strictly before today on every 300 s pass, so any UTC midnight between the copy and the stop gives Windows a day the VPS will never receive and will later rebuild itself, because `archive/witness.py:237` skips only a day whose `root.txt` is already present.
- **`gp/`**: complete, and the directory **names** must survive byte-identical. `score/catalogue.py:66` sets `snapshot_id = snapshot_dir.name`, `score/visibility.py:318` writes it into every report as `catalogue_snapshot`, and `score/globe_pack.py:109` resolves it straight back to `spool/gp/<name>`. Renaming on migration silently breaks every existing report's pack rebuild. Copying `gp/` also fixes the first-pass duplicate: `latest_sha()` compares against the newest record in its own spool, so on an empty `gp/` the first VPS pass would re-store a byte-identical catalogue and put a duplicate sha12 row in the ledger.
- **`score/`**: complete and binary-safe. 40 cycles carry a visibility report and only 9 of 44 still hold `files/`; for the rest the report and its rows file **are** the measurement, and re-scoring them would need a Deep Archive restore. If `score/` is absent nothing errors: the cycles that still hold files are re-scored from scratch, and every regenerated report carries a fresh `as_of` (`score/visibility.py:305`), so the site republishes new as-of dates for measurements that did not change.
- **`heartbeats.jsonl`**: **concatenate, do not copy, and then say what the merged file makes the site publish.** The VPS watcher started at C3, two steps before this copy, and `archive/run_cycle.py:141` appends a line on every tick from that moment, so copying the Windows file over it destroys every VPS tick since C3 and skipping the copy loses all of the Windows history. `web/build.py:174-180` reads that single file as the only source for D18 observed coverage, taking nothing from each line but its `utc` field, and `coverage_24h` (`web/build.py:185-203`) returns `None` only when the whole history is shorter than the window, so a truncated file publishes a wrong coverage fraction rather than "not yet measured". Append the Windows file to the VPS one and sort by the `utc` field; duplicate or out-of-order ticks are harmless, because `coverage_24h` sorts what it reads, but lost ticks are not. It is a rolling 24 hour window, so a genuine cutover gap is published honestly as an uncovered window and heals within a day.

  **What the merged file then makes true of the published figure, stated rather than hidden.** For roughly the 24 hours after the cutover, the file is two hosts' ticks in one stream, and nothing in it says which host wrote which line: `archive/run_cycle.py:129` sets every tick's `poller` field to `poll.user_agent(args.contact)`, which is a fixed string with no hostname in it (`archive/poll.py:74-75`), so both hosts write the same value. `coverage_24h` marks a minute covered when **any** tick is under ten minutes old (`web/build.py:201`), so across the overlap the published number is the fraction of minutes on which at least one of the two hosts was alive. It can only equal or beat either host's own uptime. Meanwhile the page says "Poller heartbeat coverage over the last 24 hours" (`web/pages.py:670-671`, and again at `:623-624`) and the ledger's `poller` field is the single fixed string at `web/build.py:241`; neither of them says two hosts. So the honest statement, and it belongs in that day's bulletin rather than in a code comment: **for the overlap window the coverage figure is the union of the home poller's and the VPS's observations, not one host's observed uptime, and it is one host's again from 24 hours after C11.** D18 accommodates this - it defines coverage over heartbeats and the ledger as "one record per poller per cycle" - but the published sentence does not, and an unexplained step up in coverage across the cutover is exactly the sort of number this project does not get to leave standing.
- **`heartbeat.json`**: do **not** copy. It is gitignored, regenerated on the first tick, and `archive/witness.py:111` reads it to decide whether the watcher is alive.
- **`outbox/`**: do **not** copy. Recreate empty; `pack()` mkdirs it anyway. The 9.28 GB `cycle_03329cf37459.tar` there is dead: that cycle shipped on 4 Sep, adopted its fingerprint on 6 Sep and had its local files deleted on 7 Sep. Delete it on Windows too, once you have confirmed its `ship.json` shows `shipped` with a `files_fingerprint`.
- **`partial/`**: disposable, one `--limit` test slice.
- **`cycle_*/files/`, 9 directories at about 9.26 GB each.** Do not copy them wholesale. The rule is: copy `files/` **only** for cycles that are either (a) not yet shipped with a matching fingerprint, or (b) still listed in `spool/score/run.json`'s `pending`. Everything else's raw bytes are already in Deep Archive, HEAD-verified, and the local copy is about to be deleted by retention anyway. Enumerate both sets before you copy; at 4.2 MB/s from the home uplink each 9.26 GB cycle is about 37 minutes.

Nothing goes missing if you copy `files/` while the home poller is running: those directories are for **completed** cycles, and a completed cycle is never rewritten.

### The order

Run every step with the previous one verified. Home keeps polling throughout steps C1 through C10.

The pattern from C6 onward is the same three moves every time, and the draft got it wrong by
omitting the middle one: **stop the Windows unit, re-sync that component's own files, start the VPS
unit.** A component's records are only final once the Windows writer for them has stopped.

**C0. Day-one measurement on the real host.** Provision the host to the section 2 spec, clone, make
a venv, and before installing anything else run the probe's `probe.sh` and one sustained
`archive/poll.py` pull against a scratch spool. Record both in
`probes/p8_vps_bootstrap/README.md` under a second dated heading. If a kill line from section 1
trips, stop here: the region or the shape of the plan changes and nothing on Windows has been
touched.

**C1. Build the real host.** `apt install python3.12-venv git bash ca-certificates fonts-dejavu-core chromium-browser`, create the `ephemera` user and `/srv/ephemera/spool`, `pip install -r requirements.txt` plus the pinned `opentimestamps-client`, write `personal.env` (heredoc, history suppressed, five names) and `/etc/ephemera/ephemera.env`, put the AWS profile at `/etc/ephemera/aws-config` mode 0600 and the deploy key under `/etc/ephemera/ssh/`, install the units disabled. Land the code edits from section 3 on `main` first, so the clone has them. Home untouched.

**C2. Gate: `make test` green on the VPS**, with a real browser present so the browser tests do not skip. This is also where `infra/guard_cf.sh` gets exercised on Linux, by `infra/tests/test_guard.py`. Then `python3 infra/guard.py` prints the personal account and profile, and a deliberately wrong account id in a sandbox copy refuses. Then `archive/poll.py --limit 5` against a scratch spool: five files, a partial record under `partial/`, no root, exit 3 (D13). This is the first time the code has ever been run on Linux, so treat a failure here as expected rather than surprising.

**C3. Start `ephemera-watcher.service`. Both pollers now running.** Zero risk of a gap; this is the only step that adds a poller before removing one. Note the UTC time you start it: C4 needs it.

**C4. Gate: one full cycle pulled by both, and two fields compared, not one.** Wait for the manifest to roll, then for that `cycle_<sha12>` compare:

- **`root.txt`, which must be identical.** P8 already observed exactly this across two continents on one manifest, so a difference here is a fault in this host, not a surprise about the feed. Different roots, or no root on the VPS, and you stop before touching anything on Windows.
- **`cycle.json`'s `first_seen_utc`, which may legitimately differ and whose difference the root cannot show.** The root commits file digests only. `archive/poll.py:295` sets `first_seen` from the local prior record or from this run's start time, so the first cycle the VPS pulls carries the VPS's C3 start time, not the time Windows first saw that manifest. Live `first_seen` values cluster at about 04:1x, 12:2x and 20:3x UTC, so a C3 start anywhere in the 00:00 to 04:16 UTC window puts the same cycle on a **different UTC date** on the two hosts.

Two things break on that skew and neither is visible in a root comparison. `archive/witness.py:225-232` buckets cycles into daily roots by `first_seen_utc[:10]`, and `:237` never rebuilds a day that already has `root.txt`, so one cycle becomes a leaf of Windows' already-stamped `daily/<D>` and again of the VPS's later `daily/<D+1>`. And `web/build.py:208` counts any gap over `CADENCE_HOLD_H = 9.0` (`web/build.py:36`) as a published cadence hold against an 8 h cadence, so an 8 h shift in one `first_seen` can fabricate a hold that did not happen or hide one that did.

**When they differ, take the earlier value - the Windows one - into the VPS's `cycle.json` before C6 starts the VPS witness.** The earlier value is the true first-seen and is what Windows has already bucketed and published, and editing it invalidates nothing: cycle identity is the manifest SHA-256 (D10) and the Merkle root is over file digests (D09), so neither changes. Do it before the witness runs, because a daily root is built once. Record both values and the edit.

Also record the VPS wall time against P1's 6 hour kill line and against the home machine's 45 to 116 minutes.

**C5. Copy the historical records, per file.** About 1.06 GB plus the selected `files/`, by the rules in "Moving the 44 cycles" above. Per file and never per directory: `tar -df` first to see what would have been overwritten, then `tar --skip-old-files -xvf` with stderr captured, which is the list of what the VPS already had.

That skip rule is right for every file except one. **Before the copy, compare the two `cycle.json` files for every cycle both hosts hold**, by "Which host's `cycle.json` wins" above. Wherever Windows' record is the better one - complete against the VPS's gapped, or more `files_recorded` where both gapped - put its `cycle.json`, its `root.txt` and the `files/*.gz` the VPS lacks in **deliberately and overwriting**, after the skip-extract has run. Record every cycle where the two records differed and which one you kept; that list is the cross-poller evidence D18 asks to be published rather than suppressed. `etag_cache.json` follows whichever `files/` you keep. `daily/` is **not** copied here, it is copied at C6. `heartbeats.jsonl` is concatenated, not copied.

**Timing rule for C5 through C9: run them inside one UTC day, and do not start C5 within two hours of 00:00 UTC.** Every step from here to C9 has a Windows writer running behind it, and a UTC midnight crossing the C5-to-C6 gap is the specific case that has Windows build, stamp and publish a `daily/<D>` the VPS never receives and later rebuilds from its own cycle set.

**C6. Witness: stop, re-sync, start.** In that order.

1. Stop the Windows Witness task; confirm no `witness.py` process remains.
2. Re-sync per file, from Windows into the VPS spool and **including into the cycle directories the VPS pulled itself**: every `root.txt.ots`, `root.txt.ots.bak`, any `root.txt.ots.stale-*`, and every `witness.json`. Then copy `daily/` in full, complete days only. Nothing on Windows writes these any more, so this copy is final and no midnight can land behind it.
3. Spot-check one overlap cycle on the VPS: `witness.json` carries `stamped_utc` and an `attested.block_height`, `root.txt.ots` is byte-identical to the Windows copy, and the Wayback samples read `verified`.
4. Start `ephemera-witness.service`. Within one 300 s interval it picks up the current cycle. **There is no stamping backlog waiting for it**, and the draft's claim that one cycle sits unstamped because Docker Desktop is broken is stale: Docker was repaired on 9 Sep and the spool has caught up. Measured 13 Sep across `Z:\ephemera\spool`: all 44 cycle directories hold a `root.txt`, all 44 hold a `root.txt.ots` beside it, all 44 `witness.json` records carry an `attested.block_height`, and there is no `root.txt.ots.stale-*` file anywhere in the spool. The 14 `daily/` days are all stamped and attested too, the newest at Bitcoin block 966741 for 2026-09-12. So the gate for this step is that the number stays zero: after the first VPS pass, roots without proofs is still 0 and witness records without a block height is still 0.

The draft said to time the stop "just after a cycle's captures have completed rather than mid-window". **Do not.** Waiting can push the C5-to-C6 gap out by most of an 8 h capture window, which is how a midnight lands inside it. Stopping mid-window is safe here: step 2 hands the VPS the same `witness.json`, with the same pending samples, and it makes the remaining captures itself.

**C7. Catalogue: stop, re-sync, start.** Never overlapping, because two clients on one Space-Track account from two IPs is still unverified (section 1, open question 2). Stop the Windows Catalogue task, re-sync `gp/` per file with the directory names byte-identical, then start `ephemera-catalogue.timer` and confirm `systemctl list-timers ephemera-catalogue.timer` shows a real `NEXT` rather than `n/a` (5.3). With `OnBootSec=5min` in the block the first pass runs at once, so verify the new `gp/` snapshot within minutes instead of waiting two hours, and verify it is **not** a duplicate of the newest copied one.

**C8. Score: stop, re-sync, start.** Stop the Windows Score task, re-sync `spool/score` per file (binary-safe), then start `ephemera-score.service`. Verify one new report plus a pack over 4 MB.

**C9. Shipper: stop, re-sync `ship.json`, verify against S3, then start.** This is the step the draft got most wrong. Follow it literally.

1. Stop the Windows Shipper task; confirm no `ship.py` process remains. Nothing else in the system writes `ship.json`.
2. Re-sync every cycle's `ship.json` from Windows into the VPS spool, per file, **overwriting** what is there. The VPS shipper has never run, so it has written none of them.
3. **Gate, before starting anything, and drive it from what S3 holds rather than from what `ship.json` claims.** For every `cycle_*` on the VPS whose `cycle.json` status is `complete` or `gaps`, list the tar's versions first:

   `aws s3api list-object-versions --bucket ephemera-space-raw --prefix cycles/<sha12>/files.tar --query 'Versions[].[VersionId,LastModified]'`

   and then take the case that puts you in. The draft collapsed the first two cases into one and got the first backwards.

   - **No versions at all.** S3 holds no tar for this cycle, so Windows never shipped it, and the VPS PUTting it is the **correct** behaviour rather than the failure. The draft's gate demanded `ship.json` with `shipped` non-null for every complete or gapped cycle and named "the VPS will PUT" as the consequence, which condemns the one upload that has to happen and is unsatisfiable for a cycle only the VPS ever pulled. What to check here instead is that the cycle can actually be packed: `files/` still holds every name its record lists, or `pack()` raises `CorruptCycle` at `archive/ship.py:107` and the pass returns 1 every thirty minutes forever. And if `ship.json` nonetheless claims `shipped` for a key that does not exist, stop: the record is lying, and understanding why comes before anything writes to S3.
   - **Exactly one version.** The normal case for the cycles already shipped from Windows. Require all three: `ship.json` exists with `shipped` non-null; `shipped.files_fingerprint` equals `files_fingerprint(cycle.json)` (`archive/ship.py:83-92`); and `aws s3api head-object --bucket ephemera-space-raw --key cycles/<sha12>/files.tar` returns a `Metadata.sha256` equal to `ship.json`'s `shipped.sha256` (`archive/ship.py:205` wrote the object metadata, `:213` wrote the record). If any of the three fails, `needs_upload()` returns a reason (`archive/ship.py:151-171`) and the VPS **will** PUT a second, byte-different object over a tar that is already there. That is the double ship, and the fix is to correct `ship.json` before the timer starts, never after.
   - **Two or more versions.** A second upload has already happened, and the object metadata says whether it was a legitimate one. Every version carries `Metadata.merkle_root` as well as `Metadata.sha256` (`archive/ship.py:205`); read both with `head-object --version-id`. Different `merkle_root` values, or an empty one on the older version, means the cycle was gapped and then healed and re-shipped on purpose, which is behaviour the shipper is built for (`archive/ship.py:170-171` and the module docstring at `:27-31`). The **same** `merkle_root` with a **different** `sha256` means two hosts tarred the same content, which is the double ship. Neither can be undone: Object Lock is in governance mode.

   Only the S3 side is evidence. "Confirm every cycle carries its copied `ship.json`" is satisfied by a stale `ship.json` and says nothing whatever about a cycle only the VPS ever pulled.
4. Start `ephemera-ship.timer`, and confirm it has a next elapse: `systemctl list-timers ephemera-ship.timer` showing a real `NEXT`, not `n/a` (5.3). After its first pass, re-run the version listing **across the whole `cycles/` prefix** and diff it against the listing from step 3. What you are looking for is a key that **gained** a version during that pass. On a `cycles/<sha12>/files.tar` key that is a double ship unless the `Metadata.merkle_root` test above says it was a heal. On the five record keys it is routine, and the next paragraph says why.

**One version per key is the rule for `files.tar` and for nothing else. It is false by design for the records.** D15's 2026-09-02 amendment puts `cycle.json`, `root.txt`, `root.txt.ots`, `witness.json` and `MANIFEST.txt` beside the tar in STANDARD class, "re-synced whenever their bytes change", and `archive/ship.py:226-235` is that sentence in code: every pass, for each of the five (`RECORD_FILES`, `archive/ship.py:61`), it hashes the local file and PUTs it again whenever the digest differs from `state["records"][name]`. On a versioned bucket each of those PUTs is another version, and it is meant to be. Measured on the live spool, 13 Sep: `witness.json` changes in **2 to 4 distinct 30-minute shipper windows per cycle** (median 3, from 3 to 14 recorded witness events per cycle), so its key carries several versions for every cycle; and all 44 cycles hold a `root.txt.ots.bak`, the backup `ots upgrade` leaves when it rewrites the proof in place after the Bitcoin attestation, with the current proof two to four times the size of its backup, so `root.txt.ots` has at least two versions for every cycle as well. **A second version of a record key means the record changed and was re-synced, which is the system working. A second version of `cycles/<sha12>/files.tar` means the archived bytes for that cycle were replaced, which is either a heal the shipper did deliberately or the one thing this whole step exists to prevent.**

Why this is worth four steps: the two hosts' tars cannot be byte-identical. The record members are added with `tarfile.add` (`archive/ship.py:134`), which copies uid, gid, uname, gname and mode from the filesystem, and every `files/*.gz` differs as well because `archive/poll.py:204` writes the gzip with no `mtime=`, stamping the local clock into each gzip header. Two shippers therefore write two different objects under one versioned key, each host's `ship.json` claiming its own SHA-256, and a restore verified against one fails against the other. The runbook calls that the single most damaging thing that can go wrong in the cutover, and the draft's own copy rule made it near-certain.

**C10. Ledger: stop the Windows task, then start `ephemera-ledger.timer`.** The clone made at C1 is behind `origin/main` by every "ledger build" the Windows publisher pushed since, and the draft had no step that refreshed it. It no longer needs one: `sync_with_published()` fetches and fast-forwards before every build (`web/publish.py:54-110`, called at `:131`). Stop Windows first anyway, because two publishers on one branch is the diverged case and it is refused rather than reconciled.

The shrink guard is a real safety net again. Its baseline is the larger of what `origin/main` publishes and what this clone has committed (`web/publish.py:159-166`), so a build holding fewer cycles than the live site is refused with both counts named. In the draft that count came from the stale local HEAD, so the guard measured the build against a published count it did not have and would have passed regardless. Do not reach for `--allow-shrink` to get past it.

Verify, in order: `systemctl list-timers ephemera-ledger.timer` showing a real `NEXT` and not `n/a` (5.3), then the fast-forward line in the journal, the commit, the push over the deploy key, the `deploy-site` workflow going green, and `ephemera.space` serving the new build with at least the cycle count it served before. Run this within one build interval of C4, or the published page goes stale while the VPS accumulates cycles the Windows build cannot see.

**C11. Stop the Windows Watcher.** The archive is now entirely on the VPS.

**C12. Leave the Windows machine powered, all six tasks disabled, spool untouched, for seven days.**

---

## 7. Verification and rollback

### Per-step gates

Already stated inline: C0 (the rate on the host actually bought), C2 (test suite, guard, limit slice), C4 (matching roots **and** compared `first_seen_utc`), C6 (an overlap cycle's stamp and captures intact after the re-sync), C7 and C8 (one live artefact each), C9 (one S3 object version per `files.tar` key, the recorded sha256 matching that object's metadata, and a cycle S3 has never seen recognised as a first upload rather than a fault, all before the VPS shipper starts), C10 (the fast-forward, the commit, the push, the workflow, the live page). Do not proceed past a red gate.

### Before the home machine is switched off

Everything here is a command that either passes or does not. "Looks fine" is not a gate.

**The strongest single check.** `python3 archive/verify.py <a VPS-pulled cycle> --wayback`, exit 0. It deliberately re-implements the D09 Merkle construction from the documented paragraph rather than importing the poller's function, so a passing root is agreement between two independent codings. It checks the cycle's identity against `MANIFEST.txt`, the names against the manifest order, every stored gzip against the record, the root, `root.txt` being exactly 65 bytes (D12), the OpenTimestamps proof being bound to **this** root, and the Wayback copies being re-fetchable and re-hashable. If this passes on a cycle the VPS pulled, stamped, captured and shipped by itself, the migration has genuinely worked.

**Then, in order:**

1. `systemctl is-active` on the three services, and `systemctl list-timers --all` on the three timers with **`NEXT` and `LEFT` reading real values on every one of them and never `n/a`**. `n/a` there means the timer has no next elapse and will never fire, which is precisely what a monotonic `OnUnitActiveSec=` with no `OnBootSec=` gives you (5.3): the unit reads `active`, `systemctl --failed` stays empty, and the catalogue and the ledger simply stop. `systemctl --failed` empty as well. (This gate is why the ship unit says `SuccessExitStatus=SIGTERM` and not `143`; see 5.3, which also says what that directive does not cover.)
2. Watcher: `heartbeat.json` age under 10 minutes, `heartbeats.jsonl` growing, at least two complete VPS-pulled cycles with roots, wall time comfortably inside 6 hours.
3. `journalctl -u ephemera-watcher --since -24h` non-empty. If it is empty, you set `StandardError=null` or passed `--log-file`, and you have been running blind.
4. Witness: a VPS-created `root.txt.ots`, `ots verify` passing, and within an hour or two a `block_height` in `witness.json`. Also confirm `witness.json` carries `stamped_utc`, which is what edit 3.4 protects. And confirm no overlap cycle was re-stamped: for one cycle both hosts held, `stamped_utc` still reads its original date and not the migration date.
5. Shipper: one VPS-shipped cycle, and **exactly one object version for every `cycles/<sha12>/files.tar` key**, not only for that one cycle. `aws s3api list-object-versions --bucket ephemera-space-raw --prefix cycles/`, count per key, and then look only at the `files.tar` keys: a second version there is the double ship C9 exists to prevent, unless the two versions' `Metadata.merkle_root` differ, which is a heal the shipper did on purpose (C9 step 3). **Do not apply the one-version rule to the other five keys under a cycle prefix.** `cycle.json`, `root.txt`, `root.txt.ots`, `witness.json` and `MANIFEST.txt` are re-PUT whenever their bytes change (`archive/ship.py:226-235`, D15's 2026-09-02 amendment), and they do change: measured 13 Sep, `witness.json` changes in 2 to 4 separate 30-minute shipper windows per cycle, and every one of the 44 cycles has had its `root.txt.ots` rewritten once by `ots upgrade`. Several versions on a record key is the system working; what is worth checking there is that the newest version's `Metadata.sha256` matches the local file, which is the digest `ship.json`'s `records` map already holds. The restore drill remains outstanding from PLAN item 8 and this is the moment to do it: a Bulk restore in-region, verified against the recorded SHA-256 per VERIFY.md. It takes 12 to 48 hours, so start it at C9 and let it run.
6. Score: one VPS report plus a pack over 4 MB, and `run.json` showing no unexpected `skipped_no_files`.
7. Ledger: `web/dist/ledger.json` on the live site showing at least the cycle count it showed before the cutover, `coverage_24h` recovered after 24 hours, and every report's `pack` field reading a bare `globe_<sha12>.json` with no drive letter, no backslash and no leading slash. That last one is the 3.9 fix reaching the public artefact; until the first VPS publish the committed file still carries the old `Z:\` strings.
8. Disk: `df -h` for the `ephemera` user showing free space above 25 GB with three days of retention held. Remember `f_bavail` excludes the ext4 reserve.
9. Environment, **for all six units and not just the watcher**: none of `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE` is set in any of them. `systemctl show -p Environment <unit>` is not the check: it reports `Environment=` directives only, so it cannot see a variable arriving through an `EnvironmentFile=` or through the manager's `DefaultEnvironment`. Measured on a transient unit whose `EnvironmentFile=` set `HTTPS_PROXY`, `systemctl show -p Environment` printed an empty value while the process's own environment held it.

   **The two kinds of unit need two different commands, and the draft gave only one.** For the three long-running services, read the running process: `tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value ephemera-watcher.service)/environ`. That command cannot work for the other three. `ephemera-ship`, `ephemera-catalogue` and `ephemera-ledger` are `Type=oneshot` units driven by timers, so between passes they have no process at all and `MainPID` is `0`; the path becomes `/proc/0/environ` and you get a "No such file" that reads like a system fault rather than an answer. Measured on an inactive transient oneshot: `MainPID=0`, `ActiveState=inactive`.

   For a oneshot, make the unit answer on its next pass. Install a dumper and a drop-in, run the unit once by hand, read the file, then take the drop-in out again:

   ```
   # /usr/local/sbin/ephemera-dumpenv, mode 0755
   #!/bin/sh
   tr '\0' '\n' < /proc/self/environ > "/run/ephemera-env-$1.txt"

   # /etc/systemd/system/ephemera-catalogue.service.d/env-audit.conf
   [Service]
   ExecStartPre=/usr/local/sbin/ephemera-dumpenv catalogue
   ```

   then `systemctl daemon-reload`, `systemctl start ephemera-catalogue.service`, `grep -E 'PROXY|CA_BUNDLE' /run/ephemera-env-catalogue.txt` expecting no output, then remove the drop-in and `daemon-reload` again. `ExecStartPre=` runs under the same unit environment as `ExecStart=`, which is what makes this an answer about the real unit rather than about a shell you happened to run: measured on a transient oneshot whose `EnvironmentFile=` set `HTTPS_PROXY` and `FOO`, the `ExecStartPre` process's `/proc/self/environ` held both, identically to the `ExecStart` process's. Note that starting one of these by hand runs exactly the pass its timer runs, so for `ephemera-ledger` that is a real commit and push and for `ephemera-ship` a real upload; do it when you are content for that pass to happen. `ephemera-catalogue` is the one that matters most: `archive/gp_pull.py:55` is the only session in the archive that transmits a password.
10. Reboot the VPS once, deliberately, and confirm all six come back and the watcher resumes the in-flight cycle from its ETag cache rather than re-pulling 9 GB.

### Rollback

Up to and including C10, the rollback is two minutes: stop the VPS unit, re-enable the Windows scheduled task. It works because every component except the poller is single-writer and the Windows spool is untouched until C11.

After C11 the rollback is the same command, and the Windows spool then has a hole for whatever the VPS pulled in between. The VPS spool holds those cycles, so the union is complete and nothing is lost; you would copy them back the way you copied forward.

**The one exception, and the draft's advice on it was useless.** The irreversible action is an S3 write: a cycle shipped from the VPS under a key Windows would also ship is a second object version with a different tar SHA-256 and a contradicting `ship.json`. The draft said to "check `systemctl --failed` on the VPS before re-enabling the Windows Shipper", which tells you nothing about which cycles the VPS already uploaded. Do this instead: before re-enabling the Windows Shipper for any reason, list the object versions under `cycles/` (check 5 above) and look at the `files.tar` keys only. For every `cycles/<sha12>/files.tar` the VPS may have touched, confirm it still holds exactly one version and that version's `Metadata.sha256` matches the `shipped.sha256` in the `ship.json` on the host you are about to run. The five record keys under the same prefix will each hold several versions, and that is not a finding: they are re-PUT whenever their bytes change (`archive/ship.py:226-235`), so counting versions across the whole prefix flags every healthy cycle and tells you nothing about the one thing that matters. Prevent it; do not plan to recover from it, because Object Lock in governance mode means the extra version stays.

Keep the Windows spool intact for seven days after C11. It is both the cold rollback and the source for any `files/` you decide you needed after all.

---

## 8. What stays on the owner's machine

**Nothing operational.** That is the goal and, now that P8 has passed, it is achievable. The six scheduled tasks are deleted, not disabled-and-forgotten. `pythonw.exe` is not needed. Docker is not needed: the OTS client runs natively on Linux (P8 measured `ots stamp` at 1.5 s), which removes the dependency that broke on the owner's machine at the start of September. It is no longer broken and there is no longer an unstamped cycle: Docker was repaired on 9 Sep, and measured 13 Sep all 44 cycle roots and all 14 daily roots in the spool carry both a proof and a Bitcoin block height. The reason to drop Docker is not a backlog, it is that a witness whose runner is a desktop application stops when the desktop does.

**What stays by choice:**

- The development checkout. Editing, `make test`, `codex review --base origin/main` before pushing. That is where the owner works and it should not move.
- The Docker `stamp`, `upgrade` and `verify` targets in `Makefile:51,55,59`. They are Windows-only conveniences for hand-checking a proof and they cost nothing to leave.
- The spool as a cold second copy for the retention week, then archived or deleted.

**What the owner still holds personally, and should be able to revoke independently.** The VPS gets a copy of the AWS credentials, the Space-Track credentials and a GitHub write key. Where the provider allows it, make each one VPS-specific: a distinct IAM user with a policy scoped to `PutObject` and `HeadObject` on `ephemera-space-raw` (note D14 says "put-only credentials on the poller", which would break `archive/ship.py:206-212`'s HEAD verification, so the deployed policy needs checking before the VPS gets a key, and it is not in the repository), and a repository deploy key rather than an account PAT. The Space-Track account cannot be split, which is the one credential the two machines would genuinely share, and is the reason the catalogue cutover is a single atomic switch rather than an overlap.

**What deliberately never reaches the VPS:** the Cloudflare **token**. The deploy stays on GitHub Actions, which is already proven on `ubuntu-latest`. The VPS pushes; the runner deploys. State the benefit exactly: one less secret at rest on the host that holds everything else. It is not isolation from Cloudflare, because the write-scoped deploy key can push the paths that trigger the deploy workflow and so can cause chosen code to run with the token in scope (section 4). A host holding the token can act on Cloudflare alone and silently; a host holding the push credential has to go through a public commit on `main` and a workflow run that is visible in the Actions log.

---

## 9. Where the surveys and the first draft were wrong

Stated because the runbook is built on them and you should know which parts were re-checked.

- **The AWS CLI is not required for the test gate.** One survey implied `infra/guard.sh` needs AWS CLI v2 installed for `make test` to be meaningful. `infra/tests/test_guard.py:30-50` stages a copy of `infra/` with a **fake `aws`** script on PATH, and the module skips only when bash is absent (`:21`). The CLI is needed only to hand-run `infra/whoami.sh`.
- **The `score/run.py` comment is not simply wrong, it is incomplete.** The survey read the comment at lines 90 to 95 as a false claim. Traced: the claim holds for `build_pack` raising, which does leave the cycle pending. What it does not cover, and what the survey correctly identified as the defect, is the process dying between the report write at `score/run.py:97` and the pack write at `:105`. The fix is the same either way; the characterisation matters because the next person reading that comment should know which half is true.
- **P4 does not price the VPS at all.** One brief asked me to note that P4's Hetzner prices are unverified. They are (`probes/p4_cost/README.md:68`), but the more important fact is `probes/p4_cost/README.md:48`, which excludes "the VPS itself" from the entire cost table. There is no verified compute price anywhere in this repository, from any provider.
- **Cycle counts go stale in days.** The briefing said 32 cycles with 9 holding raw files; it was 33 with 10 on 9 Sep and is 44 with 9 on 13 Sep. That is why C10's gate now reads "at least the count the live site already shows" rather than a fixed number, and why the shrink guard reads the published ledger rather than a figure in this document.
- **Line drift, and the draft's own correction of it was wrong.** The 9 Sep draft wrote that `web/tests/test_build.py` CHROME "is at 21 to 24, not 22 to 25", and put that in the one section whose purpose is to certify its citations. Read again: line 21 is `REPO = Path(__file__).resolve().parents[2]`, and the `CHROME` assignment opens on 22 and closes on 25. The survey was right and the correction was wrong. Section 3.10 now cites 22 to 25. Worth stating rather than quietly deleting, because a reader who trusts a certification does not re-check the rest, and 3.10 is an edit someone will apply to those exact lines.
- **Citations were re-read on 13 Sep.** The three code fixes moved lines in `web/build.py` and rewrote `web/publish.py`, so several 9 Sep citations no longer resolved. Every file:line in sections 0 through 8 was re-read in this checkout on 13 Sep 2026. The evidence lines in the findings record below are as written on 9 Sep and are not re-cited; where they differ from a section above, the section above is current.
- **What is still unverified.** No AWS call was made, so the D15 seven-day multipart-abort lifecycle rule on `ephemera-space-raw` and the IAM policy behind the profile are both unchecked; D14's "put-only credentials on the poller" would break `archive/ship.py`'s HEAD verification, and the deployed policy is not in this repository. The test suite has never been run on Linux. Nothing in this runbook has been run on a real Ubuntu VPS: the guard work was exercised under git-bash with a synthetic PATH holding `python3` and no `python`, and the publisher's fetch and fast-forward were exercised only against bare repositories on local disk, never over a network and never under systemd. The SIGTERM handler at `archive/poll.py:233` has never been executed by anything, on any platform, which makes it the first thing to test on the VPS. The 31 Aug "identical blake3 hashes cross-OS" claim in PLAN.md was not reproduced; moving the build to Linux removes the question rather than answering it. And whether anything outside this repository reads the ledger's `pack` field cannot be checked at all under the clean-room rule.

---

## Findings record: all nineteen, and where each was handled

Three adversarial passes on the 9 Sep draft (cutover, secrets, portability) found nineteen defects:
**3 blockers, 8 serious, 8 minor.** All nineteen are folded into the text above or fixed in code.
This section exists so a reader can audit that, one by one. Each entry gives what was wrong, where
it is now handled, and the evidence that established it.

The evidence lines are as recorded on 9 Sep 2026 and are **not** re-cited; three code fixes have
since moved lines in `web/build.py`, `web/publish.py` and `infra/guard_cf.sh`. Where an evidence
line disagrees with a section above, the section above is current.

### Lens 1: cutover sequence (sections 6 and 7)

**F1. BLOCKER. C5's "ignore-existing at the cycle-directory level", held against a Windows shipper running until C9, guarantees a double ship.**
Every cycle the VPS pulled itself from C3 onward was skipped wholesale, so its `ship.json` never arrived; `needs_upload()` then returns "not yet shipped" and the VPS PUTs a second, byte-different object version to a key S3 already holds, with a contradicting recorded SHA-256. The C9 gate as drafted was unsatisfiable for VPS-only cycles and passed for copied-then-shipped ones while the double ship happened.
*Addressed:* section 6, "Moving the 44 cycles" - the copy is now per file and the bulk copy is explicitly not the authority - and C9, which stops the Windows shipper, re-syncs `ship.json`, and gates on the S3 side before the VPS shipper starts. Section 7 check 5 repeats the check across the whole `cycles/` prefix, and the rollback paragraph replaces the useless `systemctl --failed` advice.
*Re-audited 13 Sep, and the first correction was itself two-thirds right.* The gate as first written conflated a second byte-different upload of something already in S3 with the first upload of something that was never there, and named "the VPS will PUT" as the failure for both, which condemns the one upload that has to happen and is unsatisfiable for a cycle only the VPS ever pulled. And it applied "exactly one object version" to every key under `cycles/`, which is false by design for the five record objects: D15's 2026-09-02 amendment has them re-synced whenever their bytes change and `archive/ship.py:226-235` re-PUTs on any digest difference, measured at 2 to 4 changed 30-minute windows per cycle for `witness.json` and at least one `ots upgrade` rewrite of `root.txt.ots` for all 44 cycles. C9 step 3 now splits on what `list-object-versions` returns, the one-version rule is scoped to `files.tar`, and `Metadata.merkle_root` is what separates a deliberate re-ship after a heal from a double ship. Section 7 check 5 and the rollback paragraph were corrected the same way.
*Evidence:* archive/ship.py:151-154 (needs_upload -> 'not yet shipped'); archive/ship.py:131-134 and 203-205 (tar.add metadata, PUT to cycles/<sha12>/files.tar); archive/poll.py:204 (gzip.open with no mtime, host clock in every gzip header); measured on Z:\ephemera\spool, finished_utc to shipped.uploaded_utc 45 to 70 min across all 32 shipped cycles, and cycle_1b3b36972d57 finished 04:59:07Z, uploaded 05:44:52Z.

**F2. BLOCKER. The same rule strands `root.txt.ots` and `witness.json`, so the VPS re-stamps attested roots and records Wayback losses that did not happen.**
With no proof file the witness stamps again and the committed timestamp becomes the migration date; with no `witness.json` a superseded cycle is marked as never captured, and that verdict is sticky forever. The draft warned about exactly this two paragraphs before issuing the rule that caused it.
*Addressed:* the same per-file rule, plus C6 step 2, which re-syncs `root.txt.ots`, `root.txt.ots.bak`, the stale variants and `witness.json` **after** the Windows witness is stopped and **into** the cycle directories the VPS pulled itself, and C6 step 3's spot-check. Section 7 check 4 now also asserts that no overlap cycle was re-stamped.
*Evidence:* archive/witness.py:191-192 (stamp when no proof exists); archive/witness.py:282 and 292-296 (sticky wayback.skipped for a superseded cycle); Z:\ephemera\spool\cycle_1b3b36972d57\witness.json (stamped_utc 2026-09-08T05:02:06Z, attested block 966019, 10 samples, manifest verified).

**F3. SERIOUS. C10 wedges the ledger: nothing refreshed the C1 clone, `publish.py` never fetched, and the shrink guard read a stale local HEAD.**
The first VPS push is rejected non-fast-forward, the unit commits onto a divergent branch every 4 hours forever, and section 4 pre-diagnosed that as a deploy-key problem so the operator debugs the wrong thing.
*Addressed:* **fixed in code.** `sync_with_published()` (`web/publish.py:54-110`, called at `:131`) fetches, fast-forwards a branch that is behind, and refuses when git cannot operate on the tree, when the fetch fails, or when the branch is both ahead and behind; the shrink baseline is now the larger of the published and the committed count (`:159-166`). Described in 5.6 and C10; section 4's push paragraph now separates a credential failure from a rejected push.
*Evidence:* web/publish.py:23-24 and 42-99 contained no fetch/pull/rebase; web/publish.py:29-33 (committed_cycle_count read the local HEAD); web/publish.py:71-75 (shrink guard used that count); git log on main: b1ea65b, 9e684da, f932cc8, 6fcf2b0, e023d2b all 'ledger build'.

**F4. SERIOUS. C4's "identical roots is the go signal" is not sufficient: the root commits file hashes, not `first_seen_utc`.**
The first cycle the VPS pulls carries the VPS's C3 start time, so the same cycle can sit on a different UTC date on the two hosts, which double-buckets it in the daily roots and can fabricate or hide a published cadence hold.
*Addressed:* C4 now gates on both fields, states the 18-percent-of-start-times window that produces the skew, names both consequences, and says to write the earlier Windows value into the VPS's `cycle.json` before C6 starts the witness, with the reason it is safe (identity is the manifest sha, the root is over file digests).
*Evidence:* archive/poll.py:294-295 (first_seen = prior or this run's started); archive/witness.py:229-234, 237 (daily bucketing by first_seen date, build-once); web/build.py:36 and 204 (CADENCE_HOLD_H = 9.0); measured first_seen values on Z:\ephemera\spool cluster at 04:1x, 12:2x, 20:3x UTC.

**F5. SERIOUS. A UTC midnight in the C5-to-C6 gap makes Windows build and publish a daily root the VPS never receives and later rebuilds differently.**
The witness builds a daily root for every UTC day strictly before today on every pass, and skips only a day whose `root.txt` already exists, so the rebuild is silent falsification arrived at through the runbook's own step order.
*Addressed:* `daily/` is removed from C5 and transferred at C6 **after** the Windows witness has stopped; C5 carries a timing rule (C5 to C9 inside one UTC day, do not start within two hours of 00:00 UTC); and the draft's advice to wait for the end of a capture window before stopping the witness is struck, with the reason.
*Evidence:* archive/witness.py:212-233 (daily roots built for every day before today, every pass); archive/witness.py:237 (skip only if root.txt already exists); draft C6 permitted waiting for the end of a capture window.

**F6. MINOR. `heartbeats.jsonl` was to be copied, but the VPS watcher has been appending to it since C3.**
Copying destroys every VPS tick since C3; skipping loses all the Windows history. Either way `coverage_24h` publishes a wrong fraction rather than "not yet measured".
*Addressed:* the bullet now says concatenate and sort by `utc`, explains why duplicates are harmless and lost ticks are not, and keeps the honest statement that a real gap publishes as an uncovered window.
*Re-audited 13 Sep:* concatenating is still the right arithmetic, but the merged file attributes a second host's observations to the VPS and nothing in it says otherwise - `archive/run_cycle.py:129` writes a `poller` field with no hostname in it (`archive/poll.py:74-75`). The bullet now also states what the site then publishes: for the overlap window the D18 coverage figure is the union of the two hosts' observations rather than one host's observed uptime, and it becomes one host's again 24 hours after C11. Said in the bulletin, not hidden.
*Evidence:* archive/run_cycle.py:138-140 (append to heartbeats.jsonl every tick); web/build.py:170-178 and 181-199 (single-file read, coverage_24h); draft C3 precedes C5.

**F7. MINOR. The heredoc instruction leaves the Space-Track password in shell history (cutover lens).**
*Addressed:* section 4, "Suppress the shell history while you type it".
*Evidence:* draft section 4 gave no `set +o history`, no `HISTCONTROL` note and no instruction to clear history, in a paragraph otherwise careful about 0600 and gitignore.

### Lens 2: secrets and guards (section 4, and the guards themselves)

**F8. BLOCKER. The offered `scp` of `personal.env` puts the Cloudflare token on the VPS.**
The live file holds eight names, not the five in the runbook's own table, including `CLOUDFLARE_API_TOKEN`. `scp` copies all eight, onto the one host that already holds the AWS credential, the Space-Track credential and a GitHub write key, destroying the property the runbook advertises most.
*Addressed:* the `scp` sentence is struck in section 4 and replaced with "five names and nothing else", with the measured eight-name fact stated.
*Evidence:* `grep -oE '^[A-Z_]+=' infra/personal.env` prints EPHEMERA_AWS_PROFILE, EPHEMERA_AWS_ACCOUNT_IDS, EPHEMERA_AWS_FORBIDDEN_IDS, SPACETRACK_USER, SPACETRACK_PASS, CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, EPHEMERA_CF_ACCOUNT_IDS (names only, no values read); loaded wholesale by infra/guard.py:24-34, called from archive/ship.py:289.

**F9. SERIOUS. The draft creates `/opt/ephemera/.aws/config` and `/opt/ephemera/.ssh/id_ed25519` inside a public repository's working tree with no ignore rule.**
Measured: `infra/personal.env` was ignored; `.aws/config`, `.aws/credentials` and `.ssh/id_ed25519` were NOT IGNORED. Not a live leak, because the committer is pathspec-confined to `web/dist`, but the VPS is where a human runs git by hand.
*Addressed:* **fixed in code** - `.gitignore:26-29` now carries `/.aws/` and `/.ssh/`, with a test that asks git rather than reading the file (`infra/tests/test_guard.py:295`). Section 4 also moves both out of the checkout entirely, to `/etc/ephemera/aws-config` and `/etc/ephemera/ssh/`, and the units in 5.3 and 5.6 use those paths.
*Evidence:* `git check-ignore -v infra/personal.env .aws/config .aws/credentials .ssh/id_ed25519` matched only the first (.gitignore:23); pathspec confinement verified at web/publish.py:77,84-87.

**F10. SERIOUS. "The credentials themselves may live in that section or in the unit's environment" - the two are not equivalent.**
Measured with botocore 1.43.81: env keys win over a keyless profile section (resolution method `env`), so pinning the profile pins the name only; and a unit `Environment=` is readable by any local user through `systemctl show`, out of a 0644 unit file.
*Addressed:* section 4 now says the keys go only in the profile file at 0600, never in `Environment=` or an `EnvironmentFile=`, and states the measured result including the `ProfileNotFound` case the draft had left open.
*Evidence:* offline botocore resolution test, no AWS call: case A (section exists, env keys set) -> access_key AKIAENVFAKE, method "env"; case B (section absent, env keys set) -> ProfileNotFound. Guard behaviour at infra/guard.py:43,54,56-58.

**F11. SERIOUS. "No Cloudflare credential ever reaches the VPS" is true of the token at rest and false of the capability.**
A write-scoped deploy key can push the four paths that trigger the deploy workflow, including `infra/cf_site.py` and `infra/guard_cf.py`, and the workflow then runs that code with the Cloudflare token in the environment.
*Addressed:* section 4's "What that key can do, stated honestly" states it in those terms, keeps the deploy key as the right choice over a PAT, asks for a `main` ruleset blocking force-push and deletion, and marks path-restriction of deploy keys as unverified. The Cloudflare-deploy section restates the isolation claim in the narrower form that is actually true.
*Evidence:* .github/workflows/deploy-site.yml:13-16 (trigger paths include infra/cf_site.py, infra/guard_cf.py and the workflow file), :50-54 (secrets in env, `run: python infra/cf_site.py deploy`); guard call site at infra/cf_site.py:161,166,169; push at web/publish.py:94.

**F12. SERIOUS. Section 3.2's reasoning was wrong, and a guard test was green while the guard was inoperative.**
`guard_cf.sh` does run on the VPS, in the C2 gate. On a PATH with no `python` it printed `REFUSED - the token cannot see the ephemera.space zone ...` character for character what the refusal test asserts, while the zone binding had never been evaluated.
*Addressed:* **fixed in code** - `infra/guard_cf.sh:40-50` resolves `python3` first and refuses in its own words if there is no interpreter, and `:63-79` prints the owning account so the three refusals are distinct; the test stages a `python3` shim, asserts it ran, and asserts an id only the fake answer carries (`infra/tests/test_guard.py:241-279`). Section 3.2 records the correct reasoning and the two scripts that still carry a bare `python`.
*Evidence:* ran infra/guard_cf.sh in a sandbox with a fake curl and PATH=/tmp/cfg/bin:/usr/bin:/bin (no python): stderr "guard_cf.sh: line 44: python: command not found" then "guard_cf: REFUSED - the token cannot see the ephemera.space zone under the allowlisted account", exit 1, sentinel not created. Assertions at infra/tests/test_guard.py:156-161; harness at :122-140.

**F13. MINOR. "Neither guard has an override flag ... and `infra/tests/test_guard.py` greps for one" was inaccurate twice.**
The grep covered the two shell guards only, not the Python guards the VPS actually runs; and both Python guards take injection arguments that replace the check.
*Addressed:* **fixed in code** - the grep now covers all four guards over docstring-stripped executable source with a lookbehind so `enforce` does not match `force` (`infra/tests/test_guard.py:114-147`), and a second test asserts every production call site passes zero arguments (`:150-176`). Section 4's assurance paragraph states both facts.
*Evidence:* infra/tests/test_guard.py:100-104 (`for name in ("guard.sh", "guard_cf.sh")`); infra/guard.py:43; infra/guard_cf.py:81,65-78; call sites archive/ship.py:289 and infra/cf_site.py:169.

**F14. MINOR. "`infra/guard.sh:18` sources the whole file, so the `aws` CLI it spawns inherits everything" is measurably false.**
`personal.env` has no `export` lines, so sourcing sets shell variables that never enter a child's environment. The guard exports one name.
*Addressed:* section 4's "Blast radius, corrected" states the measurement and keeps the conclusion, noting that the false fact was the one used to rank the two guards by risk.
*Evidence:* `grep -c '^[[:space:]]*export' infra/personal.env` -> 0. Sandbox: a file with SPACETRACK_PASS="..." sourced under `set -euo pipefail`, then `bash -c 'echo ${SPACETRACK_PASS:-UNSET}'` -> UNSET, and `env | grep -c SPACETRACK` -> 0. Export sites: infra/guard.sh:30, infra/guard_cf.sh:33.

**F15. MINOR. Section 3.12 named two `requests` sessions of four, and check 9 covered one unit of six with a command that cannot see an `EnvironmentFile`.**
`gp_pull` is the only session that transmits a password, and it was neither cited nor covered.
*Addressed:* 3.12 enumerates all four sessions, names `gp_pull` as the credential-carrying one, and says to assert across all six units by reading `/proc/<pid>/environ` rather than `systemctl show -p Environment`. Section 7 check 9 says the same and names `ephemera-catalogue` as the one that matters most.
*Evidence:* `grep -n 'Session()' archive/` -> poll.py:264, run_cycle.py:167, gp_pull.py:131, witness.py:372; credential transmission at archive/gp_pull.py:55; session construction and User-Agent at :131-133.

**F16. MINOR. The heredoc leaves credentials in shell history (secrets lens, same defect as F7 from a second angle).**
Raised independently with the extra point that the history file survives into the provider's disk snapshots and outlives any rotation of `personal.env`.
*Addressed:* section 4, "Suppress the shell history while you type it", which names `set +o history`, the `HISTCONTROL=ignorespace` alternative, and `history -c`, and marks the claim as asserted from shell behaviour rather than measured on a VPS.
*Evidence:* draft section 4 heredoc instruction with no history handling anywhere in section 4 or C1; its CR sensitivity claim is itself correct (infra/guard.sh:18 sources the file, infra/guard.py:28 uses splitlines()).

### Lens 3: Linux portability

**F17. SERIOUS. Section 3.9's proposed `pack.name` edit, applied as written, silently stops the site publisher.**
`web/build.py` reads its own output: with only the producer changed, the headline pack copy resolves a bare filename against the process CWD and raises `FileNotFoundError` under the unit's `WorkingDirectory`, uncaught, so the 4-hourly ledger run dies before the lint, the commit and the push.
*Addressed:* **fixed in code, both halves** - `web/build.py:157` publishes `pack.name` and `:318` rejoins that name to the spool the build just read; two tests pin it, the second running the build from an empty working directory (`web/tests/test_build_visibility.py:479,498`). Section 3.9 is rewritten to describe what was done, including that the committed ledger keeps the old strings until the next publish and that the leak is permanent in git history.
*Evidence:* web/build.py:153 (`"pack": str(pack) if pack.exists() else None`), :256 (`"visibility": {"reports": data["scores"], ...}`), :311-315 (`head = headline_report(...)`, `pack = head["pack"]`, `shutil.copyfile(pack, published)`); web/publish.py:57 (`rc = build.main([...])`, no try/except). Reproduced: FileNotFoundError at build.py:315 for 'globe_0e700520864b.json'.

**F18. MINOR. `SuccessExitStatus=143` covers nothing that can happen.**
systemd parses a bare number as an exit status, not a signal; a SIGTERM kill is reported as CLD_KILLED with status SIGTERM, and `Type=oneshot` does not get the implicit clean-exit signals. `ship.py` only ever returns 0, 1 or 4, so a stop or a `TimeoutStartSec` expiry mid-upload still left the unit failed - under a gate that requires `systemctl --failed` to be empty.
*Addressed:* 5.3's unit block says `SuccessExitStatus=SIGTERM` and the paragraph below it states why the numeric spelling was wrong; section 7 check 1 points back at it.
*Evidence:* systemd.service(5) SuccessExitStatus=: "Exit status definitions can be numeric termination statuses, termination status names, or termination signal names" and "for types other than Type=oneshot, one of the signals SIGHUP, SIGINT, SIGTERM, or SIGPIPE". Exit codes: archive/ship.py:310 `return 0 if ok else 1`, :314 `return poll.EXIT_INTERRUPTED` (=4, archive/poll.py:61).

**F19. MINOR. The line-drift correction in section 9 is itself wrong.**
The draft said `web/tests/test_build.py` CHROME is at 21 to 24 and the survey's 22 to 25 was wrong. It is the other way round.
*Addressed:* section 9's bullet states the measured truth, and 3.10 now cites `web/tests/test_build.py:22-25`.
*Evidence:* web/tests/test_build.py:21 `REPO = Path(__file__).resolve().parents[2]`; 22 `CHROME = next((c for c in (`; 23-24 the two `C:/Program Files` paths; 25 `"/usr/bin/google-chrome", "/usr/bin/chromium-browser") if Path(c).exists()), None)`.
