# Probes — week one

Cheap experiments that retire the big unknowns before anything is built on them. Each probe gets its
own folder with a `README.md` recording the question, the method, the measured result and the date.
A probe that fails is a finding, not a failure.

| # | Question | Kills the plan if… | Method |
|---|---|---|---|
| P1 | How long does one full cycle pull take, and at what parallelism, from a well-peered VPS? | > 6 h per cycle, or the server rate-limits or blocks | Pull `MANIFEST.txt`, then all files with 1 / 8 / 16 / 32 connections; record wall time, bytes, HTTP errors, and whether `ETag` / `If-None-Match` is honoured |
| P2 | Does third-party witnessing work end to end? | OpenTimestamps cannot be verified independently, or Wayback Save-Page-Now refuses the manifest | Hash one cycle, build a Merkle root, stamp it with OpenTimestamps, submit the manifest and five files to the Wayback Machine, then verify both from a clean machine |
| P3 | What did the six-digit catalogue rollover break? | Nothing — then bulletin #1 has no content | Script one test per library (python-sgp4, Skyfield, Orekit, GPredict, KeepTrack, astropy where relevant) against a 100000+ object in OMM and Alpha-5 forms; record pass / fail / silent-drop |
| P4 | What does the archive cost? | > USD 60/month at month 12 | Price 0.85 TB/month gzipped growth on Cloudflare R2, Backblaze B2 and a Hetzner storage box, including egress for the derived-product build |
| P5 | What are SpaceX's terms? | Written refusal | Email the space-safety onboarding address asking for mirroring terms; record the request date and any answer in `DOCS/claims-register.md` |
| P6 | Is `ephemeris_source:blend` the only manoeuvre-content marker? | Manoeuvre content is unlabelled in every file | Diff headers and record structure across a full cycle and across two consecutive cycles for the same satellite |
| P7 | Can the June 2026 degradation be reproduced from what still exists? | No source retains the period | Query CelesTrak history statistics and any SupGP archive Kelso will share; if reproducible, it becomes the scoreboard's first replay |
| P8 | Can the whole pipeline run from a datacentre IP? | The feed refuses a hosting address, a cycle projects past 6 h, S3 under 3 MB/s, or Wayback throttles the second capture | On a throwaway Linux host: reachability of every endpoint, the manifest and its 304, the pull rate with the real poller at 16 and 32 connections, a 2 GiB S3 PUT, the native OTS client, three Wayback captures at the witness's gap |

Order: P5 is an email and goes out first; P1 and P2 run the same day, because the archive starts the
moment they pass (D03); P3 is bulletin #1; P4, P6 and P7 fill the rest of the week.
