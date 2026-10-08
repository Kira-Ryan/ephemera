# Ephemera

**About every eight hours, SpaceX posts a new public manifest of files saying where each Starlink
satellite will be for the next two to three days, with its uncertainty. When the next manifest
lands, that set is gone, and no continuous public archive of those sets exists. Ephemera keeps the
history, and publishes every day how well the public catalogue can actually see.**

The files SpaceX's public manifest lists at `api.starlink.com/public-files/ephemerides/` give 48 to
72 hours of position and velocity with full covariance at 60-second steps, about three times a day.
Space-Track stopped mirroring those files on 28 July 2025, and the server keeps only the current
set. No continuous public archive of them exists; the only public sample is one week (25 Nov to
1 Dec 2024) inside the SpaceTrack-TimeSeries dataset (arXiv 2506.13034). This project exists because
SpaceX publishes the feed openly.

Ephemera archives every file each manifest lists under a witnessed hash chain, and computes from the
archive a daily, browser-checkable scoreboard: the distance between the public catalogue's
prediction and the operator's own, by element age and altitude shell, and the fraction of the
constellation the public catalogue can see. Planned, not built: the self-consistency of the
published covariance by lead time, and an honestly defined census of trajectory changes. Kelso keeps
the elements. McDowell keeps the objects. This keeps the record of how well the world can see.

> **Status (8 Oct 2026).** The whole pipeline runs on one rented server in the EU, since 3 Oct 2026:
> it pulls every manifest, roots each one in a Merkle tree stamped with OpenTimestamps, captures the
> manifest and ten root-chosen files into the Wayback Machine and re-hashes the copies, ships the raw
> files to cold storage, scores each cycle against the public catalogue, and publishes the site every
> four hours. Not yet in place: a second poller, the self-consistency series, the census, a restore
> drill. Progress is tracked in `PLAN.md`. Read `DOCS/concept.md` first, then `DOCS/decisions.md`,
> then `probes/README.md`, then `archive/README.md`.

## The one number

A median of about **11,130** files per manifest (8,568 to 18,812 over the 120 manifests to 8 Oct
2026, from the published ledger), about **2 MB** each, three manifests a day, and no continuous public
archive. The first measurements were taken 30 and 31 August 2026;
the canonical measurements table, with dates and methods, is `probes/p1_cycle_pull/README.md`;
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
| `score/` | Clean-room SGP4 scoring against the operator's published trajectories; self-consistency and the census are planned |
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
taken is D06 and the status of the request to SpaceX (sent 31 Aug 2026; no answer by 30 Sep 2026,
the thirty days D06 allowed, so the files are held as published and come down on request) is in
`DOCS/claims-register.md`. Space-Track general perturbations will be redistributed only under
Space-Track's blanket approval for basic SSA data, with citation.
