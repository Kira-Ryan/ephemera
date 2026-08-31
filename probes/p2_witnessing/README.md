# P2 — Third-party witnessing: OpenTimestamps and the Wayback Machine

**Question.** Can a third party later prove that the inputs existed, without trusting this project?

**Method.** 30 Aug 2026. SHA-256 of the 48 files pulled in P1; Merkle root built by pairwise
SHA-256 with the last leaf duplicated on odd layers (the same construction the poller uses);
`ots stamp` on the root; Wayback Machine Save-Page-Now on the manifest URL.

**Measured.**

| Item | Result |
|---|---|
| Files hashed | 48 |
| Merkle root | `91755da29c9e353fec41b7435587979892f2be17b1d328f38ff2074e85cc442d` |
| `ots stamp` on Windows | **Crashed** — `python-bitcoinlib` fails to load libssl through `ctypes` on Windows (`TypeError` in `ctypes/__init__.py`). Known platform issue, not an OTS problem. |
| Wayback Save-Page-Now on `MANIFEST.txt` | **HTTP 302** to `https://web.archive.org/web/20260829232117/https://api.starlink.com/public-files/ephemerides/MANIFEST.txt`; the availability API confirms the capture. |

**Consequences.**
- Stamping runs on Linux (the pollers will be Linux VPSs anyway). Locally, use Docker or WSL for
  development; do not spend time patching the Windows client.
- Wayback SPN works on the manifest. Still to test: SPN on a 2 MB ephemeris file (size limits), and
  the sustained rate (three cycles a day × manifest + sampled files).
- The Merkle construction (duplicate-last-leaf) is now a decision to record; write it into the
  archive README and never change it silently (a change alters every subsequent root).

**Open.**
- OTS stamp and, ~hours later, `ots upgrade` / `ots verify` from a clean machine — pending a Linux run.
- Whether a per-cycle Wayback capture of the manifest is enough, or whether sampled files are also
  needed for a convincing witness (proposal: manifest every cycle + 10 files chosen by the cycle's
  Merkle root as a seed, so the sample is unpredictable but reproducible).

## Update, 30 Aug 2026 — stamp succeeded on Linux

Run in a `python:3.12-slim` Docker container with `opentimestamps-client`: `ots stamp root.txt`
submitted the root to four calendars (a.pool.opentimestamps.org, b.pool.opentimestamps.org,
a.pool.eternitywall.com, ots.btc.catallaxy.com) and wrote `root.txt.ots` (840 bytes). The proof
currently carries *pending* attestations; the Bitcoin attestation arrives within hours and is
folded in with `ots upgrade root.txt.ots`, after which `ots verify` on a clean machine is the
independent check. `evidence/` holds the root, the proof and the 48-file manifest it commits to.

Resolution: witnessing is feasible and cheap. The poller's cycle `root.txt` is the stamp input.
Remaining: run `ots upgrade` + `ots verify` once attested; test Save-Page-Now on a 2 MB file.

## Footnote, 30 Aug 2026 — what the stamped bytes are (D12)

`evidence/root.txt` is 66 bytes: the 64-hex root followed by CRLF, because it was written on
Windows. `evidence/root.txt.ots` commits to the SHA-256 of exactly those 66 bytes
(`a7ff79448143329372bf061cb434574d3836197c2a88056bff6259e1d9c7611e`), not to the root with a bare LF.
`ots verify` must therefore be run against this file as it is; a re-typed `root.txt` with LF will
fail. The canonical form from D12 onward is 64 lowercase hex + a single LF (65 bytes), which is
what `archive/poll.py` now writes; this evidence file is kept unchanged rather than re-stamped.
