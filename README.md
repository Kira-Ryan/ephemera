# Ephemera

**Every eight hours, SpaceX publishes where each Starlink satellite is going, with its
uncertainty — the only public feed of its kind. Each set is replaced by the next, and no
continuous public archive of them exists. Ephemera keeps the history, and publishes every day how
well the public catalogue can actually see.**

SpaceX serves a 72-hour ephemeris with full position and velocity covariance for every Starlink
satellite at `api.starlink.com/public-files/ephemerides/`, refreshed every eight hours. Space-Track
stopped mirroring those files on 28 July 2025, and the server keeps only the current set. No
continuous public archive exists; the only public sample is one week (25 Nov–1 Dec 2024) inside
the SpaceTrack-TimeSeries dataset (arXiv 2506.13034). This project exists because SpaceX publishes
the feed openly.

Ephemera archives every file under a witnessed hash chain, and computes from the archive a daily,
browser-checkable scoreboard: public-catalogue error against operator truth by element age, altitude
shell and geomagnetic activity; the fraction of the constellation the public catalogue can see; the
self-consistency of the published covariance by lead time; and an honestly defined census of
trajectory changes. Kelso keeps the elements. McDowell keeps the objects. This keeps the record of
how well the world can see.

> **Status: day two (31 Aug 2026).** One home poller (Cape Town, residential link) has captured
> every eight-hour cycle since 30 Aug 2026 15:32 UTC; witnessing is automated and live (each
> cycle's Merkle root OpenTimestamps-stamped, the current cycle's manifest plus ten root-chosen
> files captured into the Wayback Machine and re-hashed against the record); the placeholder site
> is up at https://ephemera.space with push-to-deploy. 62 caller-level tests; every named mutation
> turns a test red. Not yet in place: a second poller, cold storage, the ledger and scoreboard.
> Progress is tracked in `PLAN.md`. Read `DOCS/concept.md` first, then `DOCS/decisions.md`, then
> `probes/README.md`, then `archive/README.md`.

## The one number

Around **9,000** files per cycle (8,568–17,861 across the first four captured cycles), about
**2 MB** each, three cycles a day, and no continuous public archive. Measured 30–31 August 2026;
the canonical measurements table, with dates and methods, is `probes/p1_cycle_pull/README.md` —
re-measure before quoting.

## What this is not

- **Not an independent check of SpaceX's FCC manoeuvre count.** The FCC figure counts "events
  resulting in an action" under SpaceX's private screening; public predictions carry an unlabelled
  stream in which station-keeping outnumbers avoidance many times over. Ephemera publishes three
  differently defined series side by side and never a ratio. See D04.
- **Not "covariance realism".** Comparing an earlier prediction with a later one measures
  self-consistency, contaminated by re-plans. It is named that way everywhere. See D05.
- **Not an audit of anyone.** The neutral quantity is *catalogue visibility* — how much of the
  constellation's motion the public catalogue sees — and that is the only headline.

## Repository

| Path | What |
|---|---|
| `DOCS/` | Concept, decision log, claims register — read before building |
| `probes/` | Cheap experiments that retire the big unknowns before anything is built on them |
| `archive/` | Poller, watcher and witness: hashing, Merkle roots, OpenTimestamps, Wayback |
| `infra/` | Account guards (AWS and Cloudflare) and guarded deploy scripts |
| `tools/` | The claims lint that enforces the register's wording in `make test` |
| `web/` | The static site (build-time computation only, no server) |
| `score/` | *Planned:* clean-room SGP4 scoring against operator truth; self-consistency; census |
| `data/` | *Planned:* derived products only; raw files live on cold object storage, never here |
| `licences/` | *Planned:* per-source licence and terms audit |

## Clean-room rule

Everything in this repository is re-implemented from open libraries (python-sgp4 / Skyfield /
Orekit; `hashlib` Merkle trees) on personal infrastructure with an account guard. No code from any
employer or client engagement is used, adapted, or consulted. The rule is recorded as D02 and
restated in `CLAUDE.md` because coding agents build most of this.

## Licence

MIT for this repository's code. Derived datasets are intended for CC BY 4.0 (D06, proposed). The
raw SpaceX files are to be mirrored as published, under terms SpaceX has not stated; the position
taken is D06 and the status of the request to SpaceX (drafted, not yet sent as of 30 Aug 2026) is
in `DOCS/claims-register.md`. Space-Track general perturbations will be redistributed only under
Space-Track's blanket approval for basic SSA data, with citation.
