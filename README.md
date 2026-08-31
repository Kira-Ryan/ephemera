# Ephemera

**The largest constellation in history publishes where it is going, with uncertainty, every eight
hours — and the files vanish at the next cycle. Ephemera keeps them, and publishes every day how well
the public catalogue can actually see.**

SpaceX serves a 72-hour ephemeris with full position and velocity covariance for every Starlink
satellite at `api.starlink.com/public-files/ephemerides/`, refreshed every eight hours. Space-Track
stopped mirroring those files on 28 July 2025. The server keeps only the current set; a superseded
file is gone at the next cycle. No continuous public archive exists; the only public sample is one
week (25 Nov–1 Dec 2024) inside the SpaceTrack-TimeSeries dataset (arXiv 2506.13034).

Ephemera archives every file under a witnessed hash chain, and computes from the archive a daily,
browser-checkable scoreboard: public-catalogue error against operator truth by element age, altitude
shell and geomagnetic activity; the fraction of the constellation the public catalogue can see; the
self-consistency of the published covariance by lead time; and an honestly defined census of
trajectory changes. Kelso keeps the elements. McDowell keeps the objects. This keeps the record of
how well the world can see.

> **Status: day one (30 Aug 2026).** The poller and its watcher exist and are tested against a
> local fake feed (20 caller-level tests; 13 named mutations each turn a test red). One home poller
> on a Cape Town residential link has been capturing continuously since 15:32 UTC on 30 Aug 2026;
> nothing before that is archived. Not yet in place: a second poller, automated OpenTimestamps and
> Wayback witnessing (stamping is proven manually on Linux), cold storage. Progress is tracked in
> `PLAN.md`. Read `DOCS/concept.md` first, then `DOCS/decisions.md`, then `probes/README.md`, then
> `archive/README.md`.

## The one number

**11,099** files per cycle, **2,041,931** bytes each, three cycles a day, and no continuous public
archive. Measured 30 August 2026 from one manifest and one file; the canonical measurements table,
with dates and methods, is `probes/p1_cycle_pull/README.md` — re-measure before quoting.

## What this is not

- **Not an independent check of SpaceX's FCC manoeuvre count.** The FCC figure counts "events
  resulting in an action" under SpaceX's private screening; public predictions carry an unlabelled
  stream in which station-keeping outnumbers avoidance many times over. Ephemera publishes three
  differently defined series side by side and never a ratio. See D04.
- **Not "covariance realism".** Comparing an earlier prediction with a later one measures
  self-consistency, contaminated by re-plans. It is named that way everywhere. See D05.
- **Not an audit of anyone.** The neutral quantity is *catalogue visibility* — how much of the
  constellation's motion the public catalogue sees — and that is the only headline.

## Repository (planned)

| Path | What |
|---|---|
| `DOCS/` | Concept, decision log, claims register — read before building |
| `probes/` | Cheap experiments that retire the big unknowns before anything is built on them |
| `archive/` | Pollers, hashing, daily Merkle root, OpenTimestamps and Wayback witnessing |
| `score/` | Clean-room SGP4 scoring against operator truth; covariance self-consistency; census |
| `web/` | The static site (Latent Sky pattern: build-time computation, files behind a CDN) |
| `data/` | Derived, compacted products only; raw files live on cold object storage, never here |
| `licences/` | Per-source licence and terms audit |

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
