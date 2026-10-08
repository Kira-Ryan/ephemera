# Decision log

Every material choice is a dated decision of record with its rationale. Amend by adding a new entry
that supersedes the old one; never edit history.

## D01 — Name and scope (2026-08-30, proposed)

Working name **Ephemera**: the project keeps ephemerides that are ephemeral. Scope for v1: Starlink
public ephemerides as the sole operator-truth source; the public GP catalogue as the thing measured;
four layers (archive, visibility scoreboard, covariance self-consistency and census, multi-operator
truth via SupGP). Alternatives considered: *Orbit Witness* (clearest statement of mechanism), *Latent
Orbit* (brand continuity with Latent Sky), *The Third Catalogue* (kept as the framing line, not the
product name). Status: **proposed** until the name is confirmed and a domain is registered.

## D02 — Clean-room rule (2026-08-30, accepted)

No code, configuration, prompt, schema or document from any employer or client engagement is used,
adapted or consulted. Propagation from python-sgp4 / Skyfield / Orekit; hashing and Merkle trees from
the standard library; witnessing via OpenTimestamps and the Wayback Machine; no KMS signing. Built
and run on personal infrastructure only, with an account guard that refuses any employer cloud
account by ID (the Latent Sky pattern). Rationale: the value of this project is that it is
independent; a single reused line would compromise both the independence and the IP position.
Before the first public commit: re-read the IP-assignment clause of current agreements for side
projects in a related field.

## D03 — Archive first (2026-08-30, accepted)

The archive runs before any scoring exists. Rationale: superseded files vanish at the next eight-hour
cycle and cannot be backfilled; every day the archive is not running is data that never comes back.
Two geographically separate pollers, a measured cycle-time objective (a full pull well inside eight
hours), and poller uptime published in the ledger so gaps are visible.

## D04 — Never a single ratio against the FCC count (2026-08-30, accepted)

SpaceX's semi-annual FCC figure counts "events resulting in an action (manoeuvre or coordination)"
under a private 3e-7 Pc screen. Public predictions cannot label avoidance versus station-keeping,
and station-keeping dominates. The project publishes three differently defined series side by side —
in-file burns (deduplicated across overlapping files), plan-change events (divergence beyond the
earlier covariance), and the declared count — with the definitional caveat on the same line, and
never a ratio. Any output that could be quoted as "SpaceX inflates" or "the detector is blind" is a
defect.

## D05 — "Self-consistency", never "realism" (2026-08-30, accepted)

Comparing an earlier prediction with a later one from the same operator measures prediction
self-consistency, contaminated by re-plans and orbit-determination updates. Public GP data is
100–1000× too noisy to serve as an independent check of sub-metre covariance. The word "realism" is
reserved for a later module scored against genuinely independent truth (laser-ranging predictions,
GNSS-tracked LEO satellites), labelled as such.

## D06 — Licences (2026-08-30, proposed)

MIT for code. Derived datasets CC BY 4.0 with a citation string and DOI per release. Raw SpaceX files
mirrored as published; SpaceX states no licence in its README; the files were previously distributed
publicly via Space-Track; an academic group has redistributed a week of them without incident.
Position: mirror as-is, takedown on request, and record SpaceX's answer to a written request for
terms. Space-Track GP/OMM/SATCAT redistributed only under Space-Track's blanket approval for basic
SSA data, with citation; CDMs and operator ephemerides obtained via Space-Track are never used.
Status: proposed until the SpaceX request is answered or 30 days elapse.

## D07 — Witnessing is the verification story (2026-08-30, accepted)

A hash of a file only this project possesses is "trust me". Verification therefore requires
(a) third-party witnessing of inputs — OpenTimestamps on each daily Merkle root, Wayback Machine
capture of the manifest and sampled files each cycle — and (b) published, re-computable derived
products with pinned container digests. The site never claims that inputs can be re-fetched from
SpaceX after eight hours.

## D08 — Zero-ops by design (2026-08-30, accepted)

A reference service that goes dark loses its standing; a continuously running one is what made
CelesTrak a full-time job. All computation happens at build time; the published product is static
files; a public status page shows poller health; the product degrades gracefully to catalogue-only
metrics if the SpaceX feed stops or changes; and a SpaceX cut-off is treated as making the archive
more valuable, not as the end of the project.

## D09 — Merkle construction (2026-08-30, accepted)

Leaves are the SHA-256 digests of the raw (un-gzipped) file bytes, in `MANIFEST.txt` order. Each
layer hashes adjacent pairs as SHA-256(left || right); an odd trailing node is paired with a copy of
itself. The root is written to `root.txt` only when every listed file was recorded; a cycle with
gaps has `merkle_root: null` and is kept, so the gap is visible. Rationale: simplest construction a
third party can re-implement from one paragraph; the duplicate-last-leaf rule is stated because it
is the one detail that differs between implementations. Changing any of this changes every
subsequent root and is a new decision plus a new record schema version.

## D10 — Cycle identity (2026-08-30, accepted)

A cycle is identified by the SHA-256 of `MANIFEST.txt` as served (directory
`cycle_<UTC date>_<sha256[:12]>`), not by wall-clock time. Rationale: the manifest changes every
cycle and is the only server-side statement of "the current set"; two pollers pulling the same
manifest produce the same cycle identity and, when complete, the same root — which is what makes a
second poller a check rather than a duplicate. Files are stored gzipped; the recorded hash is always
of the raw bytes, so a future change of compression cannot alter a root.

## D11 — Cycle directory name carries no wall-clock component (2026-08-30, proposed)

Supersedes the *naming* in D10, not the identity rule. The cycle directory is
`cycle_<manifest sha256[:12]>`; the UTC date of the first run on that manifest is recorded in
`cycle.json` as `first_seen_utc` and preserved across resumes. Rationale: the date prefix defeated
the purpose D10 states — a resume across UTC midnight, or a second poller on the other side of it,
produced a different identity and re-downloaded everything. Accepted in conversation by the owner
on 2026-08-30; implemented in `archive/poll.py` with a caller-level test.

## D12 — Canonical `root.txt` bytes (2026-08-30, proposed)

`root.txt` is exactly 64 lowercase hexadecimal characters followed by a single LF (65 bytes, no
BOM, no CR). The OpenTimestamps proof commits to exactly those bytes. The P2 evidence file
(`probes/p2_witnessing/evidence/root.txt`) was written with CRLF on Windows and its `.ots` commits
to the CRLF digest; it is kept as stamped, with a footnote in the P2 README, and is not the
reference form. Rationale: a verifier who retypes the root will otherwise fail on the line ending.

## D13 — Partial, interrupted and refused runs (2026-08-30, proposed)

A `--limit` run is a test slice: written under `<spool>/partial/`, recorded with `partial: {limit}`,
never given a root, exit 3. An interrupted run (SIGINT/SIGTERM) writes its record with
`status: interrupted` and what was recorded so far, no root, exit 4. A run that cannot start (no
contact address, spool volume below the free-space floor, empty manifest) exits 5 before any
download. Manifest entries that are not a single path component, and duplicate entries, are
counted as gaps: they never touch the filesystem and the cycle gets no root. Exit 2 remains
"gaps". Rationale: the original poller wrote `root.txt` for a 50-file slice, which `make stamp`
would have anchored as if complete.

## D14 — Hosting split (2026-08-30, proposed; defaults accepted by the owner)

The personal AWS account (the one Latent Sky uses, guarded by account ID; never the machine's
default profile, which is an employer account) holds only the cold bucket, the small ledger bucket,
the site bucket, CloudFront, Route 53 and ACM. Pollers, witnessing, shipping and the daily build
run on non-AWS Linux VPSs in two providers/regions. Nothing on AWS runs continuously; no database,
Lambda or NAT gateway. Rationale: D08 plus cost — the all-AWS layout priced above the P4 kill line
before storage growth, and put every credential on one host.

## D15 — Storage unit and safety (2026-08-30, proposed)

One uncompressed tar per cycle (the gzipped files, `MANIFEST.txt`, `cycle.json`, `root.txt`,
`root.txt.ots`, `witness.json`), streamed to the bucket with a full-object SHA-256 verified before
the local copy is deleted; gapped cycles are shipped too; the poller keeps three days locally;
put-only credentials on the poller; versioning and Object Lock in governance mode; a billing alarm.
The storage tier is chosen from the P4 table (`probes/p4_cost/README.md`) — default S3 Glacier
Deep Archive if within 20% of the alternatives. Rationale: per-file objects cost ~1M requests a
month; a tar per cycle costs ~90.

## D16 — Witnessing schedule (2026-08-30, proposed)

Every complete cycle root is stamped with OpenTimestamps immediately; an hourly job folds in the
Bitcoin attestation (`ots upgrade`) and records the block height. A daily root is built by the D09
construction over the day's cycle roots in `first_seen_utc` order and stamped, so D07's "daily
Merkle root" is literal. Each cycle, `MANIFEST.txt` and ten files chosen by manifest index from the
cycle root as a seed (unpredictable, reproducible) are submitted to the Wayback Machine through an
authenticated account, and the `id_` copies are re-hashed against the record. A witnessing failure
is recorded loudly and never blocks shipping. Blocks on probe P2b (SPN on a 2 MB file; sustained
rate; `ots verify` from a clean container).

## D17 — Watcher policy and contact (2026-08-30, proposed)

`archive/run_cycle.py` issues a conditional GET of `MANIFEST.txt` every 120 s (`Cache-Control:
max-age=60` bounds staleness to a minute); a new hash starts a cycle; any cycle whose record is not
`complete` is retried while its manifest is current; a rolled manifest is never retried, so a gap
stays visible. Every tick rewrites `heartbeat.json`. Every request carries a User-Agent with a
real contact address; the poller refuses to run without one.

## D18 — Ledger and coverage definitions (2026-08-30, proposed)

The ledger holds one record per poller per cycle, built at build time from the pollers' records
and heartbeats; disagreement between pollers is published, never suppressed. *Observed coverage*
is the fraction of wall-clock minutes with at least one heartbeat under ten minutes old; a cycle is
*complete* when any poller holds a full record with a root; unobserved windows are published as
such rather than assumed healthy.

## D01 — Name and scope: accepted (2026-08-31)

The name **Ephemera** is confirmed and the domain **ephemera.space** was registered on 31 August
2026 on the owner's personal Cloudflare account (registry-premium pricing, accepted knowingly as
the project's one brand asset; the renewal price was checked at purchase). This closes D01's
"proposed until the name is confirmed and a domain is registered" condition. Scope is unchanged.

## D19 — Site hosting moves to Cloudflare Pages (2026-08-31, proposed)

Amends the hosting split in D14: the static site is served by Cloudflare Pages on the owner's
personal Cloudflare account, not S3 + CloudFront. Deciding fact: the domain was registered through
Cloudflare Registrar, which requires Cloudflare nameservers, so Route 53 was never available for
DNS; Pages is free for a static site, needs no ACM or CDN configuration, and keeps the site on the
same personal account as the domain. AWS remains the cold-storage home (D15). The deploy script,
when it exists, is guarded like every infra script — with a Cloudflare account-ID allowlist in
`infra/personal.env` alongside the AWS one. The rest of D14 (pollers off AWS, nothing on AWS runs
continuously, no database) stands.

## D15 — amendment: what the shipped tar's integrity check actually is (2026-09-02, proposed)

As built (`archive/ship.py`): one uncompressed tar per finished cycle (gapped cycles included) is
multipart-uploaded straight into S3 Glacier Deep Archive in eu-west-1, bucket `ephemera-space-raw`
(Object Lock governance mode with no default retention, public access blocked, cost tag
`project=ephemera`, stale multipart uploads aborted after 7 days). S3 offers no full-object SHA-256
for multipart uploads, so the earlier wording is corrected: transit integrity comes from per-part
CRC32 checksums that S3 validates before accepting each part; content identity is the tar's SHA-256,
computed locally before upload and stored in the object's metadata (`x-amz-meta-sha256`) and in the
cycle's `ship.json`; the post-upload check compares size, metadata and storage class. A restore is
verified against that recorded SHA-256 (`VERIFY.md`). The small records (cycle.json, root.txt,
root.txt.ots, witness.json, MANIFEST.txt) sit beside the tar in STANDARD class so verifiers and
the ledger never need a restore, and are re-synced whenever their bytes change. Local `files/` are
deleted only after a verified upload and `--keep-days` (3); the shipper never edits the poller's
cycle.json - its state lives in `ship.json`. Single copy of record for now (P4); the witnessed
roots mean a lost object can be detected but not faked.

## D20 — Site page map and permanent URLs (2026-09-06, proposed)

The site is six static pages built by `web/build.py` from the spool, plus a branded `404.html`:
`/` (front page, fixed size for the life of the project), `/finding/` (the full finding for the
headline cycle), `/scored/` (every scored cycle, one row per cycle), `/archive/` (every archived
cycle and the daily roots), `/check/` (the verification procedure, data, licence and citation) and
`/globe/`. Anything that gains a row per cycle lives on `/scored/` or `/archive/`, never on the
front page. Those two pages hold the current UTC year in one section per month; when a second year
exists, earlier years move to `/scored/<year>/` and `/archive/<year>/` in the same template, and
the landing page keeps the current year. A row's id is `s-<sha12>` on `/scored/` and `c-<sha12>`
on `/archive/`, and a row's URL never moves once published; a year move is a redirect stub, not a
broken link. The fragment ids the front page already carries (`#finding`, `#archive`, `#check`,
`#data`, `#next`, `#who`) stay as landing stubs because they are indexed. `ledger.json` stays a
single file until it passes 2 MB, at which point it splits per month under the same paths; that
split gets its own entry. Rationale: "tabs" in the owner's words, implemented as pages so every
table row is linkable and indexable and the front page has a fixed height forever.

## D21 — A SupGP column beside the GP column on the scoreboard (2026-09-27, proposed; the owner said yes to the column on 27 Sep)

The visibility pages gain a second public reference: CelesTrak's supplemental GP element sets for
Starlink (`sup-gp.php?FILE=starlink`, JSON), fitted by CelesTrak to the first six hours of the
operator's own ephemerides and published with a fit RMS, as Dr Kelso described them in his reply of
27 September 2026. The GP column stays exactly as it is. The two columns answer different questions
and the page says so in those words: the GP column is what independent tracking can see (radar and
optical, no knowledge of planned manoeuvres); the SupGP column is how faithfully a six-hour SGP4 fit
of the operator's plan carries that plan, and how fast the fit ages past its window. SupGP is
derived from the same files this archive holds, so the archive is also what lets anyone check a
SupGP fit against its source. Neither column is a grade, an error of the satellite, a statement of
which side is right, or a single ratio against any count (D04, D05 unchanged); the prohibited
wording in the claims register applies to both.

Mechanics, mirroring the catalogue: a puller stores each SupGP snapshot under
`spool/supgp/<stamp>_<sha12>/` with the raw bytes gzipped, a record (sha256 of the raw bytes, count,
epoch range, the RMS field kept) and the D09 root, witnessed and shipped like `gp/`; an unchanged
snapshot is not stored twice; the scorer pairs each cycle with the newest SupGP snapshot fetched
before it and scores at the same instants as the GP column. Rate: CelesTrak's usage policy (read 27
Sep 2026) asks for SupGP no more often than every 2 hours and for machine clients to stop on any
non-200; the puller obeys both, and a non-200 is an error on the record, never a retry loop.
CelesTrak states no licence text on the pages read (the supplemental data page and the usage
policy); attribution is given on the page and in `check/` regardless, and `licences/celestrak.md`
(the folder is the owner's to create; it does not exist yet) records: source, URL, the usage
policy's cadence and stop rule, the date read, and that no licence text was found.

The finding page cites the prior work in the owner's wording of 3 October 2026, on the page from
that day, ahead of the column: "The gap between GP and operator data is a known result, not a
finding of mine. In December 2007 a CelesTrak user reported a GPS satellite whose GP element set
put it more than 20,000 km from where the operator's own almanac did, and Dr T.S. Kelso confirmed
the almanac was right. He had already measured the problem that January (AAS 07-127), and CelesTrak
has published supplemental element sets fitted to operator data since January 2008. His 2025 SDA
TAP Lab talk tells the story and links the papers." Each statement was checked on 3 October against
his own pages: the December 2007 report, the 20,000 km and his check against the NGA precise
ephemerides are in the SDA TAP Lab talk of 26 February 2025, as is the sentence that the results
"were written up on the new SupGP page and reported to JSpOC in January 2008"; AAS 07-127 is his
paper of 29 January 2007. Rationale: his reply of 27 September
made two things plain, that a comparison against GP alone repeats a result he published, and that
SupGP is the public product actually built for this; a reader deserves both columns and the
reference. Follow-on, not part of this entry: whether the SupGP RMS itself belongs on the page.

## D21 amendment: what SupGP is fitted to (2026-10-08, proposed)

D21 says SupGP "is derived from the same files this archive holds, so the archive is also what lets
anyone check a SupGP fit against its source". That is wrong, and the sentence is withdrawn. SupGP for
Starlink is fitted to the per-object files SpaceX serves by satellite name, not to the manifest-listed
files this archive keeps (Dr Kelso, 7 Oct 2026; the per-object set measured as probe P9, 8 Oct 2026). The two sets differ in format (CCSDS
OCM 3.0 against the manifest set's MEME text), in reference frame (ITRF2000 in the per-object files),
in horizon (seven days against two to three) and in timing; whether they agree at a common epoch has
not been measured. For the column, which is not built: until the archive holds the version a SupGP fit
was made from, the SupGP column compares CelesTrak's fit of one operator file with a different
operator file written at a different time, and the page says so in those words; the pairing rule is
restated when the column is built. The GP column, D04 and D05 are unchanged. Whether the archive takes
in any of the per-object set is the owner's decision, open as of this entry.

