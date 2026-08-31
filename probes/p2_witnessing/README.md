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

## P2b, 31 Aug 2026 — attestation folded in; Save-Page-Now works on a full-size file

**OpenTimestamps.** `ots upgrade` on the P2 evidence (python:3.12-slim container) fetched an
attestation from all four calendars and completed the proof: **Bitcoin block 964715** (merkle root
`149296c7…`). `ots verify` in the same clean container fails only at the last step with "Could not
connect to Bitcoin node": the reference client checks the block header against a local `bitcoind`
and has no explorer fallback. Consequence for `VERIFY.md`: the independent check is `ots verify`
plus either a Bitcoin node or a manual comparison of the block-964715 merkle root against any
block explorer; say so rather than pretending `ots verify` alone suffices on a bare machine.

**Wayback on a 2 MB file.** Save-Page-Now accepted a full ephemeris file
(`MEME_69343_STARLINK-37776_…`, 2,037,837 raw bytes) from the live feed: capture
`20260831153206`. The `id_` copy returns the origin's transfer encoding — 831,402 bytes with
`content-encoding: gzip` — and **gunzipping it yields exactly the recorded raw SHA-256**
(`2080c901…`). Consequence for `witness.py` and the verification story: the sceptic's check is
`sha256(gunzip(id_ copy)) == recorded hash`; comparing the wire bytes directly would fail.

Remaining from P2: sustained SPN rate (manifest + 10 files, three cycles a day) — measured once
`witness.py` automates it, with 429s recorded loudly.
