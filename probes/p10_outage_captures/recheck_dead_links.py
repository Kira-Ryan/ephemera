"""Read-only. Re-fetches the manifest copies that returned 404 on 5 Nov, plus those missing from the
index today, and compares each with the digest the ledger published."""
import gzip
import hashlib
import json
import re
import sys
import time

import requests

S = sys.argv[1]
led = json.load(open(S + "/ledger_now.json", encoding="utf-8"))
rows = json.load(open(S + "/p10/cdx_all.json"))[1:]
indexed = {m.group(1) for r in rows for m in [re.search(r"cycle=([0-9a-f]{12})", r[1])] if m}
DEAD_5_NOV = """1555093aa225 6b7d86853540 b10586a473bf ef0599f4eb00 0229c43347fc d98c9ca2bdf4 a879013f0100
754cd83ec71d a648b38e76b9 50874ace28b4 2288c26bbeea eaa945b04114 e91846ed183a cdc930461493 a80375a03051
9e87c37c7507 21c30f522c4f 6637e5bd6772""".split()
s = requests.Session()
s.headers["User-Agent"] = "ephemera-verify/1.0 (+https://ephemera.space)"
out = []
for c in sorted(led["cycles"], key=lambda x: x["first_seen_utc"]):
    sha = c["cycle"][6:]
    wb = c["wayback"]
    if not wb["manifest_verified"] or not wb["manifest_copy_url"]:
        continue
    was_dead = sha in DEAD_5_NOV
    in_index = sha in indexed
    if not was_dead and in_index:
        continue
    if c["first_seen_utc"] < "2026-10-01":
        continue
    time.sleep(2)
    r = s.get(wb["manifest_copy_url"], timeout=180)
    body = r.content
    raw = gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body
    ok = r.status_code == 200 and hashlib.sha256(raw).hexdigest() == c["manifest_sha256"]
    out.append({"cycle": sha, "first_seen": c["first_seen_utc"], "was_dead_5_nov": was_dead, "in_index_now": in_index,
                "http": r.status_code, "digest_ok": ok})
    print(sha, c["first_seen_utc"][:10], "dead-5-Nov" if was_dead else "-", "indexed" if in_index else "not-indexed", r.status_code, "ok" if ok else "NO", flush=True)
json.dump(out, open(S + "/p10/recheck_dead.json", "w"), indent=0)
print("was dead on 5 Nov:", sum(x["was_dead_5_nov"] for x in out), "now serving and matching:", sum(x["was_dead_5_nov"] and x["digest_ok"] for x in out))
print("not indexed today:", sum(not x["in_index_now"] for x in out), "serving and matching:", sum((not x["in_index_now"]) and x["digest_ok"] for x in out))
