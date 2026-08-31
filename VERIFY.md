# Verifying an Ephemera cycle

You should not have to trust this project. Every claim an archived cycle makes can be re-checked
from its own artefacts, offline, with one script - and the parts that need a third party
(OpenTimestamps, the Wayback Machine) are checkable against those third parties directly.

## What a cycle directory contains

```
cycle_<manifest sha256[:12]>/
  MANIFEST.txt      the manifest exactly as served by api.starlink.com
  files/<name>.gz   every listed file, gzipped; the recorded hash is of the RAW bytes
  cycle.json        the record: per-file SHA-256 and size, counts, the Merkle root
  root.txt          the root: 64 lowercase hex + one LF (65 bytes)
  root.txt.ots      the OpenTimestamps proof over root.txt's exact bytes
  witness.json      what was stamped and captured, when, and whether it verified
```

## The offline check

```
python archive/verify.py <cycle directory>          # full; add --sample 200 to spot-check
```

It re-hashes every stored file against the record, rebuilds the Merkle root from the recorded
hashes with an INDEPENDENT re-implementation of the documented construction, and checks the root
file's exact bytes and the record's internal counts. The construction, in full (D09): leaves are
the raw SHA-256 digests in manifest order; each layer hashes adjacent pairs as
SHA-256(left || right); an odd trailing node is paired with a copy of itself. That paragraph is
the whole specification - you can reimplement it yourself in a dozen lines rather than trust
`verify.py`.

## The third-party checks

**OpenTimestamps** proves the root existed no later than a Bitcoin block's timestamp.
`ots verify root.txt.ots` gives the full check but needs a Bitcoin node. Without one:
`ots info root.txt.ots` prints the attestation's block height and block merkle root - compare
that merkle root against the same block on any block explorer you trust.

**Wayback Machine** captures prove the inputs existed at the source: each cycle's manifest and ten
files - chosen by index as `int(sha256(root_hex + ":" + k), 16) mod n_files` for k = 0, 1, ... -
were submitted while live. Fetch a capture's `id_` URL (in `witness.json`), gunzip it (the copy is
the origin's gzip transfer encoding), and its SHA-256 must equal the recorded hash:
`python archive/verify.py <cycle> --wayback` does exactly that.

Operator ephemerides are predictions, not observations. Inputs are archived by this project and
witnessed by OpenTimestamps and the Wayback Machine; they are not re-fetchable from the source
after one cycle - which is why the witnessing exists.

## A worked example (the first archived cycle)

| Item | Value (as of 31 Aug 2026) |
|---|---|
| Cycle | `cycle_72bcd7796b49`, first seen 2026-08-30 13:32 UTC |
| Files | 17,861 recorded of 17,861 listed |
| Merkle root | `677d3043ef282de6ca7260c2b08e793f527321143ca991a37b9b72e468c520fd` |
| OpenTimestamps | attested at Bitcoin block **964904** (stamped 15:55 UTC, upgraded 17:06 UTC, 31 Aug 2026) |

A historical footnote: the probe-P2 evidence proof (`probes/p2_witnessing/evidence/`, Bitcoin
block 964715) commits to a root.txt whose bytes end in CRLF, because it was written on Windows
before D12 fixed the canonical form; it is kept exactly as stamped, and `ots verify` must be run
against those bytes as they are.
