"""P6 - frame check: are the operator files EME2000/J2000 (as the MEME prefix suggests) or TEME?
Propagate the public element set (latest Space-Track GP snapshot in the spool) with Skyfield and
compare with the operator file at five epochs, in both GCRS (J2000 to within a metre here) and
TEME. The frame giving the small, age-dependent residual is the file frame; the other shows a
systematic of tens of km. Usage: probe.py <spool> <cycle dir> [n satellites]"""
import gzip, json, sys, os, math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from skyfield.api import EarthSatellite, load
from skyfield.sgp4lib import TEME

spool = Path(sys.argv[1]); cycle = Path(sys.argv[2]); n = int(sys.argv[3]) if len(sys.argv) > 3 else 6
ts = load.timescale()


def parse_epoch(s):  # YYYYDDDHHMMSS.sss, UTC
    y, doy, hms = int(s[:4]), int(s[4:7]), s[7:]
    return datetime(y, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1, hours=int(hms[:2]), minutes=int(hms[2:4]), seconds=float(hms[4:]))


def read_ephem(p):
    raw = gzip.open(p, "rb").read() if p.suffix == ".gz" else p.read_bytes()
    lines = raw.decode("ascii").splitlines()
    assert lines[3] == "UVW", lines[3]
    recs = []
    for i in range(4, len(lines), 4):
        f = lines[i].split()
        recs.append((parse_epoch(f[0]), tuple(map(float, f[1:4])), tuple(map(float, f[4:7]))))
    return lines[:3], recs


snap = sorted((spool / "gp").glob("*/gp.json.gz"))[-1]
gp = {int(r["NORAD_CAT_ID"]): r for r in json.load(gzip.open(snap, "rb"))}
print("GP snapshot:", snap.parent.name, "| cycle:", cycle.name, "| skyfield GCRS vs TEME")
files = sorted(os.listdir(cycle / "files"))
step = max(1, len(files) // (n - 2))
picked = [f for f in files if f.startswith("MEME_1000")][:2] + files[len(files) // 3::step][:n - 2]
print(f"{'norad':>7} {'gp_epoch':>12} {'eval_h':>6} {'age_h':>7} {'d_GCRS_km':>10} {'d_TEME_km':>10}")
for f in picked:
    norad = int(f.split("_")[1])
    r = gp.get(norad)
    if not r:
        print(f"{norad:>7} not in GP snapshot"); continue
    sat = EarthSatellite(r["TLE_LINE1"], r["TLE_LINE2"], r["OBJECT_NAME"], ts)
    gp_epoch = datetime.fromisoformat(r["EPOCH"]).replace(tzinfo=timezone.utc)
    hdr, recs = read_ephem(cycle / "files" / f)
    for h in (0, 12, 24, 48, 72):
        t, pos, vel = recs[min(h * 60, len(recs) - 1)]
        g = sat.at(ts.from_datetime(t))
        dg = math.dist(g.position.km, pos)
        dt_ = math.dist(g.frame_xyz(TEME).km, pos)
        age = (t - gp_epoch).total_seconds() / 3600
        print(f"{norad:>7} {gp_epoch:%m-%d %H:%M} {h:>6} {age:>7.1f} {dg:>10.3f} {dt_:>10.3f}")
