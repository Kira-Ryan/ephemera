# Migration runbook: Ephemera on one Linux VPS (proposed, 9 Sep 2026)

Status: **draft for the owner**. Produced by a six-component survey and one synthesis pass, then
attacked on three lenses (cutover, secrets, portability). The attacks found real defects, listed
at the end under "Findings not yet folded in"; the runbook text above them is as drafted and has
NOT been corrected for those findings. Resolve each finding before following the step it names.
Probe P8 (`probes/p8_vps_bootstrap/README.md`, 12 Sep 2026) has since answered section 1: the
feed serves a datacentre address at full rate and the root reproduces. Owner decisions of 12 Sep:
hosting stays non-AWS (D14), cost is a factor, and the host also publishes the site.

---

# Ephemera on one Linux VPS: migration runbook

Written 9 September 2026. Every claim below is cited to a file and line I read in this checkout, or marked as unverified. Where a survey I was handed was wrong or imprecise, I say so in the last section rather than quietly correcting it.

Measured on the live spool today, 9 Sep, so the runbook is sized against the present and not the briefing: **33** `cycle_*` directories under `Z:\ephemera\spool`, **10** of which still hold a `files/` directory. The briefing said 32 and 9. One cycle has rolled since it was written. The per-cycle record set is about 9 MB (`cycle.json` 4.44 MB, `etag_cache.json` 3.71 MB, `MANIFEST.txt` 821 KB, `witness.json` 7.5 KB, `ship.json` 924 B, `root.txt` 65 B, measured on `cycle_0e700520864b`). `spool/score` is 303 MB, `spool/gp` is 135 MB, `spool/daily` is 127 KB, `heartbeats.jsonl` is 1.94 MB. The orphaned `outbox/cycle_03329cf37459.tar` is 9,277,429,760 bytes and is still there.

---

## 0. The shape of the plan

Six components move: watcher, witness, shipper, catalogue, score, ledger. Five are pure single-writer jobs where running two copies is either wasteful or actively dangerous. One, the poller, is the exception: D10 (`DOCS/decisions.md`, D10) makes cycle identity the SHA-256 of `MANIFEST.txt`, so two pollers on the same manifest produce the same cycle id and, when complete, the same root. That is the whole reason a second poller is a check and not a duplicate, and it is what lets the archive run continuously across the cutover with no gap.

So the order is: prove the datacentre link with a throwaway instance, build the real host, start the VPS poller alongside the home poller, cut the other five over one at a time while both pollers run, then stop the home poller last.

One VPS satisfies "off Windows" and "non-AWS". It does not satisfy D14's "two providers/regions" or D03's two geographically separate pollers. Poller B stays PLAN item 9. Do not let this runbook be read as closing it.

---

## 1. Probe first: what to measure before spending money

CLAUDE.md says the cheapest probe that can kill the plan runs first, with a measured result and a date under `probes/`. Create `probes/p8_vps_bootstrap/README.md` and record everything below into it.

**Cost of the probe:** one hourly instance at the candidate provider, in the candidate region, destroyed the same afternoon. At Hetzner Cloud rates that is single-digit euro cents. Every question below is unanswerable from Cape Town and all of them are answerable in about two hours from a rented IP.

Run them in this order, because each one that fails makes the later ones pointless.

**P8.1 Reachability, 5 minutes.** TCP 443 and a TLS handshake to `api.starlink.com`, `www.space-track.org`, `web.archive.org`, `s3.eu-west-1.amazonaws.com`, `sts.amazonaws.com`, `github.com`, `api.cloudflare.com`, and `celestrak.org`. The last one is not needed by the runtime but P3 is recorded as blocked on network from the home IP (`probes/p3_six_digit/README.md:3-6`), so a datacentre IP that reaches CelesTrak unblocks P3 and PLAN item 11 for free. Record which resolve over A and which over AAAA, and whether IPv6 actually carries traffic. A host with AAAA records and no working IPv6 route turns every GET into `TIMEOUT_S=120` (`archive/poll.py:56`) times `RETRIES=3` (`archive/poll.py:55`) before it becomes a gap, which looks like a stalled poller and not an error.

**P8.2 Manifest and conditional GET, 5 minutes.** `GET /public-files/ephemerides/MANIFEST.txt`. Compare against today's live manifest: 821,305 bytes, 11,133 lines. Then re-issue with `If-None-Match` and confirm HTTP 304. D17 rests on that 304; without it the watcher's 120 s tick downloads 821 KB seven hundred and twenty times a day.

**P8.3 Rate, 30 minutes. This is the probe that can kill the plan.** Pull a 200-file disjoint slice at 16 connections, then a 400-file slice at 32. Record effective milliseconds per file, sustained MB/s, and every non-200 status. Extrapolate to 11,134 files.

- P1's kill line is more than 6 hours per cycle (`probes/README.md`, row P1). If the projection crosses it, the single-VPS plan is dead in that region and you move region or provider before buying anything.
- Watch specifically for a rate that is fine for the first 100 files and collapses after that, and for 403 or 429 appearing only at 32 connections. That is a datacentre-IP policy, and it is the failure the home link could never have shown you.
- If `api.starlink.com` returns 403 to the datacentre ASN outright, the goal changes shape: the home poller stays as poller A and the VPS becomes witness plus shipper plus score plus ledger. That is a decision entry, not a workaround, because it means the Windows machine cannot be switched off.

**P8.4 Upload to S3, 20 minutes.** `dd` a 2 GB file and multipart-upload it to a **scratch key with `StorageClass=STANDARD`**, then delete it. Do not probe with `DEEP_ARCHIVE`: it carries a 180-day minimum storage charge, and `ephemera-space-raw` is under Object Lock in governance mode. You need at least 1.3 MB/s for one 9.28 GB tar to fit the shipper's 2 hour ceiling, and you want 10 MB/s or better so a cycle ships in about fifteen minutes and 27.8 GB a day never backs up. Under about 3 MB/s, a single VPS cannot keep pace with the feed and the disk sizing below is wrong.

**P8.5 Native OpenTimestamps, 10 minutes.** `pip install opentimestamps-client`, then `ots stamp` a scratch file and `ots info` it. This is the check that retires Docker. `archive/witness.py:71-76` picks `ots` when `shutil.which("ots")` finds it and falls back to `docker` otherwise. If the native client installs and stamps, the Docker dependency is gone from the whole system and the currently unstamped cycle gets stamped on the first VPS witness pass. Record the exact version you install; the Docker path installs it unpinned on every invocation (`archive/witness.py:83`), so proofs on this spool may already come from more than one client version. Whether that matters to `ots verify` is unverified.

**P8.6 Wayback from a new IP, 15 minutes.** Submit three Save Page Now captures at the code's default `--capture-gap` of 12.0 s (`archive/witness.py:352-354`, whose justification is a home-IP measurement from 31 Aug). Record when the 429 arrives. From home, roughly eight rapid unauthenticated captures tripped the limiter. If a datacentre IP trips on the second, `--capture-gap` has to rise and authenticated SPN2 stops being a nice-to-have and becomes a cutover blocker, because a cycle's capture window is about eight hours and cannot be redone.

**P8.7 Space-Track, 2 minutes, and exactly once.** One `POST /ajaxauth/login` plus one query (`archive/gp_pull.py:55,58`). Do this in a minute when the home Catalogue task is not running. This is the only probe with account risk: two clients logging into one Space-Track account from two IPs is not documented anywhere I can check, and a soft block would look identical to a maintenance page because `archive/gp_pull.py:59-60` raises on any non-200 with no retry and no backoff.

**Kill and change conditions, stated up front:** projected cycle over 6 h kills the region. A 403 from the operator kills the poller half of the migration. S3 under 3 MB/s kills the single-host plan. Wayback throttling on the second capture blocks the witness cutover until SPN2 keys exist. Native `ots` failing to run costs you Docker on the VPS, which is an annoyance and not a kill, because Docker on Linux works even though Docker Desktop on the owner's machine does not.

---

## 2. VPS spec and provider shortlist

### Sizing, from the measured numbers

**Disk.** The shipper keeps `files/` for `--keep-days`, default 3.0 (`archive/ship.py:275`), and the feed rolls about every 8 hours, so the steady-state working set is about 10 cycles at 9.26 GB, which is 93 GB. On top of that:

| Item | Size | Source |
|---|---|---|
| Retention window, 10 cycles of `files/` | 93 GB | measured, 9.26 GB per cycle |
| One tar in `outbox/` during a ship | 9.3 GB | `archive/ship.py:126,189`; transient but real |
| Poller preflight floor, `--min-free-gb` | 25 GB | `archive/poll.py:247-248`, refuses below it with exit 5 |
| Cycle records, 33 cycles at 9 MB | 0.30 GB | measured |
| `spool/score`, growing about 12 MB per scored cycle | 0.30 GB now, +13 GB/year | measured, 3 cycles/day |
| `spool/gp`, never pruned, never shipped | 0.14 GB now, +8 GB/year | measured; nothing in the repo deletes it |
| Repo checkout with history, growing 5.2 MB per scored cycle | ~1 GB, +5.7 GB/year | the committed globe pack, PLAN follow-up (b) |
| OS and packages | 10 GB | |

That is about **140 GB with zero slack**. The number that decides the size is not the steady state, it is a shipper outage: at 27.8 GB a day, a 160 GB disk breaches the preflight floor inside two days of the shipper being stuck, and the poller then refuses to start a cycle, loudly, and the cycle is gone. **Buy 320 GB.** That gives about eight days of grace. Note that `shutil.disk_usage(...).free` is `f_bavail` on POSIX (`archive/poll.py:259`, `archive/ship.py:193-195`), so ext4's default 5 percent root reserve is invisible to the preflight: on a 320 GB volume that is 16 GB you paid for and cannot use. Either size up or set `tune2fs -m 1` on the spool filesystem at build time.

**RAM: 8 GB.** Justification, and the honest gaps in it. Score's rows list alone was measured at 111 MB resident and 148 MB peak for 143,101 rows, and the parent additionally holds the catalogue, the whole `results` list materialised at `score/visibility.py:281-283`, and the 5.2 MB pack, beside four forked workers. Full-process peak was never measured. The poller's only recorded peak is 1.6 GB RSS on a 100k-line all-404 manifest (PLAN.md, review items left open), which was reduced by dropping completed futures and **not re-measured**, and all 11,134 futures are still submitted up front (`archive/poll.py:360-361`). Six units run concurrently. 4 GB is probably enough and has no margin against two unmeasured peaks; 8 GB costs a few euro and removes the question. Measure peak RSS on the first real cycle and record it in the probe.

**vCPU: 4.** Score is the only real consumer, measured at about 8 minutes per cycle at 4 workers on the home PC while the watcher was pulling (PLAN.md, 2026-09-03), which is about 24 minutes of work a day at 3 cycles a day. The poller is IO-bound across 16 threads (`archive/poll.py:242`). Two vCPU would work and would roughly double score's wall time, which matters only when draining a backlog.

**Traffic: about 0.85 TB in and 0.85 TB out per month.** In: 9.26 GB per cycle times 3 cycles a day is 27.8 GB/day, plus the catalogue at up to 12 times 14.6 MB a day, plus Wayback `id_` re-fetches at roughly 22 MB per cycle. Out: the 9.28 GB tar per cycle to S3, same 27.8 GB/day, plus git pushes carrying a 5.2 MB pack per scored cycle. Choose a provider that either includes multi-TB egress or does not meter it. Do not choose a metered cloud with a 1 TB allowance.

### Shortlist, and the honesty about prices

**No VPS price in this repository is verified.** `probes/p4_cost/README.md:48` excludes "the VPS itself" from the cost table entirely, and line 68 records that Hetzner's own prices were **not captured** because hetzner.com renders them client-side, with the numbers taken from a third-party snapshot dated 13 Feb 2026 and marked "Unverified against hetzner.com". Every figure below is a desk estimate to confirm at purchase.

- **Hetzner Cloud** (Falkenstein, Nuremberg, Helsinki). CPX31 class, 4 vCPU AMD / 8 GB / 160 GB, plus a 200 GB volume; or CPX41, 8 vCPU / 16 GB / 240 GB. 20 TB egress included on EU locations. Estimate EUR 16 to 30 a month. Best price for the shape. Caveat beyond price: Hetzner is known for acting quickly on abuse complaints, which is a real consideration if the operator dislikes 27.8 GB a day from one IP.
- **OVHcloud VPS** (Gravelines, Frankfurt). Unmetered bandwidth. Estimate EUR 12 to 25.
- **Netcup** (Nuremberg, Vienna). Large disks cheaply. Estimate EUR 10 to 20.
- **Scaleway** (Paris, Amsterdam, Warsaw). Already priced in P4 for storage, so the account may already exist. Estimate EUR 15 to 30.

Excluded by decision, not by price: any AWS instance (D14, nothing on AWS runs continuously), and any Cloudflare compute (D08 zero-ops, and no Workers path exists for a 9 GB pull).

Region: EU, near eu-west-1 for the S3 leg. But the deciding input is P8.3's measured rate from that region to `api.starlink.com`, not proximity to Ireland.

**Rough monthly cost:** VPS EUR 15 to 30 (unverified), plus S3 Glacier Deep Archive at USD 10.3 to 16.5 at month 12 (P4 desk pricing, never checked against a real bill). Combined, roughly USD 27 to 50 a month at month 12. P4's USD 60 kill line was set for storage alone; if the owner wants one number covering compute too, that needs a new decision entry raising or restating the line.

Image: Ubuntu 24.04 LTS. `python3.12` is the distro Python and satisfies everything, including `pool.shutdown(cancel_futures=...)` at `archive/poll.py:386`.

---

## 3. Code changes

Deploy by `git clone` on the VPS, never by copying this working tree. `git ls-files --eol` shows the index is LF for everything, but the working tree here is CRLF for `Makefile`, `infra/deploy-site.sh`, `infra/guard_cf.sh` and `infra/site-bootstrap.sh` because this machine has `core.autocrlf=true`. A CRLF `Makefile` or shell script fails on Linux with `$'\r': command not found`. A fresh clone is clean. Also: every tracked file is mode 100644, so nothing has the executable bit; every `ExecStart` must name the interpreter and every shell script must be run as `bash infra/whatever.sh`.

### Required, blocks Linux operation

**3.1 `Makefile:24,27,30,34,38,42,46`** all invoke `python`, which does not exist on stock Ubuntu 24.04. Add `PY ?= python3` near `SPOOL ?=` and replace each bare `python` with `$(PY)`. Without this `make test`, the only gate that runs `score/tests` and the browser tests, fails at once. In practice the systemd units use the venv interpreter, so this is about the test gate and hand-running, which is exactly where you need it.

**3.2 `infra/guard_cf.sh:44`** pipes the zone response into `python -c`. On Ubuntu that is a missing interpreter, and the failure is **swallowed and misdiagnosed**: the `|| { ... }` block at lines 49 to 52 reports `REFUSED - the token cannot see the ephemera.space zone`, which sends you hunting a token problem that does not exist. Change to `python3`. Same one-word change at `infra/deploy-site.sh:9` and `infra/site-bootstrap.sh:13,14,15`. None of these run on the VPS under the recommended deploy path (section 4), but leaving a guard that fails closed with the wrong message is a trap for the next person.

**3.3 `archive/witness.py:71-73`, drop the silent Docker fallback.** Today `--ots auto` picks `ots` if `shutil.which("ots")` finds it and otherwise `docker`. Under systemd the unit's PATH is not a login shell PATH, so an `ots` installed into `/opt/ephemera/.venv/bin` is invisible and `auto` silently selects Docker, which is the exact dependency this migration removes. Two edits:

- At `archive/witness.py:78-81`, the native command is the bare string `["ots", *ots_args]`. Add an `--ots-bin` argument (default `"ots"`), store it on the runner, and use it here, so the unit can name `/opt/ephemera/.venv/bin/ots` absolutely and never depend on PATH.
- At `archive/witness.py:72-73`, make `auto` mean native-or-refuse: if `which(ots_bin)` finds nothing, raise rather than falling through to Docker. Docker stays reachable, but only when explicitly asked for with `--ots docker`, which is what `Makefile:51,55,59` still want on Windows. This converts a silent dependency into a loud refusal, which is the project's rule.

**3.4 `archive/witness.py`, persist the stamp before the Wayback loop.** `witness_cycle` calls `ots_step` at line 279 and writes `witness.json` once, at line 336, after a Wayback loop that can run eleven captures at a 12 s gap with 300 s timeouts each. A kill in that window leaves `root.txt.ots` on disk with no `stamped_utc` in `witness.json`. The next pass sees `proof.exists()` and `proof_matches()` both true (lines 184, 191 region) and goes straight to the upgrade branch, so `stamped_utc` is **never backfilled** and `web/build.py:76` renders the cycle as never stamped, permanently. The fix is one inserted line: `poll.write_json_atomic(w_path, w)` immediately after line 279. Under Task Scheduler this window was rare. Under systemd, restarts are routine.

**3.5 `score/run.py:96-107`, write the pack before the report, atomically.** Order today is: build pack in memory (96), write the report via `visibility.write_outputs` (97), write the pack file (105). `candidates()` treats the report's existence as "this cycle is done" (`score/run.py:61`), so a kill between 97 and 105 marks the cycle scored forever with no pack, and it is never retried. The comment at lines 90 to 95 (duplicated, and worth deduplicating while you are in there) claims the ordering prevents this. Traced, the claim holds for `build_pack` **raising**, and does not hold for the process dying. This is a live example of CLAUDE.md rule 10: a comment describing intent that reads exactly like a comment describing behaviour.

The consequence is worse than one missing pack. `web/build.py:311-317` takes the headline report's pack, and `headline_report` (`web/pages.py:78-84`) does not require a pack to exist. If the headline cycle's pack is missing, `head["pack"]` is `None` (`web/build.py:153`) and `web/build.py:317` **deletes** `web/dist/globe/pack.json`, shipping a globe page with no data and no error anywhere.

Edit: move the pack write above `write_outputs`, and write it through a temp file plus `os.replace` rather than `Path.write_text`. `archive/poll.py:139-148` already has exactly this helper; `score/` cannot import it without pulling `requests` in, so write the four lines locally. Then prove it: mutate the call site by deleting the pack write and confirm a test goes red.

**3.6 `archive/ship.py`, reclaim an orphaned outbox tar.** The tar is unlinked only inside the `if why:` upload branch. Once `needs_upload()` returns `None`, the file is unreachable forever. That is not theoretical: `outbox/cycle_03329cf37459.tar` is 9.28 GB of dead weight on the spool right now, for a cycle already shipped and verified whose `files/` are deleted, so it can never even be repacked (`pack()` calls `verify_local_files()`, which raises `CorruptCycle`). Under Task Scheduler this happened once. Under systemd, `TimeoutStartSec` and `systemctl stop` reproduce it on a schedule. Edit: in `ship_cycle`, when `why` is falsy, delete `<spool>/outbox/<cycle>.tar` if it exists and log that you did.

**3.7 `archive/poll.py:141`**, `tmp.write_text(json.dumps(obj, indent=1))` with no `encoding=`. Add `encoding="utf-8"`. This is cheap determinism, not a live bug: `json.dumps` defaults to `ensure_ascii=True`, so the bytes are ASCII either way. The real exposure is the readers with no encoding under a systemd unit that has no `LANG`, where Python's locale encoding can be ASCII. Do not shotgun `encoding=` into every `read_text` in the tree; set `LANG=C.UTF-8` in every unit (section 5), which covers those and also covers `web/publish.py:62`, the one `subprocess.run(..., text=True)` in the publish path with neither `encoding=` nor `errors=`, decoding page text and register phrases.

**3.8 `infra/personal.env.example`.** Verified: it names only `EPHEMERA_AWS_PROFILE`, `EPHEMERA_AWS_ACCOUNT_IDS`, `EPHEMERA_AWS_FORBIDDEN_IDS`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `EPHEMERA_CF_ACCOUNT_IDS`. It does **not** name `SPACETRACK_USER`, `SPACETRACK_PASS` or `EPHEMERA_CONTACT`. Provision the VPS from this template and `archive/gp_pull.py:49-50` raises, the broad handler at line 138 logs it, and the pass returns 1 every two hours forever: the component never works and never crashes. Add the three names, commented, with empty values.

### Recommended, not blocking

**3.9 `web/build.py:153`** publishes `str(pack)`, the absolute spool path. The committed public `web/dist/ledger.json` today contains 28 entries reading `Z:\\ephemera\\spool\\score\\globe_<sha12>.json` (I counted them). That leaks the machine's drive layout, and at cutover all 28 silently become the new POSIX path, a whole-file diff with no failure. `web/pages.py` never reads the field, only `pack_bytes` (checked: `pack_mb` is the only thing threaded through). Change to `pack.name`. Unverified: whether anything outside this repository consumes that field, in which case it is a breaking change and not cosmetic.

**3.10 `web/tests/test_build.py:21-24`.** The browser is located at two `C:/Program Files` chrome paths plus `/usr/bin/google-chrome` and `/usr/bin/chromium-browser`. Neither `/usr/bin/chromium` nor `/snap/bin/chromium` is listed, so on a VPS with a snap Chromium every browser test calls `pytest.skip` and `make test` goes green with CLAUDE.md's "a green flag is not a picture" silently unenforced. Add both paths, and install a real browser on the VPS.

**3.11 `requirements.txt`.** `opentimestamps-client` is not in it; it appears only inside the Docker shell string at `archive/witness.py:83` and the `Makefile` stamp targets. On Linux it becomes a first-class dependency. Do not add it to `requirements.txt` unless you have confirmed it installs on Windows too, or the owner's dev machine loses `pip install -r requirements.txt`. Install it explicitly in the bootstrap at the version P8.5 measured, and add a comment in `requirements.txt` naming it and saying where it is installed.

**3.12 Proxy environment.** Both sessions are built with default `trust_env` (`archive/poll.py:264-269`, `archive/run_cycle.py:167-168`), so a VPS image that sets `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, `REQUESTS_CA_BUNDLE` or `CURL_CA_BUNDLE` changes routing or trust with no log line. None are set here. Rather than editing code, assert in the bootstrap that none of the five is set in the units' environment, and record the assertion.

### Does the Windows console suppression still matter?

No. `pythonw.exe` disappears entirely: every `ExecStart` names the venv interpreter, and the reason `pythonw` existed at all was two console windows that were closed and killed the watcher on 30 Aug (PLAN.md, Day 0 item 1).

The artefact it left in code is `run_cycle.configure_logging` at `archive/run_cycle.py:49-50`: `if log_file is None and sys.stderr is None: log_file = spool / "run_cycle.log"`. Under systemd, stderr is always a valid file descriptor, so that branch is dead. Leave it; it is the Windows path's only protection and removing it is out of scope.

What still matters is the consequence, and it is a unit-file rule, not a code edit. **Never pass `--log-file` on Linux, and never set `StandardError=null`.** With a real-but-null stderr the fallback does not fire, and every log line from both modules goes to `/dev/null` with no complaint. Note also that the fallback file is named `run_cycle.log` regardless of which program is running, so `witness.py`, `ship.py` and `gp_pull.py` given `--log-file` would interleave into the watcher's file. There is no rotation anywhere in the code, only a plain `logging.FileHandler` at `archive/run_cycle.py:53`, and the current `run_cycle.log` is 509 KB over seven days, so journald is strictly better on both counts.

---

## 4. Secrets

Names only. Nothing below prints a value, and nothing in this migration adds an override to any guard.

### What must exist on the VPS

**`/opt/ephemera/infra/personal.env`**, mode 0600, owned by the service user, gitignored by `.gitignore` (`infra/*.env`). The path is fixed by `infra/guard.py:16` relative to `guard.py` itself, so it must live inside the checkout, not in `/etc`. Contents:

| Name | Read by | Consequence if missing |
|---|---|---|
| `EPHEMERA_AWS_PROFILE` | `infra/guard.py:48`, `infra/guard.sh:24` | `GuardRefused`, shipper exits with a traceback |
| `EPHEMERA_AWS_ACCOUNT_IDS` | `infra/guard.py:46` | empty is a refusal by design, not a pass |
| `EPHEMERA_AWS_FORBIDDEN_IDS` | `infra/guard.py:47` | checked before the allowlist; a match wins |
| `SPACETRACK_USER` | `archive/gp_pull.py:44,48` | catalogue fails silently forever, exit 1 every 2 h |
| `SPACETRACK_PASS` | same | same |

Write this file **on the VPS with a heredoc**, never by pasting from a Windows editor. `infra/guard.sh:18` sources it with `.`, so a trailing CR becomes part of `AWS_PROFILE` and the `aws` CLI then fails at `guard.sh:32`. `infra/guard.py:28` is immune because it uses `splitlines()`, which drops the CR. The live file here is LF today, so an `scp` of it is safe as-is if you prefer that to retyping. Note the parser at `infra/guard.py:17` cannot represent a value containing a double quote and strips trailing whitespace, which constrains what a Space-Track password may contain.

**AWS profile section.** `infra/guard.py:54` sets `os.environ["AWS_PROFILE"]` unconditionally before the first API call. A `[profile <name>]` section must therefore exist in a config file the service user can read. Under systemd, `HOME` is unset unless the unit provides it, so `~/.aws/config` will not be found and the failure surfaces as `guard: could not establish the AWS identity` (`infra/guard.py:56-58`), which reads like a credentials problem. Set `Environment=AWS_CONFIG_FILE=/opt/ephemera/.aws/config` explicitly in the shipper unit; that removes the ambiguity. The credentials themselves may live in that section or in the unit's environment. One survey measured that env-var keys alone are not sufficient without the section; I did not re-run that measurement, so confirm it on the VPS with one `python3 infra/guard.py` before trusting it.

**Blast radius, worth knowing.** `infra/guard.py:24-34` parses every `KEY=VALUE` line into an in-process dict, so the shipper process also holds the Cloudflare and Space-Track values even though `enforce()` uses only the three `EPHEMERA_AWS_*` names and exports only `AWS_PROFILE`. Nothing leaks to a child process. `infra/guard.sh:18` is looser: it sources the whole file into the shell, so the `aws` CLI it spawns inherits everything. That is one more reason not to put Cloudflare on the VPS at all.

**`/etc/ephemera/ephemera.env`**, mode 0640, an `EnvironmentFile` for the units. Holds `EPHEMERA_CONTACT`, `LANG=C.UTF-8`, `PYTHONUNBUFFERED=1`. `EPHEMERA_CONTACT` is not a credential, it is the address published in the User-Agent (`archive/poll.py:74-75`), but four entry points refuse to start without an address containing `@`: `archive/poll.py:255-257`, `archive/run_cycle.py:162-164`, `archive/witness.py:368-370`, `archive/gp_pull.py:128-130`, all returning exit 5. Put it in the `EnvironmentFile` rather than on the `ExecStart` line, because the command line is world-readable in `/proc`.

**Git push credential for `web/publish.py:94`.** The code runs a bare `git push` and delegates entirely to git's configuration; `remote.origin.url` in `.git/config` is HTTPS today, which on Windows resolves through Git Credential Manager. A systemd unit has no TTY and no credential helper, so the push fails, `web/publish.py:96` logs `push failed (will retry on the next run)`, and the unit commits locally forever and never publishes, because by design it never rebases or force-pushes (`web/publish.py:7-8`).

Use an **ed25519 SSH deploy key generated on the VPS**, added to the repository's Deploy Keys with write access, and set `git remote set-url origin git@github.com:Kira-Ryan/ephemera.git`. Over a PAT: the private half never leaves the VPS, it is scoped to this one repository, and it is revocable in the repository settings without touching the account. The unit needs `Environment=GIT_SSH_COMMAND=ssh -i /opt/ephemera/.ssh/id_ed25519 -o IdentitiesOnly=yes -o UserKnownHostsFile=/opt/ephemera/.ssh/known_hosts`, and that `known_hosts` must be seeded with GitHub's host keys at bootstrap, from GitHub's published fingerprints, not from a blind first connection.

Two more git settings that are not secrets and will otherwise stop the publisher dead:

- `git -C /opt/ephemera config user.name` and `user.email`. They are repo-local here, not global (deliberately: PLAN.md keeps the employer address out of the history), so a fresh clone has no identity and `git commit --only` at `web/publish.py:84-87` fails with "Please tell me who you are", logged as `commit failed` at line 89 and returning 1.
- `git config --global --add safe.directory /opt/ephemera` if the unit's user does not own the checkout. Otherwise git refuses every command with "dubious ownership", `committed_cycle_count()` silently returns `None` (`web/publish.py:29-35`), which **disables the shrink guard at line 71**, and the commit fails anyway. Simplest is to make the service user own the checkout and skip the setting.

### The Cloudflare deploy from a VPS: do not put it there

The site deploy does not need to happen on the VPS at all. `.github/workflows/deploy-site.yml` runs on `ubuntu-latest`, installs the pinned `blake3` from `requirements.txt` in its own step before any secret is in the environment, and runs `python infra/cf_site.py deploy` with `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` and the optional `EPHEMERA_CF_ACCOUNT_IDS` from GitHub secrets. `infra/cf_site.py` calls `guard_cf.enforce()` before its first write and exits on refusal. PLAN.md records this proven end to end on 31 Aug.

So the VPS pushes; the runner deploys. **No Cloudflare credential ever reaches the VPS**, `curl` is not needed, `blake3` is not needed, and `infra/guard_cf.sh` never runs there. That is a real reduction in what one compromised host holds, and it is the recommended path.

If a manual VPS deploy is ever wanted, it needs `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` and `EPHEMERA_CF_ACCOUNT_IDS` added to `personal.env`, plus `curl`, plus the `python3` fixes in 3.2. Recommend not doing it. And never `wrangler`, on any machine: it was retired on 31 Aug after a sentinel test proved it ignores `CLOUDFLARE_ACCOUNT_ID` for a Pages deploy and targets an employer account from machine state.

### How the guards keep working

`infra/guard.py` has no platform dependency: `pathlib`, `re`, `os.environ`, and a `boto3` STS call. It works unchanged on Linux given the profile section and `AWS_CONFIG_FILE`. `archive/ship.py:288-289` calls `guard.enforce()` and nothing catches `GuardRefused`, so a misconfigured host fails loudly and terminally, which is correct.

`infra/guard.sh` needs bash (not dash: `#!/usr/bin/env bash`, `set -euo pipefail`, `${BASH_SOURCE[0]}`) and the AWS CLI on PATH (`guard.sh:32`). The shipper never touches it; only `infra/whoami.sh:4` does. **Correcting one survey:** the AWS CLI is *not* needed for the test gate. `infra/tests/test_guard.py:25-40` stages a copy of `infra/` with a **fake `aws` script** on PATH, and only skips the module when bash is absent. So AWS CLI v2 on the VPS is optional and only for hand-running `whoami.sh`. Install bash (present) and, if you want `whoami.sh`, the CLI.

Neither guard has an override flag, environment variable or argument, and `infra/tests/test_guard.py` greps for one. Nothing here adds one.

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
Environment=AWS_CONFIG_FILE=/opt/ephemera/.aws/config
ExecStart=/opt/ephemera/.venv/bin/python -u /opt/ephemera/archive/ship.py \
  --spool /srv/ephemera/spool --once --max-cycles 1
TimeoutStartSec=2h
SuccessExitStatus=143

# .timer
OnBootSec=5min
OnUnitActiveSec=30min
Persistent=true
```

This is a port, not a redesign: the live Windows task already runs `--once --max-cycles 1` on a PT30M repetition with a PT2H execution limit. `--interval` exists at `archive/ship.py:279` with default 1800.0 but production does not use it, and the code argues against it: in loop mode `main()` never returns and the per-pass result is only logged, whereas `--once` returns 0 or 1 and hands systemd a real exit status. Nothing survives in memory between passes.

Do **not** add `SuccessExitStatus=1`. A pass that recorded an error should show as a failed unit so you notice it in `systemctl --failed`; that is better observability than Task Scheduler ever gave. `143` is there so a stop during an upload does not read as a defect.

`--max-cycles 1` because one cycle is 9.28 GB and the pass duration from a datacentre uplink is unmeasured. Raise it only after P8.4. Note that `--max-cycles` budgets uploads only (`archive/ship.py:302-307`): record re-syncs and the retention delete still run for every cycle every pass, which is what keeps a 30-minute cadence worth having when nothing new is ready.

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
OnUnitActiveSec=2h
RandomizedDelaySec=300
Persistent=true
```

A timer, and the code says so four ways. A pass carries no state forward: the only survivor is the `requests.Session`, and `archive/gp_pull.py:55` re-authenticates every pass, so the session buys connection reuse within a pass and nothing across passes. `--once` surfaces failure as an exit code (`return 0 if ok else 1`, line 143), whereas in loop mode the identical failure is only logged at lines 138 to 141. The loop drifts, because `pause(args.interval)` starts after the pass completes, so the true period is 7200 s plus the pass duration; `OnUnitActiveSec` plus `Persistent=true` holds the cadence and recovers a run missed over a reboot. And SIGTERM is unhandled here (line 146 catches only `KeyboardInterrupt`), so a service would be killed mid-sleep with no clean path.

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
Environment=GIT_SSH_COMMAND=ssh -i /opt/ephemera/.ssh/id_ed25519 -o IdentitiesOnly=yes -o UserKnownHostsFile=/opt/ephemera/.ssh/known_hosts
ExecStart=/opt/ephemera/.venv/bin/python -u /opt/ephemera/web/publish.py --spool /srv/ephemera/spool
TimeoutStartSec=15min

# .timer
OnUnitActiveSec=4h
Persistent=true
```

A timer driving a oneshot, never a service. `web/publish.py`'s argparse declares only `--spool`, `--no-push`, `--allow-shrink` and `--log-file`: there is **no** `--interval` flag and no default interval anywhere in the file. `main()` performs exactly one build, one lint, one shrink check, one commit and one push, and returns. The 4 hour figure lives entirely in the scheduler.

`TimeoutStartSec` is mandatory here because `web/publish.py:24` and `:62` both call `subprocess.run` with **no `timeout=`**, so a hung `git push` would otherwise run forever; on Windows the task's execution limit bounded it. There is also no lock file in `publish.py`, so overlap protection is entirely systemd's refusal to start a second instance of a running oneshot.

`ExecStart` must be the **absolute path to `web/publish.py`**, not `python -m web.publish`, because line 53 does a bare `import build` with no `sys.path` insertion; it works only because Python puts the script's own directory on `sys.path[0]`, and `PYTHONSAFEPATH=1` would kill it.

`LANG=C.UTF-8` because of the un-encoded subprocess decode at line 62.

Cost is not the constraint: a full build against the real 33-cycle spool was timed at about 1.2 seconds. 4 hours is a freshness choice against an 8 hour feed cadence, so the page is never more than half a cycle stale. `score/run.py` produces new reports every 30 minutes, so a scored cycle waits up to 4 hours to appear; tighten to 1 hour if that matters, the build cost is noise.

**One thing to install for this unit that is easy to miss:** `fonts-dejavu-core`. `web/brand.py:133-143` names `CascadiaMono.ttf`, `consola.ttf`, `DejaVuSansMono.ttf` and `georgia.ttf`, `DejaVuSerif.ttf`, catches `OSError` per name, and drops through to `ImageFont.load_default` with **no warning**. On Linux only the DejaVu names can ever resolve, so without that package the 1200x630 social card renders in Pillow's bundled default at whatever metrics it likes, on every deploy, silently.

---

## 6. Cutover without losing a cycle

The feed drops each set after about eight hours, so a gap is permanent. The whole point of the order below is that the poller is the one component where running two copies is safe, so it goes first with overlap and everything else follows behind it inside one cycle.

### Can both pollers run at once? Yes, and they should

They must be on **separate spools on separate machines**. There is no lock anywhere and single-writer is a design assumption (PLAN.md, open review items). Two pollers on one spool would race on `heartbeat.json.tmp` and on the cycle record.

On two spools, D10 does exactly what it was written for: identity is the manifest SHA-256, so both produce `cycle_<same sha12>`, and D11 removed the wall-clock date precisely so a resume or a second poller across UTC midnight does not produce a different identity. When both complete, both produce the same root under the D09 construction. That is not a duplicate, it is the first real cross-poller check this project has ever run, and it is direct evidence for PLAN item 9. Record the comparison in the probe.

Note that the case-insensitive duplicate rule at `archive/poll.py:111-129` and the colon rejection at `archive/poll.py:95` are Windows-shaped rules that now bind Linux. **Keep them.** A Linux poller must refuse exactly what the Windows poller refuses, or the two roots can differ and D10's guarantee evaporates. No live cycle has ever tripped either: all 33 `cycle.json` records show `manifest_anomalies = 0`.

The one real cost of the overlap is doubled load on `api.starlink.com` from two IPs during the window, which is D03's intent anyway. Keep the window to one or two cycles, not a week.

### What must never run twice

**Shipper. Absolutely never.** Both hosts would PUT to the same key `cycles/<sha12>/files.tar`, and the tars are **not** byte-identical across hosts: the five record members are added with `tarfile.add` (`archive/ship.py:132-134`), which copies uid, gid, uname, gname and mode from the filesystem, and Linux records the service user's real values where Windows records mode 666, uid 0 and empty names. So two shippers would write two different objects to one versioned key, each host's `ship.json` claiming its own SHA-256, and a restore verified against one would fail against the other. This is the single most damaging thing that can go wrong in the cutover.

**Ledger publisher. Never.** Both commit to `main`; the loser's `git push` is rejected non-fast-forward and `publish.py` never pulls, rebases or force-pushes, so it wedges permanently, visible only as one log line at `web/publish.py:96`.

**Witness. Never, in practice.** Two witnesses would double Save Page Now submissions inside the one window that cannot be redone, and P8.6 has not yet told you how much throttle headroom a datacentre IP has.

**Catalogue. Never.** Two clients logging into one Space-Track account from two IPs is undocumented and could look like abuse. The rate itself is trivial, 48 requests a day against 30 a minute and 300 an hour, but a soft block looks identical to a maintenance page because `archive/gp_pull.py:59-60` raises on any non-200 with no retry. A two-hour gap in catalogue snapshots costs a shifted pairing and nothing irreplaceable; an account lock costs the whole `score/` layer.

**Score. Wasteful, not dangerous.** Different spools, different outputs. Still cut it over as one switch.

### Moving the 33 cycles and their records

Total non-raw state is about **740 MB**: 33 cycles of records at 9 MB each (300 MB), `spool/score` (303 MB), `spool/gp` (135 MB), `heartbeats.jsonl` (1.94 MB), `spool/daily` (127 KB). That is a single tar over ssh, minutes not hours.

Build it on Windows with `tar` from Git for Windows (rsync is not shipped with it), excluding `files/`, and extract on the VPS. **Binary-safe only.** `score/resummarise.py:35-39` rebuilds every report's summary from the gzipped rows files, and `score/catalogue.py:53-56` hard-fails a snapshot whose bytes do not hash to its record, so any text-mode or CRLF-translating copy destroys both silently.

Per-directory rules:

- **`cycle_*/`**, everything except `files/`: `cycle.json`, `MANIFEST.txt`, `root.txt`, `root.txt.ots`, `root.txt.ots.bak`, any `root.txt.ots.stale-*`, `witness.json`, `ship.json`, `etag_cache.json`. Copy `root.txt.ots` **byte-exact and before the witness unit ever starts**: if it is absent, `proof_matches()` returns False, the cycle is stamped again, and its committed timestamp becomes the migration date. The Bitcoin attestation evidence for the original stamping time is destroyed and cannot be recovered. `ship.json` is equally critical in the other direction: without it `needs_upload()` returns "not yet shipped", and for the 23 cycles whose `files/` are already deleted that means `pack()` raises `CorruptCycle` and the pass returns 1 every thirty minutes forever.
- **`daily/`**: complete or not at all. If `root.txt` exists for a day without `daily.json`, `archive/witness.py:238` raises `FileNotFoundError`, which the caller's blanket handler at lines 392 to 396 catches, so the **entire** daily step aborts for **every** day on **every** pass with only "daily-root step crashed" in the log. Unlike `witness_cycle`, which isolates per cycle. And if a day's `root.txt` is missing entirely, the day is rebuilt from whatever `cycle.json` files are then present; if any of that day's cycles did not migrate, the rebuilt root differs from the one already stamped and published, which is a silent falsification.
- **`gp/`**: complete, and the directory **names** must survive byte-identical. `score/catalogue.py:66` sets `snapshot_id = snapshot_dir.name`, `score/visibility.py:318` writes it into every report as `catalogue_snapshot`, and `score/globe_pack.py:109` resolves it straight back to `spool/gp/<name>`. Renaming on migration silently breaks every existing report's pack rebuild. Copying `gp/` also fixes the first-pass duplicate: `latest_sha()` compares against the newest record in its own spool, so on an empty `gp/` the first VPS pass would re-store a byte-identical catalogue and put a duplicate sha12 row in the ledger.
- **`score/`**: complete and binary-safe. Only 10 of 33 cycles still hold `files/`; for the other 18 scored cycles the report and its rows file **are** the measurement, and re-scoring them would need a Deep Archive restore. If `score/` is absent nothing errors: all 10 cycles that still hold files are re-scored from scratch, about 80 minutes of CPU, and every regenerated report carries a fresh `as_of` (`score/visibility.py:305`), so the site republishes new as-of dates for measurements that did not change.
- **`heartbeats.jsonl`**: copy, then let the VPS watcher append. It is the only source for D18 observed coverage (`web/build.py:170-178`); `coverage_24h` (lines 181 to 199) returns `None` when the history is shorter than the window and publishes "not yet measured". The current figure is 0.743. It is a rolling 24 hour window, so a cutover gap is published honestly as an uncovered window and heals within a day. Do not recreate it empty.
- **`heartbeat.json`**: do **not** copy. It is gitignored, regenerated on the first tick, and `archive/witness.py:108-116` reads it to decide whether the watcher is alive.
- **`outbox/`**: do **not** copy. Recreate empty; `pack()` mkdirs it anyway. The 9.28 GB `cycle_03329cf37459.tar` there is dead: that cycle shipped on 4 Sep, adopted its fingerprint on 6 Sep and had its local files deleted on 7 Sep. Delete it on Windows too, once you have confirmed its `ship.json` shows `shipped` with a `files_fingerprint`.
- **`partial/`**: disposable, one `--limit` test slice.
- **`cycle_*/files/`, 10 directories at about 9.26 GB, 93 GB total.** Do not copy them wholesale. The rule is: copy `files/` **only** for cycles that are either (a) not yet shipped with a matching fingerprint, or (b) still listed in `spool/score/run.json`'s `pending`. Everything else's raw bytes are already in Deep Archive, HEAD-verified, and the local copy is about to be deleted by retention anyway. Enumerate both sets before you copy; at 4.2 MB/s from the home uplink each 9.26 GB cycle is about 37 minutes, so the difference between "copy what is needed" and "copy all ten" is potentially six hours of uplink you would rather spend shipping.

Nothing goes missing if you copy `files/` while the home poller is running: those directories are for **completed** cycles, and a completed cycle is never rewritten.

### The order

Run every step with the previous one verified. Home keeps polling throughout steps C1 through C8.

**C0. Probe.** Section 1, on a throwaway instance. Home untouched. Destroy the instance.

**C1. Build the real host.** Provision, `apt install python3.12-venv git bash ca-certificates fonts-dejavu-core chromium-browser`, create the `ephemera` user and `/srv/ephemera/spool`, `git clone`, venv, `pip install -r requirements.txt` plus the pinned `opentimestamps-client`, write `personal.env` and `ephemera.env` by heredoc, install the units disabled. Land the code edits from section 3 on `main` first, so the clone has them. Home untouched.

**C2. Gate: `make test` green on the VPS**, with a real browser present so the browser tests do not skip. Then `python3 infra/guard.py` prints the personal account and profile, and a deliberately wrong account id in a sandbox copy refuses. Then `archive/poll.py --limit 5` against a scratch spool: five files, a partial record under `partial/`, no root, exit 3 (D13). This is the first time the code has ever been run on Linux, so treat a failure here as expected rather than surprising.

**C3. Start `ephemera-watcher.service`. Both pollers now running.** Zero risk of a gap; this is the only step that adds a poller before removing one.

**C4. Gate: one full cycle pulled by both.** Wait for the manifest to roll. Compare `cycle_<sha12>/root.txt` on the two hosts. **Identical roots is the go signal for everything that follows.** Different roots, or a missing root on the VPS, and you stop and find out why before touching anything on Windows. Record the VPS wall time against P1's 6 hour kill line and against the home machine's 45 to 116 minutes.

**C5. Copy the historical records** (740 MB) plus the selected `files/`. Use `--ignore-existing` semantics at the cycle-directory level: a cycle directory the VPS already pulled itself must never be overwritten by the Windows copy. That is not caution, it is the point of C4.

**C6. Witness: stop the Windows task, then start `ephemera-witness.service`.** Do this immediately after C5, and time it just after a cycle's captures have completed rather than mid-window (check the current cycle's `witness.json` for pending samples). Within one 300 s interval the VPS witness picks up the current cycle. The first pass also stamps the cycle that has been sitting unstamped because Docker Desktop is broken, which is the migration paying for itself.

**C7. Catalogue: stop, then start.** Never overlapping. Verify a new `gp/` snapshot inside two hours, and that it is **not** a duplicate of the newest copied one.

**C8. Score: stop, then start.** Verify one new report plus a pack over 4 MB.

**C9. Shipper: stop, then start.** Before starting, confirm every cycle in the VPS spool carries its copied `ship.json`. Verify the first VPS ship: one new object version for one key, HEAD-verified by the code itself, and `ship.json` recording it.

**C10. Ledger: stop the Windows task, then start `ephemera-ledger.timer`.** The first VPS build must report at least 33 cycles or `web/publish.py:71-75` refuses to publish, quoting the published count. That guard is your safety net; do not reach for `--allow-shrink` to get past it. Verify the commit, the push over the deploy key, the `deploy-site` workflow going green, and `ephemera.space` serving the new build. This must follow C4 within one build interval, or the published page silently goes stale while the VPS accumulates cycles the Windows build cannot see.

**C11. Stop the Windows Watcher.** The archive is now entirely on the VPS.

**C12. Leave the Windows machine powered, all six tasks disabled, spool untouched, for seven days.**

---

## 7. Verification and rollback

### Per-step gates

Already stated inline: C2 (test suite, guard, limit slice), C4 (matching roots), C7 to C10 (one live artefact each). Do not proceed past a red gate.

### Before the home machine is switched off

Everything here is a command that either passes or does not. "Looks fine" is not a gate.

**The strongest single check.** `python3 archive/verify.py <a VPS-pulled cycle> --wayback`, exit 0. It deliberately re-implements the D09 Merkle construction from the documented paragraph rather than importing the poller's function, so a passing root is agreement between two independent codings. It checks the cycle's identity against `MANIFEST.txt`, the names against the manifest order, every stored gzip against the record, the root, `root.txt` being exactly 65 bytes (D12), the OpenTimestamps proof being bound to **this** root, and the Wayback copies being re-fetchable and re-hashable. If this passes on a cycle the VPS pulled, stamped, captured and shipped by itself, the migration has genuinely worked.

**Then, in order:**

1. `systemctl is-active` on the three services and `systemctl list-timers` on the three timers. `systemctl --failed` empty.
2. Watcher: `heartbeat.json` age under 10 minutes, `heartbeats.jsonl` growing, at least two complete VPS-pulled cycles with roots, wall time comfortably inside 6 hours.
3. `journalctl -u ephemera-watcher --since -24h` non-empty. If it is empty, you set `StandardError=null` or passed `--log-file`, and you have been running blind.
4. Witness: a VPS-created `root.txt.ots`, `ots verify` passing, and within an hour or two a `block_height` in `witness.json`. Also confirm `witness.json` carries `stamped_utc`, which is what edit 3.4 protects.
5. Shipper: one VPS-shipped cycle. Confirm exactly one object version was written for that key. The restore drill remains outstanding from PLAN item 8 and this is the moment to do it: a Bulk restore in-region, verified against the recorded SHA-256 per VERIFY.md. It takes 12 to 48 hours, so start it at C9 and let it run.
6. Score: one VPS report plus a pack over 4 MB, and `run.json` showing no unexpected `skipped_no_files`.
7. Ledger: `web/dist/ledger.json` on the live site showing at least 33 cycles, `coverage_24h` recovered above the pre-migration 0.743 after 24 hours, and the pack paths no longer reading `Z:\` if you took edit 3.9.
8. Disk: `df -h` for the `ephemera` user showing free space above 25 GB with three days of retention held. Remember `f_bavail` excludes the ext4 reserve.
9. Environment: `systemctl show -p Environment ephemera-watcher` contains none of `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`.
10. Reboot the VPS once, deliberately, and confirm all six come back and the watcher resumes the in-flight cycle from its ETag cache rather than re-pulling 9 GB.

### Rollback

Up to and including C10, the rollback is two minutes: stop the VPS unit, re-enable the Windows scheduled task. It works because every component except the poller is single-writer and the Windows spool is untouched until C11.

After C11 the rollback is the same command, and the Windows spool then has a hole for whatever the VPS pulled in between. The VPS spool holds those cycles, so the union is complete and nothing is lost; you would copy them back the way you copied forward.

The one genuinely irreversible action is an S3 write. A cycle shipped from the VPS under a key Windows would also ship is a second object version with a different tar SHA-256 and a contradicting `ship.json`. Prevent it, do not plan to recover from it: never two shippers, and check `systemctl --failed` on the VPS before re-enabling the Windows Shipper for any reason.

Keep the Windows spool intact for seven days after C11. It is both the cold rollback and the source for any `files/` you decide you needed after all.

---

## 8. What stays on the owner's machine

**Nothing operational.** That is the goal and, if the probes pass, it is achievable. The six scheduled tasks are deleted, not disabled-and-forgotten. `pythonw.exe` is not needed. Docker is not needed: the OTS client runs natively on Linux, which removes the one dependency that is currently broken on the owner's machine and has left a complete cycle unstamped.

**What stays by choice:**

- The development checkout. Editing, `make test`, `codex review --base origin/main` before pushing. That is where the owner works and it should not move.
- The Docker `stamp`, `upgrade` and `verify` targets in `Makefile:51,55,59`. They are Windows-only conveniences for hand-checking a proof and they cost nothing to leave.
- The spool as a cold second copy for the retention week, then archived or deleted.

**What the owner still holds personally, and should be able to revoke independently.** The VPS gets a copy of the AWS credentials, the Space-Track credentials and a GitHub write key. Where the provider allows it, make each one VPS-specific: a distinct IAM user with a policy scoped to `PutObject` and `HeadObject` on `ephemera-space-raw` (note D14 says "put-only credentials on the poller", which would break `archive/ship.py:206-212`'s HEAD verification, so the deployed policy needs checking before the VPS gets a key, and it is not in the repository), and a repository deploy key rather than an account PAT. The Space-Track account cannot be split, which is the one credential the two machines would genuinely share, and is the reason the catalogue cutover is a single atomic switch rather than an overlap.

**What deliberately never reaches the VPS:** the Cloudflare token. The deploy stays on GitHub Actions, which is already proven on `ubuntu-latest`. The VPS pushes; the runner deploys. One less secret on the one host that holds everything else.

---

## 9. Where the surveys were wrong or imprecise

Stated because the runbook is built on them and you should know which parts I re-checked.

- **The AWS CLI is not required for the test gate.** One survey implied `infra/guard.sh` needs AWS CLI v2 installed for `make test` to be meaningful. `infra/tests/test_guard.py:25-40` stages a copy of `infra/` with a **fake `aws`** script on PATH and only skips the module when bash is absent. The CLI is needed only to hand-run `infra/whoami.sh`.
- **The `score/run.py` comment is not simply wrong, it is incomplete.** The survey read lines 90 to 95 as a false claim. Traced: the comment's claim holds for `build_pack` raising, which does leave the cycle pending. What it does not cover, and what the survey correctly identified as the defect, is the process dying between the report write at line 97 and the pack write at line 105. The fix is the same either way; the characterisation matters because the next person reading that comment should know which half is true.
- **P4 does not price the VPS at all.** One brief asked me to note that P4's Hetzner prices are unverified. They are (`probes/p4_cost/README.md:68,220`), but the more important fact is `probes/p4_cost/README.md:48`, which excludes "the VPS itself" from the entire cost table. There is no verified compute price anywhere in this repository, from any provider.
- **Cycle counts.** The briefing's 32 cycles with 9 holding raw files is now 33 with 10 holding raw files, measured 9 Sep. One cycle rolled between the briefing and this runbook.
- **Line drift.** A few survey citations were off by one to three lines (`web/tests/test_build.py` CHROME is at 21 to 24, not 22 to 25; `archive/witness.py`'s runner selection is 71 to 73). Every file:line in this runbook I read directly.
- **What I did not verify.** I made no AWS call, so the D15 seven-day multipart-abort lifecycle rule on `ephemera-space-raw` and the IAM policy behind the profile are both unchecked. I did not run the test suite on Linux. I did not measure the ProfileNotFound behaviour myself. I did not reproduce the 31 Aug "identical blake3 hashes cross-OS" claim in PLAN.md, which sits uneasily with `infra/cf_site.py` hashing working-tree bytes on a machine that writes CRLF; moving the build to Linux removes the question rather than answering it. And the SIGTERM handler at `archive/poll.py:233` has never been executed by anything, on any platform, which makes it the first thing to test on the VPS.

---

## Findings not yet folded in (adversarial passes, 9 Sep 2026)

### Lens: Cutover sequence only (section 6/7): cycle loss, double pull, double ship, premature delete, and two pollers contending for one spool or one Space-Track account. Verified against archive/poll.py, archive/run_cycle.py, archive/ship.py, archive/witness.py, score/run.py, web/publish.py and the live Z:\ephemera\spool records.

**Verdict.** Not sound on this lens. Followed literally, the cutover does not lose a cycle's raw bytes and does not leak a secret to a third party, but it does two irreversible things the runbook explicitly sets out to prevent. First, C5's 'ignore-existing at the cycle-directory level' rule, held against a Windows shipper that runs until C9, guarantees that one to three cycles reach the VPS shipper with no ship.json or a stale one and are re-uploaded to the same S3 key as a second, byte-different object version with a contradicting recorded SHA-256 - the outcome the runbook itself names as the worst possible - and the C9 gate as written is either unsatisfiable or passes while it happens. Second, the same rule strands root.txt.ots and witness.json for every overlap cycle, so the VPS re-stamps roots that already carry Bitcoin attestations and permanently records Wayback captures as lost that Windows had verified. Both are fixed by making the copy per-file rather than per-directory and by re-syncing ship.json after the Windows shipper is stopped, not before. Separately, the ledger will wedge at C10 because nothing refreshes the C1 clone and publish.py never fetches, and the runbook pre-diagnoses that failure as a deploy-key problem. Two smaller items: heartbeats.jsonl must be concatenated rather than copied, since the VPS watcher has been appending since C3; and the heredoc instruction leaves the Space-Track password in shell history.

- **BLOCKER.** C5: 'Use --ignore-existing semantics at the cycle-directory level: a cycle directory the VPS already pulled itself must never be overwritten by the Windows copy', combined with C9 'stop, then start' the shipper.
  - Why: The Windows shipper runs from C1 through C9. Every cycle the VPS pulls itself from C3 onward is skipped wholesale by the directory-level rule, so its ship.json never reaches the VPS; and any cycle copied at C5 before Windows shipped it carries a ship.json snapshot saying shipped:null that goes stale minutes later. archive/ship.py:151-154 returns 'not yet shipped' whenever state['shipped'] is falsy, so at C9 the VPS shipper packs and PUTs those cycles to the same key cycles/<sha12>/files.tar (ship.py:188, 203-205). The tar bytes cannot match Windows': the record members are added with tar.add (ship.py:131-134) carrying host uid/gid/mode/mtime, and the files/*.gz blobs themselves differ because poll.py:204 writes each gzip with gzip.open(...,'wb') and no mtime, stamping the local clock into every gzip header. Result: a second object version per key with a contradicting recorded SHA-256, which the runbook itself calls 'the single most damaging thing that can go wrong in the cutover'. The C9 gate does not catch it: cycles pulled only on the VPS have no ship.json at all (gate unsatisfiable, no remediation given), and cycles copied-then-shipped-by-Windows DO carry 'their copied ship.json' so the gate passes while the double ship still happens. Live spool timing makes this near-certain rather than theoretical: the feed rolls about every 8 h (first_seen 04:1x, 12:2x, 20:3x UTC) and Windows ships 45-70 min after finish (cycle_1b3b36972d57 finished 04:59:07Z, uploaded 05:44:52Z; cycle_23a1332e6e3c finished 22:27:35Z, uploaded 23:16:33Z), so C5->C9 spanning even one witness/catalogue/score verification covers one to three shipped cycles. The rollback advice has the same hole in reverse: 'check systemctl --failed on the VPS before re-enabling the Windows Shipper' tells you nothing about which cycles the VPS already uploaded.
  - Evidence: archive/ship.py:151-154 (needs_upload -> 'not yet shipped'); archive/ship.py:131-134 and 203-205 (tar.add metadata, PUT to cycles/<sha12>/files.tar); archive/poll.py:204 (gzip.open with no mtime, host clock in every gzip header); measured on Z:\ephemera\spool: finished_utc vs shipped.uploaded_utc gap of 45-70 min across all 32 shipped cycles.
- **BLOCKER.** C5 warns 'Copy root.txt.ots byte-exact and before the witness unit ever starts: if it is absent, proof_matches() returns False, the cycle is stamped again, and its committed timestamp becomes the migration date' - then issues a copy rule that guarantees exactly that for every overlap cycle.
  - Why: The directory-level ignore-existing rule skips the whole cycle directory for every cycle the VPS pulled itself from C3 onward, so root.txt.ots, root.txt.ots.bak and witness.json are never transferred for those cycles. When the VPS witness starts at C6, archive/witness.py:191-192 sees no proof file and re-stamps root.txt, replacing an original stamp and Bitcoin attestation with the migration date (live example: cycle_1b3b36972d57 witness.json holds stamped_utc 2026-09-08T05:02:06Z and attested block_height 966019 - unrecoverable once overwritten). Independently, with no witness.json the VPS witness treats the cycle as never captured: for a cycle no longer current, archive/witness.py:292-296 sets wayback.skipped = 'cycle superseded before witnessing completed: 1 manifest + 10 sample captures never made', and because line 282 guards on `not wb.get("skipped")` that verdict is sticky forever. Windows had 10 verified samples and a verified manifest capture for those same cycles. The archive permanently publishes a witnessing loss that did not occur. Note the harm comes specifically from the phrase 'at the cycle-directory level': plain rsync --ignore-existing is per-file and would have copied ship.json, root.txt.ots and witness.json into the VPS's existing cycle directory while correctly leaving its own cycle.json alone.
  - Evidence: archive/witness.py:191-192 (stamp when no proof exists); archive/witness.py:282 and 292-296 (sticky wayback.skipped for a superseded cycle); Z:\ephemera\spool\cycle_1b3b36972d57\witness.json (stamped_utc, attested block 966019, 10 samples, manifest verified).
- **SERIOUS.** C10: 'stop the Windows task, then start ephemera-ledger.timer... Verify the commit, the push over the deploy key, the deploy-site workflow going green.' Section 4 attributes any push failure to the missing credential helper.
  - Why: C1 clones the repo; the Windows Ledger keeps committing and pushing 'ledger build' to main every 4 hours until C10. web/publish.py never fetches, pulls or rebases - the only git invocations are show, add, diff, commit and push (web/publish.py:23-24, 29, 77, 78, 84, 94) - so the VPS clone is behind origin/main by every ledger build made between C1 and C10 (the last five commits on main are all 'ledger build'). The first VPS push is rejected non-fast-forward, web/publish.py:95-97 logs 'push failed (will retry on the next run)' and returns 1, and the unit commits locally onto a divergent branch every 4 hours forever - the exact wedge the runbook describes for two publishers, reached with only one. Because section 4 pre-diagnoses push failure as a credential-helper problem, the operator debugs the deploy key. Worse, the C10 safety net is not the net claimed: committed_cycle_count() reads HEAD:web/dist/ledger.json from the stale local HEAD (web/publish.py:29-33), so the '33 cycles or it refuses' guard compares against a stale published count and passes regardless. No step between C1 and C10 refreshes the clone.
  - Evidence: web/publish.py:23-24 and 42-99 contain no fetch/pull/rebase; web/publish.py:29-33 (committed_cycle_count reads local HEAD); web/publish.py:71-75 (shrink guard uses that count); git log on main: b1ea65b, 9e684da, f932cc8, 6fcf2b0, e023d2b all 'ledger build'.
- **SERIOUS.** C4: 'Identical roots is the go signal for everything that follows', treated as sufficient evidence the two spools agree about a shared cycle.
  - Why: The root commits file hashes only, not first_seen_utc. archive/poll.py:294-295 sets first_seen from the local prior record or this run's start time, so the first cycle the VPS pulls carries the VPS's C3 start time, not the time Windows first saw that manifest - and C5's directory-level ignore-existing guarantees the Windows cycle.json is never copied over it. The live cadence (first_seen 04:1x, 12:2x, 20:3x UTC) means starting C3 anywhere in the 00:00-04:16 UTC window puts the same cycle on a different UTC date on the two hosts, roughly 18 percent of start times. Consequences the C4 gate cannot see: archive/witness.py:229-234 buckets cycles into daily roots by first_seen_utc[:10] and archive/witness.py:237 never rebuilds a day that already has root.txt, so the cycle is a leaf in Windows' already-stamped and already-published daily/<D> and again in the VPS's later daily/<D+1>; and web/build.py:204 counts a gap over CADENCE_HOLD_H = 9.0 h (web/build.py:36) as a cadence hold against an 8 h cadence, so an 8 h shift in one first_seen fabricates or hides a published cadence hold. Nothing in C4 through C12 compares first_seen_utc between the hosts.
  - Evidence: archive/poll.py:294-295 (first_seen = prior or this run's started); archive/witness.py:229-234, 237 (daily bucketing by first_seen date, build-once); web/build.py:36 and 204 (CADENCE_HOLD_H = 9.0); measured first_seen values on Z:\ephemera\spool cluster at 04:1x, 12:2x, 20:3x UTC.
- **SERIOUS.** C5 copies daily/ ('complete or not at all'); C6 stops the Windows witness and is explicitly allowed to be timed 'just after a cycle's captures have completed rather than mid-window'.
  - Why: The Windows witness keeps running between C5 and C6, and C6's timing rule can push that gap out by most of an 8 h capture window. archive/witness.py:212-233 builds a daily root for every UTC day strictly before today on every 300 s pass, so a UTC midnight inside the C5->C6 gap means Windows builds, stamps and (via the Windows ledger, still running until C10) publishes daily/<D> after the snapshot was taken. The VPS never receives that directory, and archive/witness.py:237 only skips a day whose root.txt is already present, so the VPS builds daily/<D> from scratch with its own cycle set. Combined with the first_seen skew above, the rebuilt root can differ from the one already stamped and published for that date, with no error anywhere - precisely the 'silent falsification' the runbook warns about for a missing day, arrived at through its own step ordering rather than through a bad copy.
  - Evidence: archive/witness.py:212-233 (daily roots built for every day before today, every pass); archive/witness.py:237 (skip only if root.txt already exists); runbook C6 permits waiting for the end of a capture window before stopping the Windows witness.
- **MINOR.** C5, heartbeats.jsonl: 'copy, then let the VPS watcher append. Do not recreate it empty.'
  - Why: The VPS watcher starts at C3, two steps before the copy, and archive/run_cycle.py:138-140 appends a line to <spool>/heartbeats.jsonl on every tick from that moment. At C5 the copy either overwrites the file, destroying every VPS tick between C3 and C5, or is skipped, in which case none of the Windows history arrives - the instruction's stated order (copy, then append) is not the order the runbook actually executes. web/build.py:170-178 reads that single file as the only source for D18 observed coverage and coverage_24h (web/build.py:181-199) returns None only when the whole history is shorter than 24 h, so a truncated file silently publishes a wrong coverage fraction rather than 'not yet measured'. The correct instruction is to concatenate the two files, not copy one over the other.
  - Evidence: archive/run_cycle.py:138-140 (append to heartbeats.jsonl every tick); web/build.py:170-178 and 181-199 (single-file read, coverage_24h); runbook C3 precedes C5.
- **MINOR.** Section 4: 'Write this file on the VPS with a heredoc, never by pasting from a Windows editor.'
  - Why: A heredoc typed into an interactive login shell writes SPACETRACK_PASS and the AWS values verbatim into the service user's shell history file, where they persist after the cutover and outlive any rotation of personal.env. The runbook is otherwise careful (names only, mode 0600, nothing printed) but gives no `set +o history`, no leading-space HISTCONTROL note, and no instruction to clear history afterwards. Followed literally, the cutover leaves a second plaintext copy of the Space-Track credential on the one host that also holds the AWS key and the GitHub write key.
  - Evidence: Runbook section 4, 'What must exist on the VPS' - heredoc instruction with no shell-history suppression; contrast the file's own 0600/gitignore care for infra/personal.env.

### Lens: Secrets and guards: every credential the runbook moves to the VPS, whether any value can be printed, logged, committed or exposed by the repo being public; whether infra/guard.py, guard.sh, guard_cf.py and guard_cf.sh still refuse correctly on Linux; the scope of the git push credential; and whether .gitignore covers the files the runbook creates.

**Verdict.** Followed literally, yes to both halves of the question. It leaks a secret by way of the scp shortcut offered in section 4, which copies the whole live personal.env and puts the Cloudflare token on the exact host the runbook twice promises will never hold it, and it plants an SSH private key and an AWS credentials file inside the working tree of a public repository with no gitignore rule for either. It does not lose a cycle on my lens. The guards themselves are sound on Linux and I could not break them: infra/guard.py is platform-clean (pathlib, re, os.environ, one STS call), empty allowlist and missing profile and missing file are all refusals, the forbidden list is checked before the allowlist, archive/ship.py:289 lets GuardRefused terminate the process, and even when credentials arrive by environment variable rather than by profile the account is still checked against the allowlist by STS and still refuses. guard.sh and guard_cf.sh need bash and are bash-shebanged, and the one Linux break in guard_cf.sh (the bare `python` at line 44) is correctly identified by runbook 3.2, although its reasoning about where that script runs is wrong and one guard test goes green for the wrong reason without the fix. The push credential choice is right in kind, but the isolation claim built on it is overstated: a write-scoped deploy key can push the four paths that trigger the deploy workflow, including infra/cf_site.py, in which the Cloudflare guard itself lives. Fix the scp sentence, move .aws and .ssh out of the checkout or gitignore them, forbid AWS keys in unit environments, and restate the Cloudflare isolation claim.

- **BLOCKER.** Section 4: "The live file here is LF today, so an scp of it is safe as-is if you prefer that to retyping", set against section 4's "No Cloudflare credential ever reaches the VPS" and section 8's "What deliberately never reaches the VPS: the Cloudflare token."
  - Why: The live infra/personal.env is not the five-name file the runbook's own table describes. It holds eight names, including CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID and EPHEMERA_CF_ACCOUNT_IDS. scp copies the whole file, so taking the offered shortcut puts the Cloudflare token on the VPS and destroys the single security property the runbook advertises most loudly. It also lands on the one host that already holds the AWS and Space-Track credentials and the GitHub write key, and guard.py:24-34 parses all eight names into the shipper process on every pass. The runbook itself computes the blast radius of that dict two paragraphs earlier without noticing that its own scp shortcut is what fills it. Fix: strike the scp sentence. The heredoc is not a stylistic preference, it is the control.
  - Evidence: grep -oE '^[A-Z_]+=' infra/personal.env prints EPHEMERA_AWS_PROFILE, EPHEMERA_AWS_ACCOUNT_IDS, EPHEMERA_AWS_FORBIDDEN_IDS, SPACETRACK_USER, SPACETRACK_PASS, CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, EPHEMERA_CF_ACCOUNT_IDS (names only, no values read). Loaded wholesale by infra/guard.py:24-34, called from archive/ship.py:289.
- **SERIOUS.** Section 4 asserts .gitignore coverage for personal.env ("gitignored by .gitignore (infra/*.env)") and then creates /opt/ephemera/.aws/config and /opt/ephemera/.ssh/id_ed25519 inside the same checkout without checking either.
  - Why: Measured: git check-ignore -v says infra/personal.env is ignored by .gitignore:23, and .aws/config, .aws/credentials and .ssh/id_ed25519 are NOT IGNORED. The runbook therefore puts an SSH private key and an AWS credentials file inside the working tree of a now-public repository with no ignore rule, and it never says to add one. The automated committer cannot take them (web/publish.py:77 and :84-87 both carry a `-- web/dist` pathspec, and the comment at :81-83 says why), so this is not a live leak, but the owner's history already contains one `git add -A` incident and the VPS is the machine where a human will run git by hand. Nothing forces either file into the checkout: unlike personal.env, whose location is pinned by infra/guard.py:16 and :24, both are named by absolute path in the units (AWS_CONFIG_FILE, GIT_SSH_COMMAND -i), so /etc/ephemera/aws-config and /etc/ephemera/ssh/ cost nothing. Otherwise add /.aws/ and /.ssh/ to .gitignore in the same commit as the section 3 edits.
  - Evidence: git check-ignore -v infra/personal.env .aws/config .aws/credentials .ssh/id_ed25519 -> only the first is matched (.gitignore:23:infra/*.env); the other three print NOT IGNORED. Pathspec confinement verified at web/publish.py:77,84-87.
- **SERIOUS.** Section 4: "The credentials themselves may live in that section or in the unit's environment."
  - Why: The two options are not equivalent and one of them defeats the guard's stated design. Measured with botocore 1.43.81: with AWS_PROFILE set to a profile that exists but carries no keys, and AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY in the environment, the credentials actually used come from the environment (resolved method "env"). So guard.py:54's "pinned BEFORE the first API call" pins the profile name only; env keys sign the call and the profile section becomes decorative. The refusal itself still holds, because guard.py:43-52 checks the account STS actually returns, but the runbook is telling the operator to put a long-lived secret access key into a systemd unit environment, which is readable by any local user through `systemctl show -p Environment` (the same command the runbook's own check 9 relies on) and lives in a unit file that is 0644 by default. Say instead: credentials go only in the profile file at 0600, never in Environment= and never in the EnvironmentFile. While there: the survey claim the runbook left unverified is true. With no [profile <name>] section, boto3 raises ProfileNotFound even when env keys are present, so guard.py:56-58 reports "could not establish the AWS identity".
  - Evidence: Offline botocore resolution test (no AWS call), temp AWS_CONFIG_FILE with a bare [profile ephemera] section: case A (section exists, env keys set) -> access_key AKIAENVFAKE, method "env"; case B (section absent, env keys set) -> ProfileNotFound. Guard behaviour at infra/guard.py:43,54,56-58.
- **SERIOUS.** Section 4: "No Cloudflare credential ever reaches the VPS ... That is a real reduction in what one compromised host holds", with the write-scoped ed25519 deploy key presented as the tightly scoped choice.
  - Why: True of the token at rest, false of the capability. The deploy workflow triggers on any push to main touching web/dist/**, infra/cf_site.py, infra/guard_cf.py or the workflow file itself, and the deploy step puts CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID and EPHEMERA_CF_ACCOUNT_IDS into the environment and runs `python infra/cf_site.py deploy` from the tree that push just wrote. A repository deploy key with write access can push any ref, including changes to those exact paths, so the VPS holds a credential that runs chosen code with the Cloudflare token in scope. The guard is no barrier: guard_cf.enforce() is called at infra/cf_site.py:169, inside one of the four files the trigger list lets that same push rewrite. web/publish.py:94 never force-pushes, but the key is not limited to what publish.py does with it. This does not make a PAT better, the key is still the right choice; it means the isolation claim needs restating, and it wants a main ruleset blocking force-push and deletion at minimum. Whether GitHub can path-restrict a deploy key's pushes on this plan is unverified.
  - Evidence: .github/workflows/deploy-site.yml:13-16 (trigger paths include infra/cf_site.py, infra/guard_cf.py and the workflow file), :50-54 (secrets in env, `run: python infra/cf_site.py deploy`); guard call site at infra/cf_site.py:161,166,169; push at web/publish.py:94.
- **SERIOUS.** Section 3.2: "None of these run on the VPS under the recommended deploy path (section 4)."
  - Why: guard_cf.sh does run on the VPS, in the C2 gate. infra/tests/test_guard.py:122-161 stages a copy of infra/ with a fake curl and executes guard_cf.sh under bash, and `make test` is the gate the runbook makes C2. Worse than a wrong aside: measured on a PATH with no `python`, guard_cf.sh:44 prints "python: command not found", the || block at :49-52 fires, and the script exits 1 with "REFUSED - the token cannot see the ephemera.space zone under the allowlisted account". That is character for character what test_cf_guard_refuses_a_token_whose_zone_belongs_to_another_account asserts, so that test passes for entirely the wrong reason on a stock Ubuntu host, green while the zone binding is not being evaluated at all. Only test_cf_guard_passes_and_exports_for_the_allowlisted_account goes red. The python3 fix in 3.2 is correct and lands before C2 if the order is followed, but the justification is wrong and a guard test that stays green while the guard is inoperative is exactly the class this project forbids.
  - Evidence: Ran infra/guard_cf.sh in a sandbox with a fake curl and PATH=/tmp/cfg/bin:/usr/bin:/bin (no python): stderr "guard_cf.sh: line 44: python: command not found" then "guard_cf: REFUSED - the token cannot see the ephemera.space zone under the allowlisted account", exit 1, sentinel not created. Assertions at infra/tests/test_guard.py:156-161; test harness at :122-140.
- **MINOR.** Section 4: "Neither guard has an override flag, environment variable or argument, and infra/tests/test_guard.py greps for one. Nothing here adds one."
  - Why: Two inaccuracies in one sentence, in the paragraph the owner would rely on as the assurance. The grep at infra/tests/test_guard.py:100-104 iterates over ("guard.sh", "guard_cf.sh") only; it never reads guard.py or guard_cf.py, which are the guards the VPS actually runs (archive/ship.py:289, infra/cf_site.py:169). And both Python guards do take arguments that bypass the check outright: guard.py:43 is enforce(env=None, identity=sts_account), so a caller supplies its own allowlist and its own identity function in place of STS, and guard_cf.py:81 is enforce(opener=None), which replaces the zone lookup at :65-78. Production call sites pass nothing, so this is a documentation defect and not a live hole, but the runbook should say the seams exist and that the grep does not cover the Python guards.
  - Evidence: infra/tests/test_guard.py:100-104 (`for name in ("guard.sh", "guard_cf.sh")`); infra/guard.py:43; infra/guard_cf.py:81,65-78; call sites archive/ship.py:289 and infra/cf_site.py:169.
- **MINOR.** Section 4, blast radius: "infra/guard.sh:18 is looser: it sources the whole file into the shell, so the aws CLI it spawns inherits everything."
  - Why: Measured false. The live personal.env contains no `export` lines, so `. personal.env` sets shell variables that are not in the environment and a child process sees them unset. guard.sh exports exactly one name, AWS_PROFILE at :30 (guard_cf.sh:33 exports the Cloudflare pair, deliberately). The aws CLI at guard.sh:32 therefore inherits AWS_PROFILE and nothing else. The recommendation not to put Cloudflare on the VPS is right, but this supporting fact is not, and correcting it matters because the same reasoning is what the runbook uses to rank the two guards by risk.
  - Evidence: grep -c '^[[:space:]]*export' infra/personal.env -> 0. Sandbox: a file with SPACETRACK_PASS="..." sourced under `set -euo pipefail`, then `bash -c 'echo ${SPACETRACK_PASS:-UNSET}'` -> "child sees: [UNSET]", and `env | grep -c SPACETRACK` -> 0. Export sites: infra/guard.sh:30, infra/guard_cf.sh:33.
- **MINOR.** Section 3.12 asserts the units carry no proxy or CA override, citing archive/poll.py:264-269 and archive/run_cycle.py:167-168; check 9 verifies it with `systemctl show -p Environment ephemera-watcher`.
  - Why: The enumeration misses the session that matters and the check misses the unit that matters. There are four default-trust_env sessions, not two: archive/poll.py:264, archive/run_cycle.py:167, archive/witness.py:372 and archive/gp_pull.py:131. gp_pull's is the only one that ever transmits a password (archive/gp_pull.py:55 posts identity and password to /ajaxauth/login), and it is neither cited in 3.12 nor covered by check 9, which names only ephemera-watcher. A REQUESTS_CA_BUNDLE or HTTPS_PROXY inherited by ephemera-catalogue is a Space-Track credential interception, which is a different order of consequence from a re-routed manifest GET. Separately the check is too narrow to do its job: `systemctl show -p Environment` reports Environment= directives only, not EnvironmentFile contents nor manager-level DefaultEnvironment, so it cannot see a variable set the way the runbook sets its own. Read the environment of the running process, and run the check against all six units.
  - Evidence: grep -n 'Session()' over archive/ -> poll.py:264, run_cycle.py:167, gp_pull.py:131, witness.py:372. Credential transmission at archive/gp_pull.py:55; session construction and User-Agent at :131-133.
- **MINOR.** Section 4: "Write this file on the VPS with a heredoc, never by pasting from a Windows editor."
  - Why: Right about CRLF, silent about history. A heredoc typed at an interactive bash prompt is stored in the shell's history as a single multi-line entry and written to ~/.bash_history when that shell exits, so SPACETRACK_PASS and the AWS values end up in a 0600 plaintext file that nothing in the runbook ever cleans up, and that survives on the host with the disk images and snapshots the provider takes. Cheap fix, say it in the runbook: `set +o history` first, or HISTCONTROL=ignorespace with a leading space, or `install -m 600 /dev/null infra/personal.env` then edit it in place. Asserted from shell behaviour, not measured on the VPS.
  - Evidence: Runbook section 4, "Write this file on the VPS with a heredoc"; no history handling anywhere in sections 4 or C1. CR sensitivity claim it makes is itself correct: infra/guard.sh:18 sources the file, infra/guard.py:28 uses splitlines().

### Lens: Linux portability: every claim that code works unchanged on Linux, checked against the code  -  atomic writes/os.replace, locking, signals, the ETag cache, path separators, manifest filename case, the native OTS client and the interface witness.py expects, Skyfield/sgp4 data files, timezone and locale.

**Verdict.** On the Linux-portability lens the runbook is substantially sound: it would not lose a cycle and it would not leak a secret. It does contain one edit that, applied literally, silently stops the site publisher (defect 1). Everything else on the brief checked out against the code. Atomic writes are fine  -  every temp file is created in the same directory as its target (archive/poll.py:139-148, :203-206; archive/ship.py:129-141), so `os.replace` is a real atomic rename on POSIX and is strictly better behaved than on Windows. There is no file locking anywhere and the runbook says so; its separate-spools rule for the overlapping pollers is the right conclusion. Signal handling is correctly characterised: `poll._install_sigterm_as_interrupt` (archive/poll.py:228-235) is installed only inside `poll.main`, so `KillSignal=SIGINT` plus `SuccessExitStatus=4` is the right choice for the watcher and witness, and the exit-4 return paths are real (archive/run_cycle.py:178, :186, :193; archive/witness.py:404). The ETag cache is correctly split: the watcher's manifest ETag is in-memory only (`state` at archive/run_cycle.py:169, used at :93-101), which is a genuine reason not to use a timer; the per-cycle `etag_cache.json` is on disk and resume works. No hard-coded path separator, drive letter or `os.sep` exists anywhere in archive/, score/, web/ or infra/ except the harmless `SYSTEMROOT` in infra/tests/test_guard_cf.py:130  -  the one Windows path that reaches a public artefact is web/build.py:153, which is defect 1. The case-insensitive manifest dedup and the colon/backslash rejection (archive/poll.py:89-129) are platform-independent code, so keeping them does preserve cross-poller root identity as claimed. The OTS interface is not a risk: `ots stamp` / `ots upgrade` / `ots info` with the `BitcoinBlockHeaderAttestation(N)` regex (archive/witness.py:46, :91-101) is the same command set the Docker path runs against the same pip package in python:3.12-slim, and it demonstrably works  -  31 of 32 cycles in the committed web/dist/ledger.json carry an `attested_block`. Skyfield and sgp4 need no data files at all, which the runbook never had to claim: `score/visibility.py:59-63` calls `load.timescale()`, whose `builtin=True` default reads a bundled `iers.npz` (skyfield/iokit.py:332, :350-358); there is no `.bsp`, no `finals2000A.all` download and no write into the working directory. Timezone is clean  -  every datetime in the tree is `datetime.now(timezone.utc)` or an explicit `strptime(...).replace(tzinfo=timezone.utc)`; `grep` finds no `utcnow`, no `localtime`, no `fromtimestamp`, no `%Z`. Locale is a non-issue and the runbook slightly over-states it: the only locale-sensitive format in the tree is `%B` at web/pages.py:75, and CPython never calls `setlocale(LC_TIME, \"\")`, so month names are English whatever `LANG` says; likewise the un-encoded `read_text`/`text=True` calls are safe on Ubuntu 24.04 because PEP 538 coerces a bare C locale to C.UTF-8. Setting `LANG=C.UTF-8` in every unit is still the right move, just for a smaller reason than the runbook gives.

- **SERIOUS.** Section 3.9: change `web/build.py:153` from `str(pack)` to `pack.name`, described as 'Recommended, not blocking', cosmetic, and justified by '`web/pages.py` never reads the field, only `pack_bytes` (checked: `pack_mb` is the only thing threaded through)'. Section 7 check 7 then tells the operator to confirm 'the pack paths no longer reading `Z:\` if you took edit 3.9'.
  - Why: The claim about pages.py is true but the field is not only read by pages.py. `web/build.py` reads its own output: `ledger["visibility"]["reports"]` IS `load_scores()` (build.py:256), and build.py:311-315 does `head = headline_report(...)`, `pack = head["pack"]`, `shutil.copyfile(pack, published)`. With `pack.name` that becomes `shutil.copyfile('globe_<sha12>.json', web/dist/globe/pack.json)`, resolved against the process CWD. Under the runbook's own unit (`WorkingDirectory=/opt/ephemera`, systemd 5.6) the file is not there, so it raises FileNotFoundError. Nothing in `build.main` (web/build.py:290-341) catches it and nothing in `web/publish.py:57` catches it, so the ledger unit dies with a traceback on every 4-hourly run: no build, no lint, no commit, no push, and the published site freezes silently at whatever it last held. This is exactly CLAUDE.md rule 10  -  a description of what the author meant, not of what the code does  -  in a runbook that raises rule 10 against score/run.py. It is also the only place in the whole tree where a Windows path leaks into a public artefact (28 of 28 reports in the committed web/dist/ledger.json carry `Z:\ephemera\spool\score\globe_*.json`), so the fix is worth doing  -  but it needs build.py:312 changed too, e.g. keep the absolute path in a non-published local and publish only the name.
  - Evidence: web/build.py:153 (`"pack": str(pack) if pack.exists() else None`), web/build.py:256 (`"visibility": {"reports": data["scores"], ...}`), web/build.py:311-315 (`head = headline_report(ledger["visibility"]["reports"])`, `pack = head["pack"]`, `shutil.copyfile(pack, published)`), web/publish.py:57 (`rc = build.main([...])`, no try/except). Reproduced: `python -c "...pathlib.Path(head['pack']).name ...; shutil.copyfile(pack,'web/dist/globe/pack.json')"` -> `build.py:315 -> FileNotFoundError: [Errno 2] No such file or directory: 'globe_0e700520864b.json'`
- **MINOR.** Section 5.3, `ephemera-ship.service`: `Type=oneshot` plus `SuccessExitStatus=143`, with the stated purpose '`143` is there so a stop during an upload does not read as a defect.' Section 7 check 1 then makes '`systemctl --failed` empty' a gate before the Windows machine is switched off.
  - Why: systemd parses a numeric word in `SuccessExitStatus=` as an *exit status*, not a signal; a signal has to be written by name (`SIGTERM`). A process killed by SIGTERM is reported as CLD_KILLED with status SIGTERM, never as exit code 143, and for `Type=oneshot` the four signals SIGHUP/SIGINT/SIGTERM/SIGPIPE are explicitly NOT in the implicit clean-exit set that other types get. So `SuccessExitStatus=143` covers nothing that can actually happen here: ship.py only ever returns 0, 1 or 4 (archive/ship.py:310, :314), and a `systemctl stop` or a `TimeoutStartSec=2h` expiry during a 9.3 GB upload still leaves the unit failed. The correct spelling is `SuccessExitStatus=SIGTERM`. Consequence is observability only, but it is observability the runbook itself makes a pre-shutdown gate.
  - Evidence: systemd.service(5) SuccessExitStatus=: 'Exit status definitions can be numeric termination statuses, termination status names, or termination signal names' and 'for types other than Type=oneshot, one of the signals SIGHUP, SIGINT, SIGTERM, or SIGPIPE' (manpages.debian.org/unstable/systemd/systemd.service.5.en.html). Exit codes ship.py can return: archive/ship.py:310 `return 0 if ok else 1`, archive/ship.py:314 `return poll.EXIT_INTERRUPTED` (=4, archive/poll.py:61).
- **MINOR.** Section 9, 'Line drift': 'A few survey citations were off by one to three lines (`web/tests/test_build.py` CHROME is at 21 to 24, not 22 to 25 ...). Every file:line in this runbook I read directly.'
  - Why: The survey was right and the runbook's correction is wrong. Line 21 is `REPO = Path(__file__).resolve().parents[2]`. The CHROME assignment starts on line 22 and closes on line 25. This matters only because it appears in the one section whose purpose is to certify the runbook's citations against the surveys'  -  a reader who trusts that certification will not re-check the rest, and section 3.10 (add `/usr/bin/chromium` and `/snap/bin/chromium`) is an edit someone will apply to those exact lines on the VPS.
  - Evidence: web/tests/test_build.py:21-25  -  21 `REPO = Path(__file__).resolve().parents[2]`; 22 `CHROME = next((c for c in (`; 23-24 the two `C:/Program Files` paths; 25 `"/usr/bin/google-chrome", "/usr/bin/chromium-browser") if Path(c).exists()), None)`.

