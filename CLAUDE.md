# Ephemera — rules for coding agents

Read `DOCS/concept.md`, `DOCS/decisions.md` and `DOCS/claims-register.md` before writing anything.
Decisions are binding; propose a new decision entry rather than working around one. `DOCS/` and `PLAN.md`
are private: gitignored, on the owner's machine only, never committed. Say so if they are missing here.

## Non-negotiable

1. **Clean-room (D02).** Do not read, import, adapt or "take inspiration from" any repository other
   than this one and the open-source libraries it depends on. If you find yourself about to open a
   sibling folder under `GitHub/`, stop. Propagation: python-sgp4, Skyfield or Orekit. Hashing: the
   standard library. Witnessing: OpenTimestamps and the Wayback Machine. No KMS.
2. **Personal infrastructure only.** Every infrastructure script sources the account guard and
   refuses non-personal cloud account IDs with no override flag.
3. **Raw files are never committed.** `data/raw/` and anything under it is gitignored; raw archives
   live on cold object storage with published hashes.
4. **Claims discipline.** Any user-visible text (site, bulletin, README, docstring that renders) is
   checked against `tools/claims_rules.md`. Prohibited wording is a build failure once the browser
   tests exist.
5. **Never a single ratio against the FCC count (D04). Never "realism" for the overlap scoreboard
   (D05).**
6. **Nothing private in the repository (D23, D24).** It is public. No letter, draft, quote or paraphrase of
   correspondence, no plan naming people to approach, no decision log, no task ledger.

## Engineering rules (in addition to the user's global rules)

- The cheapest probe that can kill the plan runs first. Before building on an assumption about the
  feed, the format, the rate policy, or a library, write it as a probe under `probes/` with a
  measured result and a date.
- Every number that reaches a page carries its as-of date and how it was measured.
- Errors surface loudly. A poller that misses a file logs it, counts it, and publishes the gap; it
  never silently retries into an "installed" state with an empty archive.
- A green flag is not a picture. Anything rendered is verified in a real browser against the built
  site, with the exact inputs pinned.
- Test the caller. A helper with passing tests is not evidence it is wired in; mutate the call site
  and watch a test fail.
- Comments and commit messages describe what the code does, verified by tracing, not what was
  intended.

## Where things go

| Path | Owner | Notes |
|---|---|---|
| `DOCS/`, `PLAN.md` | human, private | gitignored; agents propose edits as decision entries |
| `CORRECTIONS.md` | agents | the public log of anything published and then corrected |
| `probes/` | agents, reviewed | one folder per probe, `README.md` with result and date |
| `archive/` | agents | pollers, hashing, witnessing; no scoring logic |
| `score/` | agents | SGP4 scoring, self-consistency, census; no I/O against live feeds |
| `web/` | agents | static site; no runtime inference, no server |
| `data/` | build output | derived only; never raw |
| `licences/` | human | per-source terms audit |
