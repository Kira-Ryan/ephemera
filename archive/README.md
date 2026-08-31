# archive/ - pollers, hashing, witnessing

`poll.py` pulls one cycle of the public Starlink ephemerides into a spool directory. `run_cycle.py`
is the watcher that keeps a spool current with the feed; it is the only long-running process in
this layer.

```
spool/
  heartbeat.json                   written by run_cycle.py every tick (gitignored)
  cycle_<manifest sha256[:12]>/    one directory per manifest (D10, D11); no wall-clock in the name
    MANIFEST.txt                   the manifest exactly as served
    files/<name>.gz                each file gzipped (level 6); the recorded hash is of the RAW bytes
    etag_cache.json                per-file ETag / Last-Modified / sha256 for resume via If-None-Match
    cycle.json                     the cycle record (schema 2): status, per-file sha256 / bytes /
                                   headers, failures, manifest anomalies, Merkle root
    root.txt                       the Merkle root, 64 lowercase hex + LF (D12); only when complete
  partial/cycle_<sha12>/           --limit test slices; never get a root
```

Run one cycle: `python archive/poll.py --spool /path/to/spool --workers 16 --contact you@example.org`.
Watch the feed: `python archive/run_cycle.py --spool /path/to/spool --contact you@example.org`
(`--once` for a single tick; `--interval` seconds between manifest checks, default 120). A contact
address is required, also via `EPHEMERA_CONTACT`; it is sent in the User-Agent.

Exit codes (`poll.py`): 0 complete · 2 gaps (record kept, `merkle_root: null`, no `root.txt`) ·
3 partial (`--limit`) · 4 interrupted (SIGINT/SIGTERM; record written with what was recorded) ·
5 refused before any download (no contact, spool volume below `--min-free-gb`, manifest empty,
unreachable or undecodable). An unexpected error inside the download loop (disk full, say) stops
the workers, writes the record with `status: error` and the exception text, and re-raises.
Re-running the same manifest resumes via conditional requests, and a re-run that ends without a
root removes any `root.txt` left by an earlier complete run of that cycle. The watcher checks the
current manifest's record on every tick - including ticks where the manifest answered 304 - and
retries any cycle whose record is not `complete`; a manifest that has rolled is never retried, so a
gap stays a gap and is visible. A pull that ends interrupted stops the watcher (exit 4).

Record fields worth knowing: `first_seen_utc` (first run on this manifest, preserved across
resumes); `manifest_anomalies` (one entry per offending manifest LINE: names that are not a single
path component, contain characters outside `[A-Za-z0-9._-]`, or duplicate an earlier line -
compared case-insensitively - are counted as gaps and never touch the filesystem, so
`files_listed == files_recorded + files_failed + files_not_attempted` always holds);
`failures` (download failures by name); `manifest_changed_during_pull` (the manifest was re-fetched
after the last download and differed - a complete set of recorded files still gets a root, per
D09; this field explains 404 gaps near a rollover); `files_not_attempted`.

Merkle construction (D09): SHA-256 leaves in manifest order; adjacent pairs hashed as
SHA-256(left || right); an odd trailing node is paired with a copy of itself. Never change this
silently - it alters every subsequent root. Any change is a decision entry and a new record schema.

Witnessing (P2): stamp `root.txt` with OpenTimestamps on a Linux host (Docker locally, `make stamp`)
and submit `MANIFEST.txt` plus sampled files to the Wayback Machine each cycle. Not yet automated
(PLAN.md item 7).

Measured behaviour of the feed: the canonical table is `probes/p1_cycle_pull/README.md`; numbers
are cited from there, not restated here.
