# The globe: ten ideas for what the world sees

Recorded 2 September 2026 from a conversation between the owner and the coding agent. Status:
accepted as the working vision by the owner ("we will work through them"), including the
new-feed ideas 3, 5, 6, 7 and 9 ("and we can do 3 5 6 7 and 9"). This is a vision
document, not a decision; anything here that changes an accepted decision goes through
`decisions.md` first.

## Ground rules that every idea inherits

- **Static and serverless (D08).** Cesium runs entirely in the visitor's browser. Everything it
  draws comes from small derived files that the existing build publishes with the site. No
  runtime inference, no API, no database.
- **Keyless.** Cesium's default imagery and terrain need a token from their hosted service. We do
  not use them. Imagery is self-hosted (Cesium's bundled Natural Earth II) or a public tile
  service with terms that allow it (NASA GIBS is the candidate; audited in `licences/` first).
- **Clean room (D02).** The owner's earlier globe and loader work in other repositories is not
  read or adapted. The mathematics those systems used (SGP4, TEME to ECEF, ground tracks, look
  angles, time scales) is standard and lives in the libraries this project may use: python-sgp4,
  Skyfield, satellite.js and Cesium's own transforms. Anything else is re-derived here from
  textbooks and specifications, with a probe and a test.
- **Claims discipline.** Labels, legends and tooltips are user-visible text and are checked
  against `claims-register.md` like any page. Never "realism" for the overlap comparison (D05);
  never one ratio against the FCC count (D04); every figure carries its as-of time and method.
- **A new feed is a new licence audit and a new probe.** Each outside data source gets an entry
  in `licences/` and a probe under `probes/` before anything from it is drawn.
- **The globe is the front door, not the science.** Nothing is drawn that the scoring layer or
  the archive cannot back with a number and a date. A picture without a measurement behind it is
  the failure mode the concept warns about.

## The ten

### 1. The Ghost Shadow
**What you see.** Every Starlink satellite drawn twice: solid where SpaceX's published file says
it is, translucent where the public catalogue puts it, with a tether between them coloured by
distance. A time slider runs across the 72 hours of the cycle; the ghosts drift as the public
elements age and snap back when Space-Track publishes new ones. A visibility gauge summarises the
whole constellation at the chosen instant.
**Data.** Held now: the operator ephemerides (archive) and the public catalogue snapshots
(`spool/gp`). Needs: the scoring layer (`score/`), which is the same comparison as the scoreboard.
**Browser.** The catalogue is propagated client-side with satellite.js from the snapshot's element
sets. The operator side comes from a per-cycle pack of sampled positions, a few megabytes.
**Status.** First to build. This is the scoreboard rendered in 3D.

### 2. Manoeuvre flares
**What you see.** Every bend in an operator trajectory (a burn) lights as a flare on the globe.
Across a month the constellation breathes: collision-avoidance clusters, launch batches climbing
to their shell, deorbit spirals. The three census series of the concept are three toggles, shown
side by side, never one number.
**Data.** Held now: the archive. Needs: the manoeuvre census in `score/` (concept layer 5).
**Status.** After 1.

### 3. The storm bulge
**What you see.** Space weather live: Kp, solar wind, F10.7 from NOAA's Space Weather Prediction
Center. When a geomagnetic storm hits, the low shells show drag pulling them down and the
visibility score decays with it. The June 2026 catalogue degradation as a replay.
**Data.** NOAA SWPC public JSON feeds (US government work, public domain; audit anyway). Needs: a
small archived feed of the indices with its own record, and the scoreboard binned by Kp (already
in the concept).
**Status.** New feed. Licence audit and probe first.

### 4. The witnessed time machine
**What you see.** Scrub back through the archive. Every frame carries its cycle id, Merkle root,
OpenTimestamps state and Bitcoin block, and its Wayback captures. The globe as a provenance viewer:
this is what was published at that instant, and here is how to check it.
**Data.** Held now: cycle records, roots, witness state, daily roots.
**Status.** Cheap once 1 exists; the frame metadata is already on the status page.

### 5. The whole sky
**What you see.** The full public catalogue, roughly thirty thousand objects including debris,
coloured by owner state and object type. Starlink shells as rings; OneWeb, Kuiper and the Chinese
constellations beside them. A slider for "who is up there, by country, over time" from launch
dates.
**Data.** Space-Track GP for the full catalogue (redistribution only under their blanket approval
for basic SSA data, with citation; recorded in the terms audit). CelesTrak for the operator-supplied
element sets of the other constellations (concept layer 4).
**Status.** New query, same feed; the redistribution wording must be settled before the pack is
published.

### 6. Conjunction theatre
**What you see.** The week's closest approaches, drawn as both objects, the miss distance and a
countdown. When one of the pair is Starlink, the ghost from idea 1 answers the sharpest question:
did the public data show a manoeuvre coming, or not.
**Data.** CelesTrak SOCRATES (public; terms audited first). Ties to the operator ephemerides we
hold.
**Status.** After 1 and 5.

### 7. Re-entry watch
**What you see.** Upcoming uncontrolled re-entries with the ground-track band and an uncertainty
window that narrows as the hour nears. On the Starlink side, satellites that vanish from the
manifests are deorbits we can count from our own archive.
**Data.** Space-Track decay and TIP messages (same account, same terms); manifests held now.
**Status.** New query; the manifest-vanish count is a derived statistic we can compute today.

### 8. Overhead now
**What you see.** Pick a city. Which satellites are above it this minute, the next passes, and how
far off the public catalogue would have placed each one. Runs entirely in the visitor's browser,
no data leaves it.
**Data.** The same packs as 1; look angles computed client-side.
**Status.** A view on 1, small.

### 9. Earth events
**What you see.** Ephemera in the wide sense: every transient public event, timestamped and
witnessed the same way the ephemerides are. Earthquakes (USGS GeoJSON), active fires (NASA FIRMS),
disasters (GDACS), hurricane tracks (NHC), launches with pad locations and countdowns (Launch
Library 2). Each is a layer on the same globe with its own archive record and root.
**Data.** Each a separate public feed; each needs its own licence audit, probe, archive record and
witness before it is drawn. Aircraft and ship positions are noted as candidates whose terms are
more restrictive and are not assumed.
**Status.** The long tail. One feed at a time, in the order the licences allow.

### 10. The witness wall
**What you see.** The archive drawn as itself: cycles as tiles, Bitcoin blocks as beads on a
timeline, Wayback captures, gaps in red. A "verify me" box where a stranger pastes a file hash and
the browser walks the Merkle path for that cycle and reports whether it reaches the published root.
**Data.** Held now: manifests and roots. Needs: per-cycle leaf lists published with the site (a
few hundred kilobytes each) and a browser re-implementation of the D09 construction, tested
against `archive/verify.py`.
**Status.** Independent of the scoring layer; can be built any time.

## Order of work

1. The scoring core in `score/`: propagate the public element sets with SGP4 and compare against
   the operator files at shared epochs; per-satellite distance, binned by element age, altitude
   and Kp. This is the concept's layer 3 and it is what every globe idea draws.
2. A per-cycle globe pack, a few megabytes, built by the existing ledger task and published with
   the site: sampled operator positions, the matching element sets, the cycle's witness metadata.
3. `web/globe/`: the Cesium page. Idea 1 first, then 4, 8 and 10 from data already held. Then
   2 when the census exists. Then the new feeds (3, 5, 6, 7, 9), each behind its own audit and
   probe.

## Tracking

| # | Idea | Depends on | Status |
|---|---|---|---|
| 1 | Ghost Shadow | score/ v0, globe pack | not started |
| 2 | Manoeuvre flares | census in score/ | not started |
| 3 | Storm bulge | SWPC feed audit + probe | not started |
| 4 | Witnessed time machine | 1 | not started |
| 5 | Whole sky | full-catalogue query, redistribution wording | not started |
| 6 | Conjunction theatre | SOCRATES audit + probe, 1, 5 | not started |
| 7 | Re-entry watch | decay/TIP query; manifest-vanish statistic | not started |
| 8 | Overhead now | 1 | not started |
| 9 | Earth events | one audit + probe per feed | not started |
| 10 | Witness wall | per-cycle leaf lists, browser Merkle check | not started |
