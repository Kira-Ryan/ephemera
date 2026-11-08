# Corrections

Every correction to something this project published, with its date, what was wrong and what replaced
it. Entries before 7 Sep 2026 predate the public repository.

- 2026-08-30 - Gzipped bytes per file was quoted as 848,660; the only measurement in the repository is
  about 821,000 (`gzip -6`, one file, probe P1). Replaced everywhere; the derived monthly volume moves
  from about 0.85 to about 0.82 TB.
- 2026-08-30 - Seconds per file on one connection was quoted as 5.3 s; probe P1 measured 4,892 ms.
  Replaced; the sequential-pull projection moves from about 16 h to about 15 h.
- 2026-08-30 - The full-cycle projection appeared as three figures (116, 45 to 80, and 80 to 116 min)
  across four documents. Replaced by the range 45 to 116 min with both measurements shown in the P1 table.
- 2026-08-30 - `README.md` said the request to SpaceX had been sent; it had not. Replaced with the
  drafted-not-sent status.
- 2026-08-30 - `README.md` said "no public archive exists" and "zero public archives"; a one-week public
  sample (25 Nov to 1 Dec 2024, arXiv 2506.13034) exists. Replaced with "no continuous public archive".
- 2026-08-30 - The draft of the request to SpaceX described a daily Merkle root, a hash chain, cold storage
  and DOIs in the present tense before any of them existed. Rewritten to state only what ran at send time.
- 2026-10-08 - A design note said SupGP "is derived from the same files this archive holds". That was wrong
  and is withdrawn: probe P9 measured a second public set, requested by satellite name. The site's colophon
  said the project ran "on a home computer" from 3 Oct, when the home machine stopped running anything, until
  8 Oct; it now says "on one rented server".
- 2026-11-08 - A check of the live site on 5 Nov found these false as written; all were corrected in one
  change.
  - **"Manifest NEVER CAPTURED"** on 37 rows: the witness got HTTP 500 from Save Page Now and recorded no
    copy, but the Wayback Machine had made most of them (probe P10). 33 manifests and 315 of 330 samples hash
    to this archive's records, so "with a defect in the independent copy" fell from 45 to 17 on the build of
    8 Nov, and the rows that remain say no copy was found.
  - **The Bitcoin block** printed was a later block than `ots verify` reports on 44 of 210 cycles and, on
    512ed350b125, a block its stored proof did not hold. The page now prints the lowest block in the proof
    it links.
  - **"Three things you can run right now"**: step 1 gave the wrong hash with plain curl (the copy arrives
    gzipped), step 2 said "k from 0 to 9" (nine names on a435fa5f0103), and step 3 needed a proof nobody
    could get. All three now work as written.
  - **"The copies have been failing"** on /check/, printed whenever a new root was only waiting for its
    block. It now gives the actual reason.
  - **"Most of an orbit" and "a large part of an orbit"** for 1,000 km, which is 2.3% of one.
  - **"The count only falls"** of the seven hindsight cycles. The share falls and the count cannot.
  - **"Listed apart"** on the globe, of satellites listed nowhere.
  - **"An older globe can be replayed"**, when the page has no way to load another pack.
  - **"The moment it is caught"**: a copy follows by a median of about 18 minutes.
  - **"Gaps in the spacing are the feed's own cadence"**, beside a count of gaps the poller was down for.
  - **"0 with nothing scored"** with six archived cycles that have no report. They are now named.
  - The 404 page's "every table row has a permanent address", and "one tab to the left".
