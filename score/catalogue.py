"""Load a public-catalogue snapshot written by archive/gp_pull.py
(`<spool>/gp/<stamp>_<sha12>/gp.json.gz` + `record.json`) into element sets keyed by NORAD id.

The snapshot is Space-Track's `gp` class: one latest element set per object, including objects
that have since decayed (DECAY_DATE set). The scorer keeps decayed sets out of the comparison and
counts them. Nothing here talks to the network; the archive is the only input (CLAUDE.md: score/
has no I/O against live feeds)."""
from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class ElementSet:
    norad: int
    name: str
    epoch: datetime
    line1: str
    line2: str
    decay_date: str | None


@dataclass(frozen=True)
class Catalogue:
    snapshot_id: str
    sha256: str
    fetched_utc: str
    sets: dict[int, ElementSet]


def latest_snapshot(spool: Path) -> Path:
    snaps = sorted(p.parent for p in (Path(spool) / "gp").glob("*/record.json"))
    if not snaps:
        raise FileNotFoundError(f"no catalogue snapshots under {Path(spool) / 'gp'}")
    return snaps[-1]


def load(snapshot_dir: Path) -> Catalogue:
    """Load a snapshot, having confirmed it is the snapshot its record claims.

    Every report publishes this digest as the provenance of the public side of the comparison. It
    was published without ever being computed, so a snapshot edited on disk changed the numbers
    while the report went on naming the same hash. Reading the bytes and hashing them is the whole
    of the fix, and it costs one pass over 15 MB."""
    snapshot_dir = Path(snapshot_dir)
    rec = json.loads((snapshot_dir / "record.json").read_text())
    raw = gzip.decompress((snapshot_dir / "gp.json.gz").read_bytes())
    got = hashlib.sha256(raw).hexdigest()
    if got != rec["sha256"]:
        raise ValueError(f"catalogue snapshot {snapshot_dir.name}: the stored bytes hash to {got[:12]}..., "
                         f"which does not match the recorded {rec['sha256'][:12]}...")
    rows = json.loads(raw)
    sets: dict[int, ElementSet] = {}
    for r in rows:
        norad = int(r["NORAD_CAT_ID"])
        epoch = datetime.fromisoformat(r["EPOCH"]).replace(tzinfo=timezone.utc)
        if norad in sets and sets[norad].epoch >= epoch:
            continue
        sets[norad] = ElementSet(norad=norad, name=r.get("OBJECT_NAME", ""), epoch=epoch,
                                 line1=r["TLE_LINE1"], line2=r["TLE_LINE2"], decay_date=r.get("DECAY_DATE") or None)
    return Catalogue(snapshot_id=snapshot_dir.name, sha256=rec["sha256"], fetched_utc=rec["fetched_utc"], sets=sets)
