# score/ - the comparisons

No I/O against live feeds. Inputs are the spool (archived cycles and catalogue snapshots); outputs
are derived JSON under `data/score/`. Every report carries its as-of time, its inputs (cycle id and
Merkle root, snapshot id and hash) and a `method` string that says what was computed.

## visibility.py - catalogue visibility, v0

For each file in a cycle, the public element set with the same NORAD id (from a `gp_pull`
snapshot) is propagated with Skyfield (python-sgp4 underneath; TEME to GCRS by Skyfield, taken as
J2000, probe P6) to the file's own record epochs every `--eval-step-min` minutes (default 360) and
differenced against the file position. Rows carry distance, radial / in-track / cross-track
components in the operator's frame, geocentric altitude and signed element age. The summary bins
rows by element age and by altitude shell: median, 90th percentile, and the share within 1, 10 and
30 km.

Both inputs are predictions. The operator's file contains planned trajectory changes the public
set cannot know about, so the tail of every distribution is dominated by satellites that are being
raised, lowered or moved. Element age and time-into-file are correlated in a single run (later
record epochs are also older relative to the set), so v0 age bins are not yet a clean age effect;
separating the two needs several snapshots per cycle, which the 2-hourly catalogue task now
provides.

```
python score/visibility.py --spool Z:/ephemera/spool --cycle cycle_f5112bb77a2a --gp latest --out data/score
```

Exit 1 if any file was unreadable (each is logged with the parser's message and listed in the
report); files without a public set or with a decayed set are counted and listed, not scored.

### First full run, 2 Sep 2026 (single cycle, single snapshot; a smoke test, not a published figure)

Cycle `f5112bb77a2a` (11,092 files, start 09:10 UTC) against snapshot `20260902T200733Z_0821a18806eb`
(Space-Track gp, fetched 20:07 UTC). 11,091 scored, 143,226 rows at 6-hour spacing, one set marked
decayed (NORAD 46173, still in the operator feed), none missing, no propagation failures, no
unreadable files. Wall time 10 minutes on the home PC, single process.

| Element age | rows | median km | p90 km | within 1 / 10 / 30 km |
|---|---|---|---|---|
| set newer than epoch | 3,846 | 1.12 | 11.6 | 0.46 / 0.89 / 0.93 |
| 0-6 h | 6,151 | 1.06 | 5.6 | 0.48 / 0.94 / 0.98 |
| 6-12 h | 8,405 | 2.01 | 10.0 | 0.28 / 0.90 / 0.97 |
| 12-24 h | 20,983 | 4.25 | 19.4 | 0.15 / 0.79 / 0.92 |
| 24-48 h | 44,076 | 10.6 | 70.5 | 0.08 / 0.49 / 0.81 |
| 48-72 h | 43,546 | 25.4 | 218.2 | 0.04 / 0.35 / 0.54 |
| over 72 h | 16,219 | 27.9 | 134.4 | 0.03 / 0.33 / 0.51 |

| Shell | rows | median km | p90 km | within 1 / 10 / 30 km |
|---|---|---|---|---|
| under 400 km | 14,152 | 42.9 | 602.3 | 0.07 / 0.33 / 0.46 |
| 400-500 km | 116,938 | 8.7 | 63.3 | 0.11 / 0.53 / 0.75 |
| 500-600 km | 12,136 | 3.6 | 214.7 | 0.21 / 0.70 / 0.83 |

Read with the caveats above: the under-400 km shell is where satellites are raised and lowered
under thrust, and the age bins mix age with prediction horizon. What the run establishes is that
the pipeline closes end to end on real data with no unreadable files and no propagation failures,
and that the magnitudes are the expected ones (about a kilometre at fresh age, tens of kilometres
within two days).
