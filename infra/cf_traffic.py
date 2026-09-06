#!/usr/bin/env python3
"""Read-only: the zone's traffic for the last N days, by day and by country, from Cloudflare's
analytics API. Runs the account guard first like every other Cloudflare script here.

  python infra/cf_traffic.py            the last 7 days
  python infra/cf_traffic.py --days 30

Country figures are Cloudflare's own aggregates by request origin; nothing here identifies a
visitor. The token needs Analytics:Read on the zone in addition to what the deploy token carries;
without it Cloudflare refuses the read and this says so and exits 2.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard_cf  # noqa: E402

API = "https://api.cloudflare.com/client/v4"
QUERY = """query($zone: String!, $since: String!, $until: String!) {
  viewer { zones(filter: {zoneTag: $zone}) {
    days: httpRequests1dGroups(limit: 100, orderBy: [date_ASC], filter: {date_geq: $since, date_leq: $until}) {
      dimensions { date }
      sum { requests pageViews countryMap { clientCountryName requests } }
      uniq { uniques }
    }
  } }
}"""


def call(path: str, body: dict | None = None) -> dict:
    hdr = {"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}", "Content-Type": "application/json"}
    req = urllib.request.Request(API + path, headers=hdr, method="POST" if body else "GET",
                                 data=json.dumps(body).encode() if body else None)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args(argv)
    try:
        guard_cf.enforce()
    except guard_cf.GuardRefused as e:
        print(e, file=sys.stderr)
        return 1
    zone = call(f"/zones?name={guard_cf.ZONE}")["result"][0]["id"]
    since, until = (date.today() - timedelta(days=args.days)).isoformat(), date.today().isoformat()
    r = call("/graphql", {"query": QUERY, "variables": {"zone": zone, "since": since, "until": until}})
    if r.get("errors"):
        msg = r["errors"][0].get("message", "")
        if "analytics.read" in msg:
            print("cf_traffic: the token cannot read analytics for this zone. Add the permission "
                  "'Zone > Analytics > Read' to it (or to a separate read-only token in personal.env) and run "
                  "again. Cloudflare said: " + msg, file=sys.stderr)
        else:
            print("cf_traffic: API error: " + json.dumps(r["errors"])[:600], file=sys.stderr)
        return 2
    days = r["data"]["viewer"]["zones"][0]["days"]
    if not days:
        print(f"no traffic recorded for {guard_cf.ZONE} between {since} and {until}")
        return 0
    tot_req = sum(d["sum"]["requests"] for d in days)
    tot_pv = sum(d["sum"]["pageViews"] for d in days)
    print(f"{guard_cf.ZONE}, {since} to {until} (Cloudflare zone analytics, as of {date.today().isoformat()})")
    print(f"{'date':<12}{'requests':>10}{'page views':>12}{'unique visitors':>17}")
    for d in days:
        print(f"{d['dimensions']['date']:<12}{d['sum']['requests']:>10}{d['sum']['pageViews']:>12}{d['uniq']['uniques']:>17}")
    print(f"{'total':<12}{tot_req:>10}{tot_pv:>12}{'per day, not summed':>17}")
    by_country: dict[str, int] = {}
    for d in days:
        for c in d["sum"]["countryMap"]:
            by_country[c["clientCountryName"]] = by_country.get(c["clientCountryName"], 0) + c["requests"]
    print(f"\nrequests by country, top {args.top} of {len(by_country)}:")
    for k, v in sorted(by_country.items(), key=lambda kv: -kv[1])[:args.top]:
        print(f"  {k:<6}{v:>8}  {100 * v / max(tot_req, 1):5.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
