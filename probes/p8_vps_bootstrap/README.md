# P8 - Can Ephemera run from a datacentre IP?

**Question.** Every cycle so far was pulled from one residential connection in Cape Town. Before
the whole pipeline moves to a Linux host (PLAN item 6b, D14), does the operator's feed serve a
datacentre address at all, and at what rate; do the other five endpoints answer; does the
OpenTimestamps client run natively so Docker can go; and does the Wayback Machine throttle a new
IP at the witness's capture gap?

**Kills the plan if** the feed refuses a hosting address, or a full cycle projects to more than
6 hours (the P1 line), or S3 uploads run under 3 MB/s, or Wayback returns 429 on the second capture.

**Result, 12 Sep 2026: none of the kill conditions triggered.** The feed serves a datacentre IP at
two to four times the home rate with zero failures, everything is reachable including CelesTrak
(which the home IP cannot reach, P3), the native OTS client stamps in 1.5 s, and S3 takes a
2 GiB object at 55.7 MB/s.

## Method

A throwaway host, created and destroyed by `ec2_probe_host.sh` (account guard first, SSH from the
owner's address only, self-terminating after two hours): AWS EC2 `t3.small` in eu-west-1, Ubuntu
24.04.4 LTS, Python 3.12.3, 2 vCPU, 2 GB, public address 34.242.139.192 (AS16509). It held no AWS
credential; the S3 test used a one-hour presigned PUT minted on the owner's machine under the
guard, and the object was deleted afterwards, every version. `probe.sh` ran the checks in the
order below and wrote `evidence/results.txt` and `evidence/probe.log`. The pull rate is measured
with the production poller (`archive/poll.py --limit`), not with curl, so the figure is the real
code path: 16 threads, conditional requests, gzip on write.

This is a probe on AWS's address space, not on the provider that will host the pipeline. D14
keeps continuous compute off AWS; the point here was to answer the kill questions before any
money was spent, and an AWS range is the most commonly blocked hosting range there is, so a pass
here is the harder pass. The Hetzner-specific rate is measured again on the real host (see next
steps); this probe cost under USD 0.10.

## Canonical measurements

| Quantity | Value | Method |
|---|---|---|
| Feed reachability | HTTP 200, TLS in 34 ms, served by 151.101.129.143 | `curl` to `MANIFEST.txt` |
| Manifest | 820,999 bytes, 11,131 lines, sha `34e224670e92`, `ETag` present | `curl -D` |
| Conditional request | **304** on `If-None-Match` | second `curl` with the ETag |
| 200 files at 16 connections | **6.51 files/s, 13.3 MB/s raw, 0 failed**, 30.7 s | `poll.py --limit 200 --workers 16` |
| 400 files at 32 connections | **8.23 files/s, 16.8 MB/s raw, 0 failed**, 48.6 s | `poll.py --limit 400 --workers 32` |
| Projected full cycle, 11,134 files | **22 to 28 min** (home: 45 to 116 min, P1) | files/s above |
| Sustained full-cycle pull, 11,132 files | **24 min 3 s, 0 failed, 22.6 GB raw** (7.7 files/s, 15.7 MB/s), root written | `poll.py --workers 16`, no `--limit` |
| Same manifest pulled at home, 4.4 h earlier | **identical Merkle root** `3a1dc167948cd8c8...` after 4 h 23 min with a 54-gap retry | `Z:\ephemera\spool\cycle_34e224670e92` |
| Poller peak memory, full cycle | 578 MB RSS, 179% of 2 vCPU (gzip on write) | GNU `time -v` |
| S3 eu-west-1, 2 GiB single PUT | **55.7 MB/s**, 38.5 s, HTTP 200 (a 9.3 GB tar: about 3 min) | `curl -T` over a presigned URL |
| Native OpenTimestamps | `opentimestamps-client` v0.7.2 installs; `ots stamp` **1.5 s**, 735-byte proof | pip in the venv |
| Wayback at a 12 s gap | 3 captures: one HTTP 523 from Wayback's side, two OK; **no 429** | `witness.capture()`, the production function |
| Space-Track | 200 to the front page; **login not attempted** | two clients on one account is an owner decision |
| CelesTrak | HTTP 200 in 0.54 s (unreachable from the home IP, P3) | `curl` |
| OTS calendars alice, bob, finney | all 200 | `curl` |
| S3, STS, GitHub, Cloudflare API | 307, 302, 200, 400: all reachable | `curl` |
| IPv6 | no default route on the host | `ip -6 route` |
| `requirements.txt` on Ubuntu 24.04 / Python 3.12.3 | installs in 15.9 s, every wheel present | `pip install -r` |

Notes on the rate figures. The two slices overlap (the first 200 manifest entries are inside the
first 400) and went to separate spools, so both are fresh downloads, but the second may have been
flattered by CDN warming from the first; the sustained pull is the number to cite, and it held the
slice rate for the whole cycle with no collapse after the first few hundred files, which was the
failure the runbook warned a slice could not show. The one WARNING per slice log is the poller's own
"partial slice recorded, no Merkle root by design", which is `--limit` doing what it says.

The root cross-check is the strongest result here. The manifest with sha `34e224670e92` was pulled
by the home poller from 12:18 UTC, which took 4 h 23 min because `api.starlink.com` reset 54
connections that afternoon and the watcher retried the gapped cycle, and by the probe host from
16:50 UTC in 24 minutes. Both produced `3a1dc167948cd8c8d478f1e96fa117da95c51308017a233e03070248ef47ad68`.
Two pollers on two continents, one identity (D10, the manifest sha), one root: that is the
property the migration's cutover rests on, and it is now observed rather than argued.

The Wayback 523 was returned by the Wayback Machine itself (Cloudflare "origin unreachable" from
web.archive.org), on the first capture only, and the two captures that followed at 12 s spacing
both succeeded with `id_` copies fetched and re-hashed. It is a transient of the service, not a
rate limit, and the witness records exactly this kind of failure per sample and moves on.

## What this settles

- The operator serves a hosting address, at full rate, for a whole cycle, with no 403 or 429.
  The poller can leave the home machine. The single biggest unknown in the migration is closed.
- A second poller reproduces the first one's root from the same manifest, so both can run
  through the cutover and the archive never stops (runbook section 6).
- Docker leaves the project. On Linux the OTS client is a pip install and stamps directly, which
  is the dependency that failed on the home machine on 9 Sep after a Windows update.
- The S3 leg is not the bottleneck anywhere: shipping a cycle takes minutes, not most of an hour.
- CelesTrak is reachable from a datacentre, which unblocks P3 and the SupGP feed (globe ideas 5
  and 7) for free once the host exists.

## What it does not settle

- Nothing about Hetzner, OVH or netcup specifically. The rate must be re-measured on the chosen
  host on day one; the migration runbook makes that its first gate.
- Space-Track from a second IP on one account.
- Behaviour over weeks: whether 27.8 GB a day from one hosting address draws an abuse complaint or
  a quiet throttle. Only the real host will show that, which is why the home poller stays up
  through the cutover.

## Next steps

1. Owner opens the Hetzner Cloud account (or OVH or netcup; D14, non-AWS) and creates the host to
   the runbook's spec: 4 vCPU, 8 GB, about 320 GB of disk, EU location, Ubuntu 24.04.
2. Day one on that host: run `probe.sh` again, then the sustained pull, and record both in this
   file under a second dated heading.
3. Then the runbook's cutover, both pollers running until the host has caught its own cycles.

## Evidence

`evidence/results.txt` is the key=value summary, `evidence/probe.log` the full transcript,
`evidence/pull_w16_n200.log` and `evidence/pull_w32_n400.log` the poller's own logs for the two
slices, `evidence/full_pull.log` the poller log and GNU time summary of the sustained pull,
`evidence/full_root.txt` its root, and `evidence/full_cycle.json.gz` its complete record with every
file's digest, from which the root can be rebuilt (D09).
`probe.sh` is the script; `ec2_probe_host.sh` creates and destroys the throwaway host.
