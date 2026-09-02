# P6 - Frame of the operator files, and first public-vs-operator residuals

**Question.** The archived files are named `MEME_<norad>_...`: Mean Equator, Mean Equinox, i.e.
EME2000/J2000. SGP4 produces TEME. Before any scoring: which frame are the positions in, and does a
clean-room propagation of the public element set land anywhere near the operator trajectory?

**Kill criterion.** If the smallest residual came out at tens of km in both frames, either the frame
assumption or the time convention is wrong and the scoreboard cannot be built on this parser.

**Method, 2 Sep 2026.** `probe.py`: the newest archived cycle (`cycle_f5112bb77a2a`, ephemeris
start 09:10:42 UTC) against the latest public-catalogue snapshot (`20260902T200733Z_0821a18806eb`,
Space-Track `gp`, fetched 20:07 UTC). For seven satellites, the element set is propagated with
Skyfield 1.55 (python-sgp4 2.27) to the file's own record epochs at 0, 12, 24, 48 and 72 h from
start, and the distance to the file position is taken twice: with Skyfield's GCRS output (within a
metre of J2000 at this scale) and with its TEME output. Record epochs `YYYYDDDHHMMSS.sss` are read as
UTC. Element age is the evaluation epoch minus the element set's epoch, so it is negative when the
public set is newer than the file's start.

**Measured.**

| NORAD | set epoch (UTC) | eval h | age h | d GCRS km | d TEME km |
|---|---|---|---|---|---|
| 100001 | 09-02 13:15 | 0 | -4.1 | 0.979 | 32.278 |
| 100001 | | 12 | 7.9 | 5.981 | 13.259 |
| 100001 | | 24 | 19.9 | 26.939 | 41.484 |
| 100001 | | 48 | 43.9 | 105.597 | 117.338 |
| 100001 | | 72 | 67.9 | 236.226 | 241.437 |
| 100002 | 09-02 14:37 | 0 | -5.2 | 2.332 | 31.734 |
| 100002 | | 72 | 66.8 | 359.926 | 366.774 |
| 57525 | 09-02 14:04 | 0 | -3.3 | 1.865 | 31.829 |
| 57525 | | 72 | 68.7 | 1.179 | 35.548 |
| 61940 | 09-02 06:09 | 0 | 4.7 | 4.369 | 37.159 |
| 61940 | | 72 | 76.7 | 302.135 | 313.534 |
| 65411 | 09-01 22:54 | 0 | 11.0 | 4.337 | 45.165 |
| 65411 | | 72 | 83.0 | 97.501 | 121.611 |
| 68668 | 09-02 08:36 | 0 | 0.8 | 0.223 | 40.110 |
| 68668 | | 48 | 48.8 | 2.038 | 39.123 |
| 68668 | | 72 | 72.8 | 17.316 | 33.730 |

(The full 35-row output is what `probe.py` prints; the rows above are the ones that carry the
conclusion.)

**Conclusion.**
- **The positions are EME2000/J2000.** Every satellite shows a 32-45 km residual when the file is
  read as TEME and a 0.2-4 km residual at small age when read as J2000. The parser and the scorer
  treat the files as J2000 and take Skyfield's GCRS output as J2000; the frame-bias difference is
  under a metre at these radii, far below anything scored.
- **Time convention holds.** Record epochs read as UTC give sub-km agreement at zero age; a
  UTC/TAI or day-of-year slip would show as tens of km along-track.
- **Six-digit ids propagate.** 100001 and 100002 carry Alpha-5 designators in their public
  element lines and python-sgp4 2.27 handles them; their residuals are ordinary.
- **First sight of the scoreboard's content.** Two satellites (57525, 68668) stay within about
  2 km of the public prediction for two to three days: no planned trajectory change in the file.
  Four others (100001, 100002, 61940, 65411) diverge to 100-360 km by 72 h: the operator file
  contains planned changes the public element set cannot know about. Which of these is which, at
  what element age, by shell and by Kp, is exactly what the visibility scoreboard measures. No
  figure here is a scoreboard number; seven satellites are a frame check, not a sample.

**Consequences for `score/`.**
- `score/ephem.py` reads the four-line header and four-line records; positions J2000 km, velocities
  km/s, 21 lower-triangular covariance elements in the file's stated UVW frame.
- Propagation via Skyfield's `EarthSatellite` (python-sgp4 underneath); positions taken in GCRS.
- Element age is signed and binned; the "set newer than the epoch" bin is kept separate.
- Evaluation at the file's own record epochs, so no interpolation of the operator trajectory.
