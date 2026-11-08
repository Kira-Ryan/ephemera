# P10 - Do Wayback copies exist for the cycles the witness recorded as never captured?

**Question.** From 13 to 25 Sep 2026 Save Page Now answered HTTP 500 to the witness, which recorded no
copy, and the archive page printed "manifest NEVER CAPTURED" on those rows. A check of the live site on
5 Nov found captures in the Wayback index under the same URLs. Do they exist for every such cycle, and
do they hold the bytes this archive recorded?

**Kills the plan if** copies exist and do not match: that would mean the archive's record and an
independent copy disagree. None did.

**Result, 8 Nov 2026.** Of the 37 cycles recorded as never captured:

| | Manifests | Samples |
|---|---|---|
| Copy found and its SHA-256 equals the archive's record | **33** | **315** of the 330 under those 33 manifests |
| Listed in the index, but the copy answers 404 | 0 | 4 |
| Not in the index | 4 | 11 under those manifests, and all 40 under the other four |
| Copy found and its digest differs | **0** | **0** |

- 28 cycles have the manifest and all ten samples. Those rows no longer carry a defect, which took the
  site's count from 45 to 17 on the ledger of 8 Nov.
- 5 cycles have the manifest and some samples: c504091dd2b0 and c9f83fc4657b and 444b844a9ffc 9 of 10,
  d6763ae68580 8 of 10, e7c0515a4f47 0 of 10. They keep a defect and print their losses.
- 4 cycles have nothing in the index: 513b92c4683e, f855253d23d5, 24c4d4760724, e41647a0de27.
- Each manifest capture is dated 0.71 to 1.55 h after the cycle was first seen, and none after the next
  cycle was first seen, so the capture times are as good as ones the witness had recorded itself.

The matched copies are in `archive/late_copies.json`, which the build reads (D16 amendment of 8 Nov). The
per-cycle results are in `evidence/results.json`. The check was run from the owner's home address at about
one request every two seconds, 18:26 to 19:05 UTC.

## A second result: verified copies that come and go

The check of 5 Nov found 18 rows marked "manifest ok" whose link answered 404. All 18 were re-fetched on
8 Nov (`recheck_dead_links.py`, `evidence/recheck_dead_links.json`): **15 served the right bytes again**.
Still 404: cdc930461493 (21 Oct), b10586a473bf (31 Oct), 21c30f522c4f (3 Nov).

The same run shows it moving the other way. Of the cycles not yet in the index on 8 Nov, the newest copies
are served, and copies from 3 to 5 Nov that served on 5 Nov (b3f1f050ca40, 08eed5393d9a, 13f2c4b7bfbd,
6df7d4ca15e9) answered 404 on 8 Nov.

The pattern fits the Wayback Machine serving a new capture for a few days, then not until its index
catches up. That is an inference from one re-test: nothing here proves those copies are safe, and
cdc930461493 has been missing for 18 days. The site says so on the archive page. The witness only fetches
a copy once it is verified, so the ledger cannot see any of this.

## Method

`check_captures.py` takes the ledger, one saved CDX prefix query over the folder, and the rollback spool's
`cycle.json` files for the per-file digests. For each cycle whose record says no capture was made, it takes
the earliest status-200 capture at or after first seen, fetches the `id_` copy, removes any gzip, and
compares the SHA-256 of the raw bytes with the digest recorded when the file was pulled. It only reads.

```
python probes/p10_outage_captures/check_captures.py --ledger ledger.json --cdx cdx.json \
    --spool <spool> --out evidence/results.json --late archive/late_copies.json
```

## Limits

- It looked only at those 37 cycles and only at their ten sampled files, as the witness would have.
- "Not in the index" is as of 8 Nov 2026, and the second result above shows the index moves.
- Three other kinds of defect were not touched: cycles superseded before witnessing, copies that held
  another cycle's manifest, and samples lost one at a time.
