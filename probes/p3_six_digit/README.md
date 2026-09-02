# P3 — Six-digit catalogue rollover breakage survey

**Status: blocked on network, 30 Aug 2026.** `celestrak.org` (104.168.149.178) and the legacy
`celestrak.com` both time out on TCP 443 from this machine's residential IP, while `space-track.org`
and `api.starlink.com` are reachable. That pattern is consistent with a firewall rule on CelesTrak's
side (CelesTrak documents blocking clients that generate repeated errors), possibly covering this ISP
range rather than this host. The earlier research pass hit the same refusal from this network.

**Actions.**
1. Test from another network (phone hotspot) to separate "this IP/ISP" from "CelesTrak down".
2. If it is a block: the pollers run on a VPS regardless, so P3 runs there; and it is worth a polite
   note to Kelso when first making contact — being blocked by CelesTrak is a thing to fix, not work
   around.
3. Space-Track (account required) is the fallback GP source and is reachable from here.

**Planned method (unchanged).** For one object with `NORAD_CAT_ID >= 100000` (the first is 100000,
Saramago / Lusíada 3, 11 Jul 2026) in OMM JSON and, where offered, Alpha-5 TLE: one scripted test per
library — python-sgp4 (`Satrec.sgp4init` from OMM fields; TLE parsing of Alpha-5), Skyfield
(`EarthSatellite` from OMM and from TLE), Orekit (TLE parser), GPredict and KeepTrack (manual). Record
pass / fail / silent-drop with versions. Also count how many active-catalogue objects are six-digit, so
the bulletin can say how much of the sky a TLE-only pipeline is now blind to.

## Datapoint, 2 Sep 2026 - the public catalogue side

First Space-Track snapshot (`gp` class, `OBJECT_NAME/STARLINK~~`, personal account): 12,811 records
(one latest element set per object, decayed objects included since epochs run back to 2020), of which
**365 carry six-digit NORAD ids** (>= 100000). So the six-digit regime is already live in the public
catalogue for Starlink, not only in SpaceX's own file names (NORAD 100224 first archived 31 Aug).
Scoring must filter to current objects (DECAY_DATE null, recent epoch) before comparing.
