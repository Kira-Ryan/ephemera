# P5 - SpaceX public-files terms: request

**Status:** draft, not sent. Rewritten 31 Aug 2026 in plain register; every sentence is true on the
day it is sent. Send from a personal address. Record the send date and any answer in
`DOCS/claims-register.md` (Unverified list) and close D06 when answered or after 30 days.

**To:** space-safety-onboarding@spacex.com (confirmed 31 Aug 2026: the address is embedded in
space-safety.starlink.com's own application bundle)
**Subject:** Mirroring terms for the public Starlink ephemerides

---

Hello,

I run a small independent, non-commercial archive project and want to check the terms for keeping
and redistributing the public Starlink ephemeris files at
api.starlink.com/public-files/ephemerides/.

The project pulls each published set once per cycle using conditional requests, records a SHA-256
for every file and a Merkle root per cycle, and keeps the files so that a superseded set can still
be examined later. The roots are anchored with OpenTimestamps. The plan from here is to keep the
raw files on cold storage and publish derived products (public catalogue error against the operator
trajectory by element age, and covariance self-consistency by lead time) as open datasets with
DOIs. Nothing is sold. The code is MIT and the derived data will be CC BY 4.0.

Three questions:

1. May the raw files be mirrored as published, with attribution to SpaceX and takedown on request?
2. Is there a rate or concurrency policy you would like a poller to respect? I run one
   manifest-driven pass per eight-hour cycle with conditional requests, and would rather ask than
   guess.
3. Is there a preferred citation for the files?

Whatever you answer is fine, including no to mirroring. In that case the archive will keep hashes
only, and the derived products will say so. Thanks for publishing these files at all. They are the
only public source of operator trajectories with covariance, and this project exists because of
them.

Kind regards,
Kira Ryan
https://ephemera.space
