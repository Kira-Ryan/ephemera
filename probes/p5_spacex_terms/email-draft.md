# P5 — SpaceX public-files terms: request

**Status:** draft, not sent. Rewritten 30 Aug 2026 so that every sentence is true on the day it is
sent: only what is running is stated in the present tense. Send from a personal address. Record the
send date and any answer in `DOCS/claims-register.md` (Unverified list) and close D06 when answered
or after 30 days.

**To:** the Starlink space-safety onboarding contact (the address published in the
space-safety.starlink.com documentation; confirm it on the docs page before sending)
**Subject:** Mirroring terms for the public Starlink ephemerides

---

Hello,

I run an independent, non-commercial archive project and would like to confirm the terms under which
the public Starlink ephemeris files at api.starlink.com/public-files/ephemerides/ may be retained and
redistributed.

The project fetches each published set once per cycle with conditional requests, records the SHA-256
of every file under a per-cycle Merkle root, and keeps the files so that a set which has been
superseded can still be examined later. I intend to anchor each root with OpenTimestamps, keep the
raw files on cold storage, and publish derived products — public-catalogue error against the
operator trajectory by element age, and covariance self-consistency by lead time — as open datasets
with DOIs. The purpose is a witnessed record of the files, which are otherwise unavailable once
superseded, and a neutral measure of how well the public catalogue tracks the constellation. Nothing
is sold; the code is MIT and the derived data is intended for CC BY 4.0.

Three specific questions:

1. May the raw files be mirrored as published, with attribution to SpaceX and takedown on request?
2. Is there a rate or concurrency policy you would like a poller to respect? I plan one
   manifest-driven pass per eight-hour cycle using conditional requests and would rather ask than
   guess.
3. Is there a preferred citation for the files?

I will honour whatever answer you give, including "no" to mirroring, in which case the archive will
hold hashes only and the derived products will state that. Thank you for publishing the files at
all — it is the only public operator-published trajectory of its kind with covariance, and this
project exists because of it.

Kind regards,
Kira Ryan
