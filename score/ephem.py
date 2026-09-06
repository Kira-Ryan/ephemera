"""Parser for the operator-published Starlink ephemeris files archived in a cycle (`MEME_*.txt`,
stored gzipped by the poller).

Format, verified against archived files on 2 Sep 2026 (probe P6):

    created:2026-09-02 09:30:50 UTC
    ephemeris_start:2026-09-02 09:10:42 UTC ephemeris_stop:2026-09-05 09:10:42 UTC step_size:60
    ephemeris_source:blend
    UVW
    2026245091042.000 x y z vx vy vz          one record = this line plus three covariance lines
    c1 c2 c3 c4 c5 c6 c7                      21 lower-triangular covariance elements, 7 per line,
    c8 ... c14                                in the frame named on line 4
    c15 ... c21

Record epochs are `YYYYDDDHHMMSS.sss`, UTC. Positions are km in EME2000/J2000 (the MEME prefix;
P6 measured a 32-45 km error when the files are read as TEME), velocities km/s. Anything that does
not fit the format raises ValueError naming the file and line; nothing is skipped silently.
"""
from __future__ import annotations

import gzip
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

HEADER_LINES = 4
LINES_PER_RECORD = 4
COV_ELEMENTS = 21

_HDR2 = re.compile(r"^ephemeris_start:(\S+ \S+) UTC ephemeris_stop:(\S+ \S+) UTC step_size:(\d+)$")
_NAME = re.compile(r"^MEME_(\d+)_([^_]+)_")


@dataclass(frozen=True)
class Record:
    epoch: datetime
    pos: tuple[float, float, float]
    vel: tuple[float, float, float]
    cov: tuple[float, ...]


@dataclass(frozen=True)
class Ephemeris:
    norad: int
    object_name: str
    created: datetime
    start: datetime
    stop: datetime
    step_s: int
    source: str
    cov_frame: str
    record_count: int
    records: tuple[Record, ...]


def parse_epoch(s: str) -> datetime:
    """`YYYYDDDHHMMSS.sss` (UTC) to an aware datetime."""
    if len(s) < 13 or not s[:13].isdigit():
        raise ValueError(f"bad record epoch {s!r}")
    return (datetime(int(s[:4]), 1, 1, tzinfo=timezone.utc)
            + timedelta(days=int(s[4:7]) - 1, hours=int(s[7:9]), minutes=int(s[9:11]), seconds=float(s[11:])))


def parse_name(filename: str) -> tuple[int, str]:
    """`MEME_<norad>_<object name>_...` to (norad, object name)."""
    m = _NAME.match(Path(filename).name)
    if not m:
        raise ValueError(f"not an operator ephemeris file name: {filename!r}")
    return int(m.group(1)), m.group(2)


def _utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def read_raw(path: Path) -> bytes:
    """The file's own bytes, decompressed. These are the bytes the poller hashed, so these are the
    bytes to check a record against."""
    return gzip.open(path, "rb").read() if path.suffix == ".gz" else path.read_bytes()


def read_lines(path: Path) -> list[str]:
    return read_raw(path).decode("ascii").splitlines()


def record_count(lines: list[str]) -> int:
    body = len(lines) - HEADER_LINES
    if body < LINES_PER_RECORD or body % LINES_PER_RECORD:
        raise ValueError(f"{len(lines)} lines is not a header plus whole records")
    return body // LINES_PER_RECORD


def parse_record(lines: list[str], index: int, path: Path) -> Record:
    base = HEADER_LINES + index * LINES_PER_RECORD
    try:
        f = lines[base].split()
        if len(f) != 7:
            raise ValueError(f"expected epoch + 6 state values, got {len(f)} fields")
        cov = tuple(float(x) for ln in lines[base + 1:base + 4] for x in ln.split())
        if len(cov) != COV_ELEMENTS:
            raise ValueError(f"expected {COV_ELEMENTS} covariance elements, got {len(cov)}")
        return Record(parse_epoch(f[0]), tuple(float(x) for x in f[1:4]), tuple(float(x) for x in f[4:7]), cov)
    except (ValueError, IndexError) as e:
        raise ValueError(f"{path.name} record {index} (line {base + 1}): {e}") from e


def read(path: Path, indices: list[int] | None = None) -> Ephemeris:
    """Parse one file. With `indices`, only those record positions are parsed (the scorer samples
    every N minutes and has no use for the other 4,000 rows); the header is always checked."""
    path = Path(path)
    lines = read_lines(path)
    if len(lines) < HEADER_LINES or not lines[0].startswith("created:") or not lines[2].startswith("ephemeris_source:"):
        raise ValueError(f"{path.name}: header does not match the published format")
    m = _HDR2.match(lines[1])
    if not m:
        raise ValueError(f"{path.name}: line 2 does not match the published format: {lines[1][:80]!r}")
    n = record_count(lines)
    norad, name = parse_name(path.name)
    wanted = range(n) if indices is None else indices
    recs = []
    for i in wanted:
        if not 0 <= i < n:
            raise ValueError(f"{path.name}: record index {i} outside 0..{n - 1}")
        recs.append(parse_record(lines, i, path))
    return Ephemeris(norad=norad, object_name=name, created=_utc(lines[0][len("created:"):].removesuffix(" UTC")),
                     start=_utc(m.group(1)), stop=_utc(m.group(2)), step_s=int(m.group(3)),
                     source=lines[2][len("ephemeris_source:"):], cov_frame=lines[3].strip(),
                     record_count=n, records=tuple(recs))
