# P1 — Full-cycle pull: timing, parallelism, conditional requests

**Question.** How long does one full cycle pull take, at what parallelism, and does the server support
conditional requests so a poller can resume without re-downloading?

## Canonical measurements (cite this table; nothing else in the repository restates these numbers)

| Quantity | Value | Measured | Method |
|---|---|---|---|
| Files per cycle | 11,099 | 30 Aug 2026 | line count of one `MANIFEST.txt` |
| Bytes per file, raw | 2,041,931 | 30 Aug 2026 | one file, `Content-Length` and body |
| Bytes per file, gzipped | ~821,000 | 30 Aug 2026 | the same file, `gzip -6` (the poller's level) |
| Per cycle, raw / gzipped | ~22.7 GB / ~9.1 GB | derived | 11,099 × the per-file figures |
| Per day / per month, gzipped | ~27 GB / ~0.82 TB | derived | 3 cycles/day, 30 days |
| Seconds per file, one connection | 4.9 s (4,892 ms) | 30 Aug 2026 | `curl`, Cape Town residential link |
| Full cycle at 16 connections | 45–116 min | 30 Aug 2026 | 116 from `curl` slices; 45–80 from `poll.py` on 50 and 30 files, same link |
| Conditional requests | `ETag`, `Last-Modified`, HTTP 304 | 30 Aug 2026 | GET with `If-None-Match` |
| `HEAD` | 404 | 30 Aug 2026 | use GET for headers |
| Files per cycle, second sample | **17,861** (11,027 satellites; 6,834 with two files) | 30 Aug 2026 15:28 UTC | manifest sha `72bcd7796b49…`, fetched by the poller |
| Sustained full-cycle pull from a datacentre IP | **24 min 3 s, 11,132 files, 0 failed, 22.6 GB raw** (7.7 files/s, 15.7 MB/s), peak RSS 578 MB, 179% of 2 vCPU | 12 Sep 2026 | `poll.py --workers 16` on an AWS t3.small in eu-west-1; probe P8, `probes/p8_vps_bootstrap/README.md` |

**The file count is not constant.** The morning manifest listed 11,099 files; the 15:28 UTC manifest
listed 17,861 for 11,027 distinct NORAD ids — 6,834 satellites appeared twice, with two different
epoch fields in the name (e.g. `…_2420111_…_1472346720_…` and `…_2420923_…_1472376240_…`). Every
volume figure above is therefore a range until the steady state is established.

**Update, 31 Aug 2026 — first four captured cycles (home watcher, complete, with roots):**

| Cycle (manifest sha12) | First seen UTC | Files | Raw GB | Wall time |
|---|---|---|---|---|
| `72bcd7796b49` | 30 Aug 13:32 | 17,861 | 36.2 | 71 min |
| `92e6892c0f3e` | 30 Aug 20:02 | 9,111 | 18.5 | 39 min |
| `5e4faf0f4e4e` | 31 Aug 04:09 | 9,353 | 19.0 | 42 min |
| `1d424255c9ae` | 31 Aug 11:44 | 8,568 | 17.4 | 42 min |

The cadence is ~8 h with no missed manifest (gaps 6.5 / 8.1 / 7.6 h). The steady state so far is
~9,000 files ≈ 18 GB raw ≈ 7.4 GB gzipped per cycle ≈ **0.67 TB/month gzipped** — below both P4
pricing volumes; the 17,861-file manifest was the outlier. The overlap question is closed below
(P1b): consecutive manifests share no file names at all.

**Method.** 30 Aug 2026, from a Cape Town residential connection (public IP deliberately not
recorded). Fetched `MANIFEST.txt`, then pulled disjoint 16-file slices with `curl` under
`xargs -P` at 1, 8, 16 and 32 connections; captured GET response headers for one file; issued a second
GET with `If-None-Match`.

**Measured.**

| Item | Value |
|---|---|
| Files in manifest | 11,099 |
| Bytes per file (one file, raw / gzip -6) | 2,041,931 / ~821,000 |
| Lines per file | 17,287 (4 header lines + 4,321 records × 4 lines; 60 s step; 72 h) |
| Response headers | `ETag`, `Last-Modified`, `Accept-Ranges: bytes`, `Cache-Control: max-age=60, must-revalidate` |
| `If-None-Match` with the served ETag | **HTTP 304**, 0 bytes — conditional requests work |
| `HEAD` | 404 — use GET for headers |
| 1 connection | 4,892 ms per file |
| 8 connections | 841 ms per file effective |
| 16 connections | **629 ms per file effective** (~3.3 MB/s) |
| 32 connections | 887 ms per file effective — no gain; the link saturates near 4.5 MB/s |

**Projection.** 11,099 × 629 ms / 60,000 ≈ **116 minutes per cycle at 16 connections from this
link**, against an 8-hour cycle. The "kills the plan if > 6 h" criterion is not met even from a home
connection; a well-peered VPS will be several times faster. Raw per cycle ≈ 22.7 GB; ≈ 68 GB/day.

**Consequences for the poller.**
- 16 workers; more buys nothing on a residential link and risks looking abusive.
- Store the ETag per file; retries and resumes use `If-None-Match`.
- The manifest changes every cycle, so a cycle is identified by the SHA-256 of `MANIFEST.txt`.
- `Cache-Control: max-age=60` means an edge cache may serve a file up to a minute stale relative to
  the origin; irrelevant for archival, but record `Last-Modified` per file.

**Open.** Whether the server rate-limits a sustained 11,099-file pull (only 80 files pulled here).
The first full-cycle run answers it.

**Update, 30 Aug 2026 (poller, after sizing the connection pool to the worker count).** `poll.py`
pulled 50 files in 22 s and 30 files in 7 s at 16 workers from the same link (about 4.6 and 8.7 MB/s;
the second run had a warmer path). Projection for 11,099 files: **45–80 minutes per cycle**, i.e.
under 20% of the 8-hour window. Re-running the same cycle answered every file with HTTP 304 in ~1 s
and produced an identical Merkle root.

## P1b closed, 31 Aug 2026 — consecutive manifests share nothing

Measured over the first four complete cycles: **zero repeated file names between consecutive
manifests** (0 of ~9,000–17,861 in every pair). The epoch fields inside each file name change every
cycle, so every cycle is 100% fresh bytes. Consequences: content-addressed deduplication in the
storage layer (the open question in D15) buys nothing and is dropped; the volume arithmetic is
simply files × size per cycle with no overlap discount; and the steady state stands at ~9,000
files ≈ 18 GB raw ≈ 7.4 GB gzipped per cycle (~0.67 TB/month gzipped). Still open from P1: whether
the per-cycle file count tracks manoeuvre activity, and the sustained-pull behaviour from a
datacentre IP.

## Cadence anomaly, 31 Aug 2026 evening

The manifest first seen at 11:44 UTC was still being served, byte-identical (sha `1d424255c9ae...`,
8,568 lines), at 21:17 UTC - a 9.6-hour hold against the ~8-hour cadence observed until then, with
the watcher healthy (fresh heartbeat, 304s every two minutes) and an independent fetch agreeing.
First observed deviation from the nominal cadence; recorded here because cadence is an assumption
downstream (witnessing windows, ledger coverage), not a guarantee. The count of such holds becomes
a truth-health statistic once the ledger exists.

## Uplink, 2 Sep 2026 - the home link's upload side

First real shipment of a cycle tar (9.26 GB) from the Cape Town residential link to S3 eu-west-1:
multipart parts of 512 MB, 4 concurrent, measured over a 4-minute window at **4.2 MB/s
(34 Mbit/s)**, so one cycle uploads in about 37 minutes. Packing the tar from the SATA disk ran at
about 17 MB/s (9 minutes per cycle). Steady-state need is 3 cycles/day, i.e. about 2.3 hours of
upload a day against 24 available; the home link keeps pace with margin, and the 11-cycle backlog
drains in roughly 10 hours at one cycle per half-hour shipper run.
