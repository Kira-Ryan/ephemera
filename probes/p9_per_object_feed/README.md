# P9 - What does the ephemerides folder serve besides the manifest?

**Question.** Dr T.S. Kelso's reply of 7 Oct 2026 said the manifest lists a different set from the
one CelesTrak uses, which requests each satellite's file by name. Does that set exist; what is in
it; how big is it; how often does a file change; and how does it relate to the manifest set this
archive keeps?

**Kills the plan if** the archive's premise fails: that what the site says it keeps is what it
keeps. It does not: the archive keeps exactly what each manifest lists. The finding made two public
statements wrong and opens a decision for the owner (below).

**Result, 8 Oct 2026.** The folder serves a second public set: a file per satellite at
`<folder>/<OBJECT_NAME>.txt` (for example `STARLINK-1008.txt`), listed in no manifest, with a new
version about every two hours per satellite, staggered across the constellation.

| Quantity | Per-object set | Manifest set (archived) |
|---|---|---|
| How a file is found | by name; there is no listing (the folder root and an unknown name both answer 404) | listed in `MANIFEST.txt` |
| Names tried, names served | 27 of 27 (4 in the scout, 24 spread through the 3 Oct manifest, one overlapping) | 11,151 files in the 3 Oct manifest |
| Format | CCSDS OCM 3.0, `ORIGINATOR = SPACEX/USA`, with `CREATION_DATE`, `MESSAGE_ID` and `TIME_LAST_OBSERVATION_GPS_NS` | MEME text: `created:`, `ephemeris_start/stop`, `ephemeris_source:blend`, `UVW` |
| Horizon and step | exactly 7 days from `START_TIME` to `STOP_TIME`, 60 s, 10,081 rows | 48 to 72 hours, 60 s |
| Frame | trajectory and covariance `ITRF2000` (Earth-fixed), covariance as a lower triangle | see P6 |
| Manoeuvres | `MAN` blocks with `MAN_BASIS = PLANNED`, `NTW_ROTATING`, continuous acceleration (start, duration, acceleration); 50 of 52 versions carried at least one, most two or three | none in the file |
| Size | about 5.03 MB raw, served gzip-encoded at about 1.92 MB | about 2.0 MB raw |
| A full set | about 56 GB raw and 21 GB on the wire (11,151 names times the sampled size; not fetched) | 22.6 GB raw a manifest |
| Change | a new version about every two hours per satellite (below) | a new manifest about every 8 hours |
| `HEAD` | answers 404 even for a file `GET` serves | not used |

## Method

From the owner's residential connection, because SSH to the host was blocked that afternoon (the
host itself kept publishing). The project's contact address was in the User-Agent throughout.

- Scout, 2026-10-08T16:19:23Z to 2026-10-08T16:21:55Z: 106 requests at 0.5 s spacing. `GET` on the
  name in Dr Kelso's reply and on three names taken from the manifest's own file names
  (`MEME_<catalogue number>_<OBJECT_NAME>_...`); one unknown name; the folder root; `HEAD` on 100
  names spread through the manifest.
- Cadence, 2026-10-08T16:25:21Z to 2026-10-08T18:21:45Z (116 minutes, 24 polls): 27 names, one
  conditional `GET` each every five minutes (`If-None-Match`, `If-Modified-Since`), so an unchanged
  file cost a 304. 648 requests: 596 answered 304 and 52 answered 200 with a first or new copy. A
  version is identified by its `CREATION_DATE`.

## Cadence

25 of 27 objects published a new version inside the 116-minute window. Between consecutive versions
of one object: 25 intervals, shortest 38.7 minutes, median 120.9, longest 200.2. If each object's
versions were evenly spaced, the fraction that changed would put the interval near 126 minutes. Both
readings say about two hours per object. The 52 versions' creation times run continuously from 14:10
to 18:11 UTC with no batching (the longest gap between any two is 23.8 minutes), so the folder changes
continuously: if the sample is typical, about 90 files a minute across 11,151 names. `CREATION_DATE` is
a median of 7.9 minutes after the file's own `EPOCH_TZERO` (longest 35.6). In 24 of 25 cases a new
version's manoeuvre rows differed from the previous version's. A `PLANNED` manoeuvre can be listed
after its start time: one file created at 15:14 UTC listed a burn that began at 05:45 UTC that day.

## What it does not show

- Whether every satellite has a per-object file: 27 of 27 names tried did; no one has fetched all
  11,151.
- Whether the two sets agree for the same satellite at the same instant. The manifest files at hand
  were five days older than the per-object files, so no common epoch was compared; that the files
  differ byte for byte says nothing.
- Whether a `PLANNED` manoeuvre was flown as planned.
- The frame beyond the header: `ITRF2000` is what the files say; it was not checked against anything.
- How the server behaves under sustained polling of the whole set.

## What changed

The site and the records were corrected the same day: the colophon, which had said "on a home
computer" since the cutover; the README, which presented the manifest set as the only public feed;
the claims register's Kelso entry, which had read his source as a direct provision; and D21, whose
premise that SupGP is fitted to the files this archive keeps is withdrawn by a proposed amendment.
The sentence on the finding page that attributes most of the spread to planned trajectory changes
was never measured; a rewording is proposed to the owner. Whether the archive takes in any of the
per-object set, and whether SpaceX hears of it first, are the owner's decisions; on 31 Aug the project
told SpaceX it makes one manifest-driven pass per eight-hour cycle.

## Evidence

`evidence/scout_summary.json` and `evidence/cadence_summary.json`: status codes, headers, hashes,
sizes, header keyword lines, timestamps and counts. No trajectory, covariance or manoeuvre rows are
committed (raw operator data never is), and the error bodies are withheld because they name the
operator's storage.
