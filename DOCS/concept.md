# Ephemera — concept

*Written 30 August 2026, from a fourteen-agent problem search (seven research lenses with live
evidence, three strategists, hostile red-team review of each, a completeness critic). This document
records what survived the red team, not what the strategists first proposed.*

## The problem

- SpaceX publishes, for every Starlink satellite, a 72-hour ephemeris with full 6×6 covariance at
  `api.starlink.com/public-files/ephemerides/` (Modified ITC format, 60-second steps, a `MANIFEST.txt`
  listing the current set), refreshed every eight hours. Measured 30 Aug 2026: 11,099 files,
  2,041,931 bytes each, ~821,000 bytes gzipped (`gzip -6`; the canonical table is
  `probes/p1_cycle_pull/README.md`).
- Space-Track stopped hosting these files on 28 July 2025. The server serves only the current set.
  The only public historical sample is one week (25 Nov–1 Dec 2024) inside the SpaceTrack-TimeSeries
  dataset (arXiv 2506.13034, CC BY-NC-SA). T.S. Kelso fits every file each cycle for CelesTrak SupGP
  and likely holds the only multi-year private archive; he publishes no archive and no statistics.
- The public general-perturbations catalogue (18 SDS via Space-Track, mirrored by CelesTrak) is what
  SOCRATES, every open tracker and the promised TraCSS public products rely on. From 2 June 2026 it
  degraded for weeks: mean element age 2.49 days; 4,366 of 10,684 Starlink satellites more than 30 km
  from CelesTrak's operator-derived SupGP. The public evidence is a LinkedIn post.
- TraCSS (US civil space traffic coordination) has 70 pilot operators and 10 national accounts but no
  declared operational date because of budget uncertainty (Via Satellite, 26 Aug 2026); its public
  data release is "later in 2026". The UK is a national account.
- On 11 July 2026 the catalogue number reached 100000. The legacy TLE format cannot carry new
  objects; nobody has measured what broke downstream.

Nobody continuously measures, in public, how far the public catalogue drifts from operator truth, or
whether the covariance every collision probability depends on is self-consistent. Academic groups
publish one-month snapshots (arXiv 2605.19850; 2510.11242; 2603.25835). Vendors compute it and sell
it. The Office of Space Commerce validates internally. The operator is the party being measured.

## The product: one archive, four layers

### 1. The witnessed archive

Two geographically separate pollers pull every file each cycle with 16+ parallel connections (one
file took 4.9 s from Cape Town on one connection; sequential is ~15 h per 8 h cycle). Each file is
SHA-256 hashed; per-cycle and daily Merkle roots are anchored with OpenTimestamps; the manifest and a
sample of files are submitted to the Wayback Machine each cycle so a third party can prove the inputs
existed without trusting the operator of this project. Raw gzipped files go to cold object storage
(~27 GB/day, ~0.82 TB/month). Compacted derived products (subsampled states and covariance summaries,
Parquet/zstd) go to Zenodo under the 50 GB per-record limit with DOIs. Poller uptime is itself
published in the ledger, so a gap is visible rather than silent. A SpaceX cut-off makes the archive
more valuable, not less; the product degrades to catalogue-only metrics.

### 2. The visibility scoreboard

Every Starlink public element set (CelesTrak OMM, six-digit safe; Space-Track history under this
project's own account) is propagated with clean-room SGP4 and scored against the operator trajectory
at common epochs in the radial / along-track / cross-track frame. Published daily:

- public-orbit error versus element age, by altitude shell and Kp band — the one-month Jankovic
  study (arXiv 2605.19850) made continuous and permanent;
- the **catalogue visibility** fraction: share of the constellation whose public orbit lies within
  X km of operator truth (X published, several thresholds);
- a degradation detector that would flag a 2 June 2026 event within hours;
- catalogue-health covariates as by-products: element age, lost element sets, six-digit coverage.

### 3. Covariance self-consistency and the census

Consecutive files overlap by ~64 hours. The earlier prediction is compared with the later trajectory,
normalised by the earlier covariance: a chi-square-by-lead-time scoreboard, by shell and Kp. It is
called *self-consistency*, never realism — it is prediction-versus-later-prediction, contaminated by
re-plans and orbit-determination updates. Genuine realism needs independent truth (laser-ranging
predictions, GNSS-tracked satellites via SupGP) and is a later, separately labelled module.

The census counts trajectory changes in the operator's own predictions with a low-thrust-aware
detector (Starlink burns are Hall-thruster arcs over many minutes, not impulses), publishes the
detection floor, separates *plan changes* (divergence between consecutive files) from *executed
changes* (confirmed by the next file's back-fit), and labels a change "avoidance-consistent" only
when a public conjunction screen shows a close approach in the window. Against the FCC figure, three
differently defined series are shown side by side — in-file burns, plan-change events, SpaceX's
declared "events resulting in an action" — with the definitional caveat on the same line and
explicitly no ratio.

### 4. Multi-operator truth

CelesTrak SupGP (OneWeb, Planet, Iridium, GPS, Galileo) and the declared GPS/Galileo manoeuvre
notices (NANU/NAGU) add operator-derived truth for other constellations by month three, so this is
never a single-operator scorecard. The GNSS tier is a handful of declared events a year — case
studies, not a dashboard.

## Sequence

| When | Deliverable |
|---|---|
| Week 1 | Archive running (two pollers, hashes, OpenTimestamps, cold storage). Email SpaceX space-safety onboarding about mirroring terms. Check the SpaceOps 2027 abstract deadline on STAR. |
| Week 2 | **Bulletin #1:** scripted survey of what the six-digit rollover broke across python-sgp4, Skyfield, Orekit, GPredict, KeepTrack. Sent to Kelso and McDowell before publication. |
| Weeks 3–6 | Visibility scoreboard live as a static site with the claims register. |
| Weeks 7–12 | Covariance self-consistency, three-definition census, SupGP operators. First monthly bulletin with Zenodo DOI. arXiv preprint by mid-November. |
| Oct–Nov 2026 | 500-word abstract to the 13th UT Austin / IAA Space Traffic Conference (Feb 2027). |
| Dec 2026–Jan 2027 | Comparison note within a week of the TraCSS public data release. Reconciliation note on the ~1 Jan 2027 FCC filing: rates on a partial window, three series. |
| Months 4–6 | Phase-two modules on the same archive: reentry prediction scoreboard; post-mission-disposal compliance ledger; Kp-stratified drag module; GEO relocation ledger from public elements. |
| Feb–Mar 2027 | IAC 2027 Poznań abstract; AMOS 2027 abstract (Conjunction/RPO). JSSE or ASR submission in Q1. |

## Allies, in order

1. **T.S. Kelso** — before anything is public. He consumes the same files for SupGP and could publish
   a census in a weekend. The archive and ledger are infrastructure he lacks in public; propose a
   co-authored dataset paper with his backfill.
2. **Matt Hejduk / Lauri Newman (NASA CARA)** — covariance is their stated open concern.
3. **Jonathan McDowell** — relocating to the UK, wants to do more documentation; the catalogue-health
   layer feeds his identity and deorbit work.
4. **Hugh Lewis (Birmingham)** — currently produces the quoted manoeuvre figure by hand from FCC
   filings; reviewer on the avoidance-consistent proxy, not a competitor.
5. **UCL SSA group** — presented an on-orbit reference network for TraCSS ephemeris quality at AMOS
   2025; the UK institutional collaborator.

## What the red team killed

- Pitching it as a check of the 207,152 figure (category mismatch; a TLE-based Arizona study already
  found ~20% of the declared rate).
- Retrospective validation on the SpaceTrack-TimeSeries archive (its ephemeris portion is seven days).
- "Anyone can re-fetch the inputs" (false after eight hours without the archive and witnessing).
- "~15 GB/month" (it is ~2 TB/month raw, ~0.82 TB/month gzipped).
- "Covariance realism" (self-consistency), and "every manoeuvre in the catalogue" (unvalidated noise
  outside operator-derived truth).
- Reusing employer or client code (clean-room only — D02).
- A catalogue-wide 30,000-object detector, an operator transparency index, or an 18 SDS audit in v1
  (adversaries before allies).

## Rejected alternatives (for the record)

A live thermospheric density scoreboard (truth engine published twice in 2026; licence problems with
NRLMSIS 2; institutional intent at CCMC). Cislunar products (unoccupied and timely, but inside the
current employer's product line — build with them or later). An open ground-station scheduling
benchmark (depends on employer scheduler code; academic audience). An agentic MCP layer as the
headline (wrapper risk; the pattern is the employer's NASA platform). A thin, provenance-signed MCP
over this project's own ledger is a month-four addition, not the product.
