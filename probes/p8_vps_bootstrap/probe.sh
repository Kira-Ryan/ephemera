#!/usr/bin/env bash
# P8: can Ephemera run from a datacentre IP? Run on a Linux host, never on the owner's machine.
#
#   CONTACT=you@example.org [PRESIGNED_PUT=<url>] bash probe.sh
#
# Measures, in the order the runbook gives, each one able to kill the plan:
#   8.1 reachability of every endpoint the six components need, with the resolved addresses;
#   8.2 the manifest, its size, and whether If-None-Match returns 304 (D17 rests on it);
#   8.3 the pull rate from this IP, using the real poller (archive/poll.py --limit) at 16 and 32
#       connections, so the number is the production code path and not a curl approximation;
#   8.4 upload throughput to S3 eu-west-1 over a presigned PUT, so no AWS credential touches the host;
#   8.5 the native OpenTimestamps client, which retires the Docker path if it stamps;
#   8.6 Wayback Save-Page-Now from this IP at the witness's 12 s capture gap, watching for the 429.
# Space-Track (8.7) is deliberately not run here: two clients on one account is an owner decision.
#
# Everything lands under $WORK (default ~/p8): probe.log is the full transcript, results.txt the
# key=value summary. Nothing outside $WORK is read or written, so the host's other projects are
# never touched (D02).
set -uo pipefail

WORK="${WORK:-$HOME/p8}"
CONTACT="${CONTACT:?set CONTACT=<email> (goes in the User-Agent, as the poller requires)}"
BASE="${BASE:-https://api.starlink.com/public-files/ephemerides}"
REPO_URL="${REPO_URL:-https://github.com/Kira-Ryan/ephemera.git}"
WAYBACK="https://web.archive.org"

mkdir -p "$WORK"
cd "$WORK" || exit 1
LOG="$WORK/probe.log"
RES="$WORK/results.txt"
: > "$RES"
exec > >(tee -a "$LOG") 2>&1

rec() { echo "$1=$2" >> "$RES"; echo "   -> $1=$2"; }
now() { date -u +%FT%TZ; }
secs() { date +%s.%N; }
elapsed() { awk -v a="$1" -v b="$(date +%s.%N)" "BEGIN{printf \"%.1f\", b-a}"; }

echo "== P8 start $(now) host=$(hostname) kernel=$(uname -srm)"
. /etc/os-release 2>/dev/null && echo "   os: ${PRETTY_NAME:-unknown}"
PUBIP="$(curl -s --max-time 10 https://checkip.amazonaws.com || echo unknown)"
rec public_ip "$PUBIP"
rec os "${PRETTY_NAME:-unknown}"
rec python "$(python3 --version 2>&1)"
rec vcpu "$(nproc)"
rec ram_gb "$(free -g | awk '/Mem/{print $2}')"
rec disk_free_gb_work "$(df -BG "$WORK" | tail -1 | awk '{print $4}' | tr -d G)"

# ------------------------------------------------------------------ 8.1 reachability
echo; echo "== 8.1 reachability $(now)"
probe_host() {  # name url
  local name="$1" url="$2" host
  host="$(echo "$url" | sed -E 's#https?://([^/]+).*#\1#')"
  local addrs; addrs="$(getent ahosts "$host" 2>/dev/null | awk '{print $1}' | sort -u | tr '\n' ' ')"
  local out; out="$(curl -sS -o /dev/null --max-time 25 -w '%{http_code} connect=%{time_connect}s tls=%{time_appconnect}s ip=%{remote_ip}' "$url" 2>&1)"
  echo "   $name: $out  [resolves: ${addrs:-none}]"
  rec "reach_${name}" "$out"
}
probe_host starlink_manifest "$BASE/MANIFEST.txt"
probe_host spacetrack "https://www.space-track.org/"
probe_host wayback "$WAYBACK/"
probe_host s3_euw1 "https://s3.eu-west-1.amazonaws.com/"
probe_host sts "https://sts.amazonaws.com/"
probe_host github "https://github.com/"
probe_host cloudflare_api "https://api.cloudflare.com/client/v4/"
probe_host celestrak "https://celestrak.org/"
probe_host ots_alice "https://alice.btc.calendar.opentimestamps.org/"
probe_host ots_bob "https://bob.btc.calendar.opentimestamps.org/"
probe_host ots_finney "https://finney.calendar.eternitywall.com/"
rec ipv6_default_route "$([ -n "$(ip -6 route show default 2>/dev/null)" ] && echo present || echo none)"

# ------------------------------------------------------------------ 8.3a repo and environment
# The clone comes before 8.2 so the manifest fetch can use the poller's own User-Agent string.
echo; echo "== repo and environment $(now)"
if [ ! -d "$WORK/ephemera/.git" ]; then
  git clone --quiet --depth 1 "$REPO_URL" "$WORK/ephemera" || { rec clone "FAILED"; exit 1; }
fi
rec clone "ok $(git -C "$WORK/ephemera" rev-parse --short HEAD)"
if [ ! -x "$WORK/venv/bin/python" ]; then
  python3 -m venv "$WORK/venv" || { rec venv "FAILED (python3-venv missing?)"; exit 1; }
fi
T0=$(secs)
if "$WORK/venv/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1 && \
   "$WORK/venv/bin/pip" install --quiet -r "$WORK/ephemera/requirements.txt" > "$WORK/pip.log" 2>&1; then
  rec pip_requirements "ok $(elapsed "$T0")s"
else
  rec pip_requirements "FAILED see pip.log"; tail -n 5 "$WORK/pip.log"
fi
PY="$WORK/venv/bin/python"
UA="$(cd "$WORK/ephemera/archive" && "$PY" -c "import poll,sys; print(poll.user_agent(sys.argv[1]))" "$CONTACT")"
echo "   user-agent: $UA"

# ------------------------------------------------------------------ 8.2 manifest and 304
echo; echo "== 8.2 manifest $(now)"
curl -sS -A "$UA" -D "$WORK/manifest.hdr" -o "$WORK/MANIFEST.txt" --max-time 120 \
     -w '%{http_code} %{size_download}B %{time_total}s\n' "$BASE/MANIFEST.txt" | sed 's/^/   GET: /'
ETAG="$(grep -i '^etag:' "$WORK/manifest.hdr" | tr -d '\r' | cut -d' ' -f2-)"
rec manifest_bytes "$(stat -c %s "$WORK/MANIFEST.txt" 2>/dev/null || echo 0)"
rec manifest_lines "$(wc -l < "$WORK/MANIFEST.txt")"
rec manifest_etag "${ETAG:-none}"
rec manifest_sha256 "$(sha256sum "$WORK/MANIFEST.txt" | cut -c1-12)"
if [ -n "$ETAG" ]; then
  rec manifest_conditional "$(curl -sS -A "$UA" -o /dev/null --max-time 60 -H "If-None-Match: $ETAG" -w '%{http_code}' "$BASE/MANIFEST.txt")"
else
  rec manifest_conditional "no etag header"
fi

# ------------------------------------------------------------------ 8.3 pull rate, real poller
# --limit N pulls the first N manifest entries into <spool>/partial/ and exits 3 by design (no root).
# The two slices overlap (first 200 is inside first 400) but go to separate spools, so both are
# fresh downloads; any CDN warming from the first run flatters the second and is noted as such.
pull_slice() {  # workers limit
  local w="$1" n="$2"
  local spool="$WORK/spool_w${w}_n${n}"
  rm -rf "$spool"
  echo; echo "== 8.3 pull $n files at $w connections $(now)"
  local t0; t0=$(secs)
  ( cd "$WORK/ephemera" && "$PY" archive/poll.py --spool "$spool" --workers "$w" --limit "$n" \
      --contact "$CONTACT" --min-free-gb 2 > "$WORK/pull_w${w}_n${n}.log" 2>&1 )
  local rc=$?
  local wall; wall="$(elapsed "$t0")"
  local rec_json; rec_json="$(ls "$spool"/partial/cycle_*/cycle.json 2>/dev/null | head -1)"
  if [ -n "$rec_json" ]; then
    "$PY" - "$rec_json" "$wall" "$w" "$n" "$RES" <<'PYEOF'
import json, sys
c = json.load(open(sys.argv[1])); wall = float(sys.argv[2]); w, n, res = sys.argv[3], sys.argv[4], sys.argv[5]
got, failed, raw = c.get("files_recorded", 0), c.get("files_failed", 0), c.get("bytes_raw", 0)
print(f"   recorded={got} failed={failed} bytes_raw={raw:,} wall={wall:.1f}s")
print(f"   -> {got/wall:.2f} files/s, {raw/wall/1e6:.1f} MB/s raw, projected full cycle (11,134 files) = {11134/(got/wall)/60:.1f} min")
with open(res, "a") as f:
    f.write(f"pull_w{w}_n{n}_files_per_s={got/wall:.2f}\npull_w{w}_n{n}_MB_per_s={raw/wall/1e6:.1f}\n"
            f"pull_w{w}_n{n}_failed={failed}\npull_w{w}_n{n}_projected_cycle_min={11134/(got/wall)/60:.1f}\n")
PYEOF
  else
    rec "pull_w${w}_n${n}" "NO RECORD rc=$rc (see pull log)"; tail -n 8 "$WORK/pull_w${w}_n${n}.log"
  fi
  echo "   http errors in pull log: $(grep -cE 'ERROR|WARNING' "$WORK/pull_w${w}_n${n}.log")"
  grep -E 'ERROR|WARNING' "$WORK/pull_w${w}_n${n}.log" | sed -E 's/^.{0,24}//' | cut -c1-110 | sort | uniq -c | sort -rn | head -5
  rec "pull_w${w}_n${n}_rc" "$rc"
}
pull_slice 16 200
pull_slice 32 400

# ------------------------------------------------------------------ 8.4 S3 upload over a presigned PUT
echo; echo "== 8.4 S3 upload $(now)"
if [ -n "${PRESIGNED_PUT:-}" ]; then
  dd if=/dev/urandom of="$WORK/blob.bin" bs=1M count=2048 status=none
  out="$(curl -sS -o /dev/null --max-time 1800 -T "$WORK/blob.bin" -w '%{http_code} %{speed_upload} %{time_total}' "$PRESIGNED_PUT")"
  code="${out%% *}"; rest="${out#* }"; speed="${rest%% *}"; tt="${rest#* }"
  mbs="$(awk -v s="$speed" 'BEGIN{printf "%.1f", s/1000000}')"
  echo "   PUT 2 GiB: http=$code speed=${mbs} MB/s total=${tt}s"
  rec s3_put_http "$code"
  rec s3_put_MB_per_s "$mbs"
  rm -f "$WORK/blob.bin"
else
  rec s3_put "skipped (no PRESIGNED_PUT)"
fi

# ------------------------------------------------------------------ 8.5 native OpenTimestamps
echo; echo "== 8.5 native ots $(now)"
if "$WORK/venv/bin/pip" install --quiet opentimestamps-client > "$WORK/ots-pip.log" 2>&1; then
  OTS="$WORK/venv/bin/ots"
  rec ots_version "$("$OTS" --version 2>&1 | head -1)"
  echo "p8 probe $(now)" > "$WORK/stampme.txt"
  t0=$(secs)
  if "$OTS" stamp "$WORK/stampme.txt" > "$WORK/ots-stamp.log" 2>&1 && [ -s "$WORK/stampme.txt.ots" ]; then
    rec ots_stamp "ok $(elapsed "$t0")s, proof $(stat -c %s "$WORK/stampme.txt.ots") bytes"
    "$OTS" info "$WORK/stampme.txt.ots" 2>&1 | head -n 6 | sed 's/^/   /'
  else
    rec ots_stamp "FAILED"; tail -n 5 "$WORK/ots-stamp.log"
  fi
else
  rec ots_install "FAILED see ots-pip.log"
fi

# ------------------------------------------------------------------ 8.6 Wayback at the witness's gap
echo; echo "== 8.6 wayback $(now)"
( cd "$WORK/ephemera/archive" && "$PY" - "$WAYBACK" "$BASE" "$WORK/MANIFEST.txt" "$UA" "$WORK/results.txt" <<'PYEOF'
import hashlib, json, sys, time, requests
sys.path.insert(0, ".")
import witness  # the production capture(): submit, read timestamp, fetch id_ copy, re-hash
wayback, base, manifest, ua, res = sys.argv[1:6]
sha = hashlib.sha256(open(manifest, "rb").read()).hexdigest()
s = requests.Session(); s.headers["User-Agent"] = ua
stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
first_429 = None
for i in range(3):
    url = f"{base}/MANIFEST.txt?probe=p8-{stamp}-{i}"
    t0 = time.time()
    e = witness.capture(s, wayback, url, sha)
    dt = time.time() - t0
    ok = "error" not in e
    print(f"   capture {i}: {'ok ts=' + e['timestamp'] if ok else 'ERROR ' + e['error'][:90]}  ({dt:.0f}s)")
    if not ok and "429" in e["error"] and first_429 is None:
        first_429 = i
    if i < 2:
        time.sleep(12.0)
with open(res, "a") as f:
    f.write(f"wayback_first_429_at=" + ("none in 3" if first_429 is None else str(first_429)) + "\n")
PYEOF
)

# ------------------------------------------------------------------ done
echo; echo "== P8 end $(now)"
echo "== results.txt"; sed 's/^/   /' "$RES"
