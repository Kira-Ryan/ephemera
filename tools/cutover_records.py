#!/usr/bin/env python3
"""Phase B of the cutover (DOCS/migration-runbook.md section 6, steps 4 and 5): bring the records
the Windows host held into the VPS spool from a staging directory, one file at a time, under the
ownership table, and check the result.

  plan  STAGING SPOOL   print every action, change nothing
  apply STAGING SPOOL   refuse if anything would stop, otherwise do it, then run the checks
  check STAGING SPOOL   the checks only

The table, as code: a cycle only Windows had is copied whole. A cycle both hosts had keeps the
VPS's cycle.json, etag_cache.json, MANIFEST.txt and root.txt after the two root.txt are found byte
for byte identical, takes Windows's root.txt.ots, root.txt.ots.bak and witness.json as a set (same
root; the attestation the site has already published) unless the VPS's witness record holds
verified captures Windows's lacks, in which case the VPS's set stays, and takes Windows's
ship.json only if it records shipped and the VPS's is not a first-hand upload record that Windows
merely adopted.
daily/, gp/ and score/ are copied whole; an existing file may only be identical. heartbeats.jsonl
is the union of both, by utc, never an overwrite. files/ is never touched, and a staging directory
that contains any is refused outright. A root that differs between hosts, a cycle only one host
has a root for, an unknown record file, or a different existing file under daily/ gp/ score/ each
stop the whole apply before anything is written: those are for a person to decide.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

VPS_KEEPS = ("cycle.json", "etag_cache.json", "MANIFEST.txt", "root.txt")
WINDOWS_WINS = ("root.txt.ots", "root.txt.ots.bak", "witness.json")
KNOWN = set(VPS_KEEPS) | set(WINDOWS_WINS) | {"ship.json"}
WHOLE_DIRS = ("daily", "gp", "score")
IGNORED = {"heartbeat.json", "outbox", "partial"}


@dataclass
class Action:
    verb: str          # copy | keep | merge | stop
    src: Path | None
    dst: Path | None
    why: str

    def __str__(self) -> str:
        return f"{self.verb:5} {self.src if self.src else '-'} -> {self.dst if self.dst else '-'}  ({self.why})"


def same_bytes(a: Path, b: Path) -> bool:
    return a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()


def shipped_state(path: Path) -> dict:
    """The `shipped` block of a ship.json, or {} when there is none or the file is absent."""
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")).get("shipped") or {})
    except (OSError, ValueError):
        return {}


def witness_score(path: Path) -> tuple[int, int]:
    """How complete a witness record is: (manifest copy verified, sample copies verified). A file
    that is absent or unreadable scores below any real record."""
    try:
        wb = json.loads(path.read_text(encoding="utf-8")).get("wayback") or {}
    except (OSError, ValueError):
        return (-1, -1)
    samples = wb.get("samples") or {}
    return (1 if (wb.get("manifest") or {}).get("verified") else 0,
            sum(1 for e in samples.values() if isinstance(e, dict) and e.get("verified")))


def record_summary(path: Path) -> str:
    try:
        r = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return f"unreadable ({e})"
    return (f"status={r.get('status')} files_recorded={r.get('files_recorded')} files_failed={r.get('files_failed')} "
            f"manifest_anomalies={len(r.get('manifest_anomalies') or [])} root={str(r.get('merkle_root'))[:12]}")


def plan_cycle(cdir: Path, dst: Path) -> list[Action]:
    if (cdir / "files").exists():
        raise SystemExit(f"{cdir}: staging holds a files/ directory; the tar was made wrong, nothing applied")
    names = sorted(p.name for p in cdir.iterdir())
    unknown = [n for n in names if n not in KNOWN]
    if unknown:
        return [Action("stop", cdir / unknown[0], None, f"unknown record file(s) {unknown}")]
    if not dst.exists():
        return [Action("copy", cdir / n, dst / n, "cycle only on Windows") for n in names]
    sr, dr = cdir / "root.txt", dst / "root.txt"
    if sr.exists() != dr.exists():
        who = "Windows" if sr.exists() else "the VPS"
        return [Action("stop", sr, dr, f"only {who} has a root for this cycle; Windows {record_summary(cdir / 'cycle.json')}; "
                                       f"VPS {record_summary(dst / 'cycle.json')}")]
    if sr.exists() and not same_bytes(sr, dr):
        return [Action("stop", sr, dr, f"root.txt differs between hosts; Windows {record_summary(cdir / 'cycle.json')}; "
                                       f"VPS {record_summary(dst / 'cycle.json')}")]
    actions = []
    # The proof and the witness record describe each other, so they move or stay as one set. On 3 Oct
    # 2026 two overlap cycles had a sample Windows was refused outright (the URL's daily capture quota
    # was spent by the VPS's retries) and the VPS had verified: Windows's record must not replace that.
    w_ours, w_theirs = witness_score(dst / "witness.json"), witness_score(cdir / "witness.json")
    vps_set_stays = w_ours > w_theirs
    for n in names:
        s = cdir / n
        if n in VPS_KEEPS:
            actions.append(Action("keep", s, dst / n, "cycle on both hosts; the VPS's stays"))
        elif n in WINDOWS_WINS:
            if vps_set_stays:
                actions.append(Action("keep", s, dst / n, f"the VPS's witness record is the more complete one "
                                                          f"({w_ours[1]} verified samples against {w_theirs[1]}); its proof and captures stay"))
            else:
                actions.append(Action("copy", s, dst / n, "same root; Windows's proof and captures win"))
        elif n == "ship.json":
            theirs, ours = shipped_state(s), shipped_state(dst / n)
            if not theirs:
                actions.append(Action("keep", s, dst / n, "Windows never shipped it; the VPS's ship.json stays"))
            elif ours and not ours.get("adopted_from_remote_utc") and theirs.get("adopted_from_remote_utc"):
                actions.append(Action("keep", s, dst / n, "the VPS uploaded this one itself and Windows adopted it; "
                                                          "the first-hand record stays"))
            else:
                actions.append(Action("copy", s, dst / n, "Windows recorded the cycle shipped"))
    return actions


def plan(staging: Path, spool: Path) -> list[Action]:
    actions: list[Action] = []
    for cdir in sorted(staging.glob("cycle_*")):
        if cdir.is_dir():
            actions.extend(plan_cycle(cdir, spool / cdir.name))
    for sub in WHOLE_DIRS:
        base = staging / sub
        if not base.exists():
            continue
        for f in sorted(p for p in base.rglob("*") if p.is_file()):
            dst = spool / sub / f.relative_to(base)
            if not dst.exists():
                actions.append(Action("copy", f, dst, f"{sub}/ copied whole"))
            elif same_bytes(f, dst):
                actions.append(Action("keep", f, dst, "already there, identical"))
            else:
                actions.append(Action("stop", f, dst, f"a different {sub}/ file already exists on the VPS"))
    hb = staging / "heartbeats.jsonl"
    if hb.exists():
        actions.append(Action("merge", hb, spool / "heartbeats.jsonl", "union of both hosts' heartbeats, by utc"))
    for name in sorted(p.name for p in staging.iterdir()):
        if name in IGNORED:
            actions.append(Action("keep", staging / name, None, "not part of the copy"))
        elif name not in WHOLE_DIRS and name != "heartbeats.jsonl" and not name.startswith("cycle_"):
            actions.append(Action("stop", staging / name, None, "unexpected entry in staging"))
    return actions


def hb_key(line: str) -> str:
    try:
        return str(json.loads(line).get("utc") or "")
    except ValueError:
        return ""


def merge_heartbeats(src: Path, dst: Path) -> tuple[int, int]:
    """Union by exact line, ordered by utc. Read the live file twice around the write so a tick the
    watcher appended meanwhile is not lost; the window that remains is the os.replace itself."""
    def lines(p: Path) -> list[str]:
        return [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []
    theirs = lines(src)
    before = lines(dst)
    merged = sorted(set(before) | set(theirs), key=hb_key)
    tmp = dst.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(merged) + "\n", encoding="utf-8")
    late = [l for l in lines(dst) if l not in set(merged)]
    if late:
        with open(tmp, "a", encoding="utf-8") as f:
            f.write("\n".join(late) + "\n")
    os.replace(tmp, dst)
    return len(before), len(merged) + len(late)


def copy_atomic(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def apply(actions: list[Action], spool: Path) -> None:
    stops = [a for a in actions if a.verb == "stop"]
    if stops:
        for a in stops:
            print("STOP", a)
        raise SystemExit(f"{len(stops)} thing(s) a person must decide; nothing was written")
    for a in actions:
        if a.verb == "copy":
            copy_atomic(a.src, a.dst)
        elif a.verb == "merge":
            before, after = merge_heartbeats(a.src, a.dst)
            print(f"heartbeats: {before} lines on the VPS -> {after} after the union")
    print(f"applied: {sum(1 for a in actions if a.verb == 'copy')} copied, {sum(1 for a in actions if a.verb == 'keep')} kept")


def check(staging: Path, spool: Path) -> list[str]:
    problems = []
    for cdir in sorted(spool.glob("cycle_*")):
        if (cdir / "root.txt").exists() and not (cdir / "root.txt.ots").exists():
            problems.append(f"{cdir.name}: root.txt without root.txt.ots")
        try:
            rec = json.loads((cdir / "cycle.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if rec.get("status") == "complete":
            ship = cdir / "ship.json"
            try:
                shipped = bool((json.loads(ship.read_text(encoding="utf-8")).get("shipped") or {}))
            except (OSError, ValueError):
                shipped = False
            if not shipped:
                problems.append(f"{cdir.name}: complete but ship.json does not record shipped")
    for sub in WHOLE_DIRS:
        base = staging / sub
        if base.exists():
            for f in (p for p in base.rglob("*") if p.is_file()):
                if not (spool / sub / f.relative_to(base)).exists():
                    problems.append(f"{sub}/{f.relative_to(base)}: missing from the spool")
    s_days = {p.name for p in (staging / "daily").iterdir()} if (staging / "daily").exists() else set()
    v_days = {p.name for p in (spool / "daily").iterdir()} if (spool / "daily").exists() else set()
    if s_days - v_days:
        problems.append(f"daily: {sorted(s_days - v_days)} on Windows, not on the VPS")
    hb_s, hb_v = staging / "heartbeats.jsonl", spool / "heartbeats.jsonl"
    if hb_s.exists():
        have = set(hb_v.read_text(encoding="utf-8").splitlines()) if hb_v.exists() else set()
        missing = [l for l in hb_s.read_text(encoding="utf-8").splitlines() if l.strip() and l not in have]
        if missing:
            problems.append(f"heartbeats: {len(missing)} Windows line(s) missing from the VPS file")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=["plan", "apply", "check"])
    ap.add_argument("staging", type=Path)
    ap.add_argument("spool", type=Path)
    args = ap.parse_args(argv)
    if not args.staging.is_dir() or not args.spool.is_dir():
        raise SystemExit("staging and spool must both be existing directories")
    if args.mode in ("plan", "apply"):
        actions = plan(args.staging, args.spool)
        for a in actions:
            if args.mode == "plan" or a.verb == "stop":
                print(a)
        counts = {v: sum(1 for a in actions if a.verb == v) for v in ("copy", "keep", "merge", "stop")}
        print("plan:", counts)
        if args.mode == "plan":
            return 1 if counts["stop"] else 0
        apply(actions, args.spool)
    problems = check(args.staging, args.spool)
    for p in problems:
        print("CHECK", p)
    print(f"check: {len(problems)} problem(s). Still to run by hand: archive/verify.py on the oldest cycle, the newest "
          f"Windows-only cycle and one overlap cycle; and list-object-versions on the overlap cycles' files.tar keys.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
