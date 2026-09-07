#!/usr/bin/env python3
"""The site's pages, rendered from the ledger that web/build.py assembles (D20 for the page map).

Six pages share one chrome: masthead, tab bar, colophon with the register's four required caveats,
and the build stamp. The front page is a fixed-size spread and never grows. Anything that gains a
row per cycle lives on /scored/ or /archive/, in one section per UTC month, with row ids that never
move once published (`s-<sha12>`, `c-<sha12>`).

Layout is a centred frame of twelve columns on one baseline (`--base`). A block names the columns it
occupies (`z-prose`, `z-side`, `z-full`, `z-c1..3`); a `z-side` written straight after a `z-prose`
lands beside it, so the source order reads top to bottom on a phone and as bands on a desktop.
Hierarchy comes from size and placement, not boxes. Nothing here reads the spool; every figure
comes from the ledger and carries the ledger's as-of time.
"""
from __future__ import annotations

import html
import math
import re
from datetime import datetime, timedelta, timezone

import brand

SITE = "https://ephemera.space/"
LOST_KM = 1000
STRIP_DAYS = 30
CONTACT_NAME = "Kira Ryan"
CONTACT_MAIL = "KiraRyan27@gmail.com"
CONTACT_LINKEDIN = "https://www.linkedin.com/in/kira-ryan/"
DESCRIPTION = ("An archive of the public Starlink ephemerides, hashed and anchored in Bitcoin, with a "
               "daily measure of what the public satellite catalogue can see.")

# (path, tab label). Order is the tab order. The globe is a page of its own that borrows this chrome.
PAGES = (("", "Front page"), ("finding/", "The finding"), ("scored/", "Scored cycles"),
         ("archive/", "The archive"), ("check/", "Check it"), ("globe/", "The globe"))

# The four caveats DOCS/claims-register.md requires on every page, verbatim, plus the two house
# sentences. tools/claims_lint.py asserts the four on every built page.
CAVEATS = ("Operator ephemerides are predictions, not observations. Starlink is the only operator with public "
           "covariance; other operators enter via CelesTrak SupGP without covariance. Public GP data is too noisy "
           "to test sub-metre covariance; the self-consistency scoreboard measures "
           "prediction-versus-later-prediction. That scoreboard is not built yet. Inputs are archived by this "
           "project and witnessed by OpenTimestamps and the Wayback Machine; they are not re-fetchable from the "
           "source after one cycle. Every figure above carries the build time it was true at. Gapped or lost "
           "items are printed, never hidden.")


# ---------------------------------------------------------------- small helpers


def esc(x) -> str:
    return html.escape(str(x))


def utc_min(s: str | None) -> str:
    return (s or "?")[:16].replace("T", " ")


def parse_utc(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def pct(x: float) -> str:
    """A share as a percentage. Small shares keep a decimal: 41 of 11,090 is 0.4 percent, and
    printing that as 0% would say the opposite of what the number means."""
    v = 100 * x
    return f"{v:.1f}%" if 0 < v < 1 else f"{v:.0f}%"


def gb(n: int) -> str:
    return f"{n / 1e9:,.0f}"


def month_label(ym: str) -> str:
    return datetime.strptime(ym, "%Y-%m").strftime("%B %Y")


def headline_report(reports: list[dict]) -> dict | None:
    """The newest report whose catalogue snapshot was fetched before the cycle, with rows scored.

    A cycle paired with a later snapshot is scored with hindsight: the element set already knows what
    the satellite did during the file. Those numbers are not comparable and must never become the
    headline, however recent the report is."""
    return next((r for r in reports if r["snapshot_relation"] == "before_cycle" and r["at_file_start"]), None)


def newer_not_comparable(reports: list[dict], head: dict) -> str:
    """A sentence for the headline stamp when cycles scored after the headline cycle could not
    supply it, so the page never reads as if the headline cycle were the newest scored one. Empty
    when the headline is the newest report."""
    newer = [r for r in reports if r["first_seen_utc"] > head["first_seen_utc"]]
    if not newer:
        return ""
    why = no_headline_reason(newer).removeprefix("No comparable cycle yet: ").removesuffix(", listed on the scored page.")
    return (f" {len(newer)} newer scored {'cycle is' if len(newer) == 1 else 'cycles are'} not comparable "
            f"({why}), listed on the scored page.")


def no_headline_reason(reports: list[dict]) -> str:
    """Why the front page and the finding carry no headline: each report is counted under the one
    thing that disqualified it, so a cycle with nothing scored, or one scored before the headline
    existed, is never described as a hindsight pairing."""
    if not reports:
        return "No cycle has been scored yet."
    empty = sum(1 for r in reports if r["overall"] is None)
    hind = sum(1 for r in reports if r["overall"] is not None and r["snapshot_relation"] == "after_cycle")
    early = sum(1 for r in reports if r["overall"] is not None and r["snapshot_relation"] == "before_cycle"
                and not r["at_file_start"])
    unpaired = len(reports) - empty - hind - early
    parts = []
    if hind:
        parts.append(f"{hind} scored with hindsight")
    if empty:
        parts.append(f"{empty} with nothing scored")
    if early:
        parts.append(f"{early} scored before the comparable headline existed")
    if unpaired:
        parts.append(f"{unpaired} with the pairing not recorded")
    return f"No comparable cycle yet: {', '.join(parts)}, listed on the scored page."


def witness_defect(c: dict) -> str | None:
    """What went wrong with the independent copy, or None. Mirrors web/build.py's rule; the ledger
    carries the raw states, so the page derives the same verdict from the same fields."""
    wb = c["wayback"]
    if not wb.get("attempted"):
        return None
    if wb["skipped"]:
        return "no independent copy was made"
    if not wb["manifest_verified"]:
        return ("the manifest was never captured" if not wb["manifest_captured"]
                else "the archived manifest copy is another cycle's file")
    if wb["losses"]:
        return f"{wb['losses']} of {wb['samples_total']} sample captures were lost"
    if wb["samples_total"] and wb["samples_verified"] < wb["samples_total"]:
        return f"only {wb['samples_verified']} of {wb['samples_total']} samples verified"
    return None


# ---------------------------------------------------------------- the stylesheet

CSS = """
  :root {
    --bg: #090c17; --surface: #111629; --surface-2: #171d33;
    --rule: #3d4a75; --rule-soft: #283152;
    --ink: #eceada; --ink-soft: #b9b7c6; --ink-faint: #8f8da0;
    --accent: #ffb347; --accent-lit: #ffcd80; --accent-rule: #9d7034;
    --held: #6fd39a; --warn: #ffb347; --bad: #ff7a7a;
    --km-1: #7fd4ff; --km-10: #ffe08a; --km-30: #ff8c42; --km-far: #ff4d5e; --km-lost: #c86bff;
    --serif: Georgia, 'Iowan Old Style', Charter, 'Palatino Linotype', 'Times New Roman', serif;
    --mono: ui-monospace, 'Cascadia Mono', 'SF Mono', Menlo, Consolas, 'DejaVu Sans Mono', monospace;

    /* One baseline for everything vertical. Named --base, not --line: the globe page uses --line
       for a colour, and the tab bar is injected into that page. */
    --base: 1.75rem; --half: .875rem; --base-s: 1.3125rem;
    --frame: 78rem; --outer: clamp(1.25rem, 6vw, 5rem); --gutter: var(--base); --measure: 60ch;
    --t-body: 1.125rem; --t-lede: 1.25rem; --t-deck: 1.5rem; --t-h2: 2rem; --t-foot: .9375rem;
    --t-small: .875rem; --t-cap: .8125rem; --t-pull: 4.375rem;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  html { scroll-behavior: smooth; -webkit-text-size-adjust: 100%; }
  body { background: var(--bg); color: var(--ink); font: var(--t-body)/var(--base) var(--serif);
         font-variant-numeric: tabular-nums lining-nums; }

  /* The frame: the full 78rem until the viewport is too narrow, then the viewport less two margins. */
  .page { width: min(var(--frame), calc(100% - 2 * var(--outer))); margin: 0 auto;
          padding: var(--base) 0 calc(3 * var(--base));
          display: grid; grid-template-columns: repeat(12, minmax(0, 1fr));
          column-gap: var(--gutter); row-gap: 0; align-items: start; }
  .page > * { min-width: 0; }

  /* Zones. A block names the columns it occupies; rows are never named. A .z-side placed after a
     .z-prose lands on the same row; the next .z-prose or .z-full starts a new one. */
  .z-full  { grid-column: 1 / -1; }
  .z-prose { grid-column: 1 / span 6; }
  .z-wide  { grid-column: 1 / span 8; }
  .z-side  { grid-column: 8 / span 5; }
  .z-c1 { grid-column: 1 / span 4; } .z-c2 { grid-column: 5 / span 4; } .z-c3 { grid-column: 9 / span 4; }
  .z-prose > p, .z-prose > ul, .z-prose > ol { max-width: var(--measure); }

  p, ul, ol { margin-bottom: var(--base); }
  ul, ol { margin-left: 1.25rem; }
  .fine, .dim, .note, .more, figcaption { font-size: var(--t-small); line-height: var(--base-s); }
  p.fine, p.dim, p.more, .note p, .note ul { margin-bottom: var(--base-s); }
  .z-prose > :last-child, .z-side > :last-child, .note > :last-child { margin-bottom: 0; }
  .z-prose, .z-side, .z-wide, figure.z-full, .tablewrap { margin-bottom: var(--base); }

  a { color: var(--accent); text-decoration: underline; text-decoration-thickness: 1px;
      text-underline-offset: .18em; text-decoration-color: var(--accent-rule); }
  a:hover { color: var(--accent-lit); text-decoration-color: var(--accent-lit); }
  a:focus-visible, summary:focus-visible, input:focus-visible { outline: 2px solid var(--accent-lit); outline-offset: 3px; }
  b, strong { font-weight: 700; color: var(--ink); }
  code { font: .85em var(--mono); color: var(--accent-lit); word-break: break-all; }
  .mono { font-family: var(--mono); font-size: .9em; }
  .skip { position: absolute; left: -9999px; }
  .skip:focus { left: var(--outer); top: var(--half); background: var(--surface-2); padding: var(--half); z-index: 9; }
  tr[id], .section[id], [id].col { scroll-margin-top: calc(2 * var(--base)); }

  /* masthead: mark and wordmark left, the build stamp right; then the tab bar on a rule */
  .masthead { grid-column: 1 / -1; display: flex; align-items: center; flex-wrap: wrap;
              gap: var(--half) var(--base); padding-bottom: var(--half); }
  .mark { flex: none; }
  .masthead h1 { font: 400 1.75rem/1.75rem var(--mono); letter-spacing: .26em; margin-right: -.26em;
                 text-transform: uppercase; }
  .masthead h1 a { color: var(--accent); text-decoration: none; }
  .masthead .where { margin-left: auto; text-align: right; font: var(--t-cap)/var(--base-s) var(--mono);
                     letter-spacing: .1em; text-transform: uppercase; color: var(--ink-faint); }
  .standfirst { grid-column: 1 / -1; font: var(--t-cap)/var(--base-s) var(--mono); color: var(--ink-faint);
                margin: 0 0 var(--half); max-width: none; }

  .tabs { grid-column: 1 / -1; display: flex; flex-wrap: wrap; column-gap: var(--base);
          border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule-soft);
          margin-bottom: calc(2 * var(--base));
          font: var(--t-cap)/var(--base-s) var(--mono); letter-spacing: .1em; text-transform: uppercase; }
  .tabs a { color: var(--ink-faint); text-decoration: none; margin-top: -1px; border-top: 2px solid transparent;
            padding: calc(.375 * var(--base) - 1px) 0 calc(.375 * var(--base)); }
  .tabs a:hover { color: var(--ink); }
  .tabs a[aria-current="page"] { color: var(--accent); border-top-color: var(--accent); }

  /* the opening: standfirst beside the pull figures */
  .deck { font: var(--t-deck)/calc(1.25 * var(--base)) var(--serif); max-width: 40ch; margin-bottom: var(--base); }
  .deck strong { color: var(--accent); font-weight: 400; }
  .pulls { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: var(--base) var(--gutter); }
  .pulls > .more { grid-column: 1 / -1; }
  .pull b { display: block; font: 400 var(--t-pull)/calc(3 * var(--base)) var(--serif); color: var(--ink);
            letter-spacing: -.02em; white-space: nowrap; }
  .pull b.held { color: var(--held); } .pull b.warnk { color: var(--warn); }
  .pull.long b { font-size: 2.75rem; line-height: calc(2 * var(--base)); }
  .pull span { display: block; font: var(--t-small)/var(--base-s) var(--serif); color: var(--ink-soft); max-width: 26ch; }
  .pull small { display: block; font: var(--t-cap)/var(--base-s) var(--mono); color: var(--ink-faint);
                letter-spacing: .06em; text-transform: uppercase; }

  /* section heads: a rule across the frame, the head in the text column, the stamp in the margin */
  .section { grid-column: 1 / -1; display: grid; grid-template-columns: subgrid; column-gap: var(--gutter);
             align-items: baseline; margin: var(--base) 0 var(--base);
             border-top: 1px solid var(--rule); padding-top: calc(var(--half) - 1px); }
  .section h2 { grid-column: 1 / span 6; font: 400 var(--t-h2)/calc(1.5 * var(--base)) var(--serif); color: var(--ink); }
  .section .stamp { grid-column: 8 / span 5; margin: 0; font: var(--t-cap)/var(--base-s) var(--mono); color: var(--ink-faint); }
  .section .stamp b { color: var(--ink-soft); font-weight: 400; }
  .tabs + .section, .standfirst + .section { margin-top: 0; }
  h3 { font: var(--t-cap)/var(--base-s) var(--mono); letter-spacing: .1em; text-transform: uppercase;
       color: var(--ink-faint); margin-bottom: 0; }

  .lede { font: var(--t-lede)/var(--base) var(--serif); }
  .lede b { color: var(--accent); }
  .dim, .more, .note { color: var(--ink-soft); }
  .fine { color: var(--ink-faint); }
  .note ul { list-style: none; margin-left: 0; }
  .note li { margin-bottom: 0; }
  .warnk { color: var(--warn); } .held { color: var(--held); } .bad { color: var(--bad); }

  figure { margin: 0 0 var(--base); }
  figure svg { display: block; width: 100%; height: auto; }
  figcaption { margin-top: var(--half); color: var(--ink-faint); max-width: var(--measure); }
  .curve, .history { overflow-x: auto; }
  .curve svg, .history svg { min-width: 24rem; }
  .strip .kept { fill: var(--held); } .strip .warn { fill: var(--warn); } .strip .miss { fill: var(--bad); }
  .strip .pending { fill: var(--ink-faint); } .strip .pulling { fill: none; stroke: var(--ink-faint); stroke-width: 1.5; }
  .strip a:focus-visible rect { stroke: var(--accent-lit); stroke-width: 2; }
  .strip text, .curve text, .history text { font: 11px var(--mono); fill: var(--ink-faint); }
  .curve .grid, .history .grid { stroke: var(--rule-soft); }
  .curve .line { fill: none; stroke: var(--accent); stroke-width: 2; }
  .curve .dot, .history .live { fill: var(--accent); }
  .history .hind { fill: none; stroke: var(--accent); stroke-width: 1.5; }
  .curve .val { fill: var(--ink); }

  /* tables: hairlines, a serif caption, sticky head where the frame holds the table */
  .tablewrap { grid-column: 1 / -1; overflow-x: auto; scrollbar-color: var(--rule) transparent; scrollbar-width: thin; }
  table { border-collapse: collapse; width: 100%; min-width: 42rem;
          font: var(--t-cap)/var(--base-s) var(--mono); font-variant-numeric: tabular-nums lining-nums; }
  caption { caption-side: top; text-align: left; font: var(--t-body)/var(--base) var(--serif); color: var(--ink-soft);
            padding-bottom: var(--half); position: sticky; left: 0; max-width: calc(100vw - 2 * var(--outer)); }
  th, td { padding: .375rem .75rem .375rem 0; border-bottom: 1px solid var(--rule-soft);
           vertical-align: baseline; white-space: nowrap; text-align: left; }
  th:last-child, td:last-child { padding-right: 0; }
  td.wrap, tr.gap td { white-space: normal; }
  td.wrap { min-width: 9rem; } td.state { min-width: 18rem; } tr.gap td:nth-child(3) { min-width: 11rem; }
  @media (max-width: 83.99rem) { td.wrap, tr.gap td { white-space: nowrap; } td.state { white-space: normal; } }
  thead th { position: sticky; top: 0; z-index: 2; background: var(--bg); color: var(--ink-faint); font-weight: 400;
             font-size: .75rem; letter-spacing: .06em; text-transform: uppercase; border-bottom: 1px solid var(--rule); }
  tbody tr:hover td { background: var(--surface-2); }
  .num { text-align: right; }
  td.mono { color: var(--ink-soft); }
  tr.gap td { color: var(--bad); background: rgba(255, 122, 122, .07); font-weight: 700; }
  tr.warn td.state { color: var(--warn); }
  tr:target td { background: var(--surface-2); box-shadow: inset 3px 0 var(--accent); }
  tbody.month tr.head th { padding-top: var(--base); font: var(--t-body)/var(--base) var(--serif); color: var(--ink);
                            border-bottom: 1px solid var(--rule); white-space: normal; }
  tbody.month tr.head th small { margin-left: var(--half); font: var(--t-cap)/var(--base-s) var(--mono); color: var(--ink-faint); }
  tbody.month tr.head:hover th { background: none; }
  .months { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 0 var(--base); margin-bottom: var(--base);
            font: var(--t-cap)/var(--base-s) var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--ink-faint); }
  .months a { text-decoration: none; }
  .months label { margin-left: auto; cursor: pointer; }
  body.only-defects tbody tr:not(.gap):not(.warn):not(.hind):not(.head) { display: none; }
  @media (min-width: 84rem) { .tablewrap { overflow: visible; } }
  @media (max-width: 83.99rem) {
    th:first-child, td:first-child { position: sticky; left: 0; z-index: 1; background: var(--bg); }
    tr.gap td:first-child { background: #1a141e; }
  }

  /* the foot: three columns under one rule each */
  .col { font: var(--t-foot)/var(--base-s) var(--serif); color: var(--ink-soft); margin-top: var(--base);
         border-top: 1px solid var(--rule-soft); padding-top: calc(var(--half) - 1px); }
  .col h2 { font: 400 var(--t-lede)/var(--base) var(--serif); color: var(--ink); margin-bottom: var(--half); }
  .col p, .col ul, .col ol { margin-bottom: var(--base-s); }
  .col ol { margin-left: 1.25rem; }
  .col > :last-child { margin-bottom: 0; }

  /* colophon: who runs this, the build line, and the caveats in two columns of the mono */
  .colophon { grid-column: 1 / -1; display: grid; grid-template-columns: subgrid; column-gap: var(--gutter);
              margin-top: calc(2 * var(--base)); border-top: 1px solid var(--rule); padding-top: calc(var(--base) - 1px);
              font: var(--t-small)/var(--base-s) var(--serif); color: var(--ink-soft); }
  .colophon .who { grid-column: 1 / span 6; }
  .colophon .who h2 { font: 400 var(--t-lede)/var(--base) var(--serif); color: var(--ink); margin-bottom: var(--half); }
  .colophon .build { grid-column: 8 / span 5; font-family: var(--mono); color: var(--ink-faint); }
  .colophon .caveats { grid-column: 1 / -1; margin-top: var(--base); columns: 2; column-gap: var(--gutter);
                       font-family: var(--mono); color: var(--ink-faint); }
  .colophon p { margin-bottom: var(--base-s); }
  .colophon .caveats p { max-width: none; }

  details { margin-bottom: var(--base); }
  summary { cursor: pointer; font: var(--t-cap)/var(--base-s) var(--mono); letter-spacing: .1em;
            text-transform: uppercase; color: var(--ink-faint); }
  details[open] summary { margin-bottom: var(--half); }
  details p { font-size: var(--t-small); line-height: var(--base-s); color: var(--ink-soft); }

  /* Between 48rem and 72rem the frame is too narrow for a reading measure beside a chart, but wide
     enough for text beside notes and figures, so the bands stay two-column on eight tracks. */
  @media (max-width: 71.99rem) {
    .page { grid-template-columns: repeat(8, minmax(0, 1fr)); }
    .z-full, .z-wide, .z-c1, .z-c2, .z-c3 { grid-column: 1 / -1; }
    .z-prose { grid-column: 1 / span 5; }
    .z-side { grid-column: 6 / span 3; }
    .section h2 { grid-column: 1 / span 5; } .section .stamp { grid-column: 6 / span 3; }
    .colophon .who { grid-column: 1 / span 5; } .colophon .build { grid-column: 6 / span 3; }
    :root { --t-pull: 3rem; }
    .pull b { line-height: calc(2 * var(--base)); }
    figure.z-side.curve { grid-column: 1 / -1; }
  }
  /* Under 48rem everything runs in one column at the measure, in source order. */
  @media (max-width: 47.99rem) {
    .page, .section, .colophon { grid-template-columns: minmax(0, 1fr); }
    .z-full, .z-prose, .z-wide, .z-side, .z-c1, .z-c2, .z-c3, .section h2, .section .stamp,
    .colophon .who, .colophon .build, .colophon .caveats { grid-column: 1 / -1; }
    .z-prose, .z-wide, .z-side { max-width: var(--measure); }
    .colophon .caveats { columns: 1; }
    .z-side.note { border-left: 2px solid var(--rule-soft); padding-left: var(--base); }
  }
  @media (max-width: 40rem) {
    html { font-size: 94%; }
    :root { --t-h2: 1.75rem; --t-deck: 1.25rem; }
    .deck { line-height: var(--base); }
    .section h2 { line-height: calc(1.25 * var(--base)); }
    .z-side.note { padding-left: var(--half); }
  }

  @media print {
    :root { --ink: #000; --ink-soft: #333; --ink-faint: #444; --accent: #7a4a00; --accent-lit: #7a4a00; --bg: #fff;
            --surface: #fff; --surface-2: #f2f2f2; --rule: #999; --rule-soft: #ccc;
            --bad: #9b1c1c; --warn: #7a4a00; --held: #1b6b3a; }
    body { background: #fff; color: #000; }
    .page, .section, .colophon { display: block; width: auto; }
    .tabs, .skip, .months { display: none; }
    .tablewrap { overflow: visible; } table { min-width: 0; font-size: 9pt; }
    thead th, th:first-child, td:first-child { position: static; }
    tr.warn td.state::before { content: "DEFECT: "; }
    tr.gap td { -webkit-print-color-adjust: exact; print-color-adjust: exact; background: #fbe9e9; }
    .colophon .caveats { columns: 1; }
    a { text-decoration: none; } h2 { break-after: avoid; }
  }
"""


# ---------------------------------------------------------------- chrome


def tabs(current: str, rel: str, pack_mb: float | None) -> str:
    out = ['<nav class="tabs" aria-label="Pages">']
    for path, label in PAGES:
        href = rel + (path or "./") if rel else (path or "./")
        cur = ' aria-current="page"' if path == current else ""
        title = (f' title="3D view: loads a {pack_mb:.1f} MB pack and needs WebGL"'
                 if path == "globe/" and pack_mb else "")
        out.append(f'  <a href="{esc(href)}"{cur}{title}>{esc(label)}</a>')
    out.append("</nav>")
    return "\n".join(out)


def masthead(gen: str, rel: str, standfirst: bool) -> str:
    return f"""  <header class="masthead">
    {brand.inline_mark(40)}
    <h1><a href="{rel or './'}">Ephemera</a></h1>
    <span class="where">ephemera.space<br>built {esc(gen)} UTC</span>
  </header>
""" + (f'  <p class="standfirst">{esc(DESCRIPTION)}</p>\n' if standfirst else "")


def colophon(ledger: dict, rel: str, full: bool) -> str:
    gen = utc_min(ledger["generated_utc"])
    who = (f"<p>{esc(CONTACT_NAME)}, on my own time, on a home computer in Cape Town, with no funding and no "
           "affiliation to any operator or agency. If a figure here is wrong I want to know, and corrections get "
           "published rather than quietly fixed.</p>" if full else
           f"<p>{esc(CONTACT_NAME)}, on my own time, on a home computer in Cape Town, with no funding and no "
           "affiliation to any operator or agency.</p>")
    return f"""  <footer class="z-full colophon">
    <div class="who">
      <h2 id="who">Who runs this</h2>
      {who}
      <p><a href="mailto:{esc(CONTACT_MAIL)}">{esc(CONTACT_MAIL)}</a> &nbsp;
      <a href="{esc(CONTACT_LINKEDIN)}">linkedin.com/in/kira-ryan</a></p>
    </div>
    <div class="build">
      <p>Built {esc(gen)} UTC from <a href="{rel}ledger.json">ledger.json</a>. Every figure on this page
      carries the time it was true at.</p>
      <p>Cite as: Ryan, K. (2026). Ephemera: an archive of the public Starlink ephemerides and a daily measure
      of public catalogue visibility. https://ephemera.space, retrieved {esc(gen)} UTC.</p>
    </div>
    <div class="caveats"><p>{esc(CAVEATS)}</p></div>
  </footer>
"""


def page(title: str, path: str, desc: str, current: str, body: str, ledger: dict, pack_mb: float | None,
         standfirst: bool = True, skip: str = "#main") -> str:
    """The chrome around a page body. `path` is the page's own path under the site root, which
    decides the canonical URL, the title and the relative prefix back to the root."""
    rel = "../" * path.count("/")
    gen = utc_min(ledger["generated_utc"])
    full_title = "Ephemera" if not path else f"Ephemera: {title}"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(full_title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{SITE}{esc(path)}">
<link rel="icon" href="{rel}icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="{rel}icon-180.png">
<meta name="theme-color" content="#090c17">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Ephemera">
<meta property="og:title" content="{esc(full_title)}">
<meta property="og:url" content="{SITE}{esc(path)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:image" content="{SITE}social.png">
<meta name="twitter:card" content="summary_large_image">
<style>{CSS}</style>
</head>
<body>
<a class="skip" href="{skip}">Skip to the content</a>
<main class="page" id="main">
{masthead(gen, rel, standfirst)}
{tabs(current, rel, pack_mb)}
{body}
{colophon(ledger, rel, full=(path == ""))}
</main>
</body>
</html>
"""


# ---------------------------------------------------------------- figures


def cycle_strip(ledger: dict, rel: str, rows: int | None = 1) -> str:
    """One block per cycle on a real time axis, one row per 30 days, newest row first. `rows`
    limits the rows (the front page shows one); None shows every row. Each block links to the
    cycle's row on the archive page, so the strip is the visual index to the growing table."""
    cycles = [c for c in ledger["cycles"] if c["first_seen_utc"]]
    if len(cycles) < 2:
        return ""
    newest = max(parse_utc(c["first_seen_utc"]) for c in cycles)
    oldest = min(parse_utc(c["first_seen_utc"]) for c in cycles)
    end = newest.replace(hour=23, minute=59, second=59)
    W, ROW, top, bot = 1000.0, 74.0, 8.0, 26.0
    bands = []
    while True:
        # The newest row covers the data it holds: at most 30 days, at least 3, never a month of
        # nothing with the cycles crammed at one end.
        days = STRIP_DAYS if bands else max(3.0, min(float(STRIP_DAYS), (end - oldest).total_seconds() / 86400 + 0.5))
        start = end - timedelta(days=days)
        inside = [c for c in cycles if start < parse_utc(c["first_seen_utc"]) <= end]
        if not inside and not bands:
            break
        bands.append((start, end, inside))
        if rows is not None and len(bands) >= rows:
            break
        if all(parse_utc(c["first_seen_utc"]) > start for c in cycles):
            break
        end = start
    out = []
    for i, (start, end, inside) in enumerate(bands):
        y0 = i * ROW
        span = (end - start).total_seconds()
        for c in inside:
            x = 6 + (parse_utc(c["first_seen_utc"]) - start).total_seconds() / span * (W - 18)
            # A pull still running is not a defect: it is drawn hollow, in its own class, and only a
            # gapped pull is red.
            cls = ("pulling" if c["status"] == "in-progress" else "miss" if not c["merkle_root"]
                   else "warn" if witness_defect(c)
                   else "pending" if not c["wayback"].get("attempted") or not c["wayback"]["samples_total"] else "kept")
            title = (f"{c['cycle'][6:]} first seen {utc_min(c['first_seen_utc'])} UTC, {c['files_recorded']:,} files"
                     + (f", {witness_defect(c)}" if witness_defect(c) else ""))
            out.append(f'<a href="{rel}archive/#c-{c["cycle"][6:]}"><rect class="{cls}" x="{x:.1f}" y="{y0 + top}" '
                       f'width="7" height="{ROW - top - bot:.0f}" rx="1"><title>{esc(title)}</title></rect></a>')
        # Ticks: weekly on a 30-day row, every other day on a shorter row, daily on a very short one,
        # so a young archive is labelled rather than showing one tick in eight days of blocks.
        days = span / 86400
        every = 1 if days <= 10 else 2 if days <= 20 else 0
        day = start.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        while day <= end:
            x = 6 + (day - start).total_seconds() / span * (W - 18)
            if (every and day.toordinal() % every == 0) or (not every and day.day in (1, 8, 15, 22)):
                out.append(f'<line x1="{x:.1f}" y1="{y0 + top}" x2="{x:.1f}" y2="{y0 + ROW - bot + 4:.0f}" stroke="#283152"/>'
                           f'<text x="{x:.1f}" y="{y0 + ROW - 8:.0f}" text-anchor="middle">{day:%d %b}</text>')
            day += timedelta(days=1)
    H = ROW * len(bands)
    return (f'<figure class="z-full strip"><svg viewBox="-6 0 {W + 12:.0f} {H:.0f}" role="img" '
            f'aria-label="Every archived cycle on a time axis, one block each, coloured by state; each block links to its row.">'
            f'{"".join(out)}</svg><figcaption>'
            + ("The last 30 days" if rows == 1 else "Every cycle kept") + ", one block per cycle on a time axis"
            + ("" if rows == 1 else ", one row per 30 days, newest row first")
            + ". Green is complete and independently copied, grey is complete with the copy still pending, amber is "
              "complete but the independent copy failed, red is an incomplete pull, and a hollow block is a pull still running. "
              "Gaps in the spacing are the "
              f"feed's own cadence. Each block links to its row. As of {esc(utc_min(ledger['generated_utc']))} UTC."
              "</figcaption></figure>")


def visibility_curve(report: dict, cls: str = "z-side") -> str:
    """Median separation against element age, log y, from the same by_age list as the table. A
    curve in the side column is drawn on a narrower viewBox, so its labels are not scaled to dust."""
    bins = [b for b in report["by_age"] if b["n"] >= 50]
    if len(bins) < 3:
        return ""
    W, H, L, R, T, B = (620.0, 280.0, 50.0, 40.0, 18.0, 44.0) if cls == "z-side" else (1000.0, 300.0, 54.0, 46.0, 18.0, 44.0)
    lo, hi = 0.5, max(60.0, max(b["median_km"] for b in bins) * 1.3)

    def y(v: float) -> float:
        return T + (H - T - B) * (1 - (math.log10(max(v, lo)) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)))

    step = (W - L - R) / (len(bins) - 1)
    pts = [(L + i * step, y(b["median_km"])) for i, b in enumerate(bins)]
    grid = "".join(f'<line class="grid" x1="{L}" y1="{y(v):.1f}" x2="{W - R:.0f}" y2="{y(v):.1f}"/>'
                   f'<text x="{L - 8:.0f}" y="{y(v) + 4:.1f}" text-anchor="end">{v:g} km</text>' for v in (1, 3, 10, 30))
    line = '<polyline class="line" points="' + " ".join(f"{x:.1f},{yy:.1f}" for x, yy in pts) + '"/>'
    dots = "".join(f'<circle class="dot" cx="{x:.1f}" cy="{yy:.1f}" r="4"/>'
                   f'<text class="val" x="{x:.1f}" y="{yy - 12:.1f}" text-anchor="middle">{b["median_km"]:.1f}</text>'
                   f'<text x="{x:.1f}" y="{H - 22:.0f}" text-anchor="middle">{esc(b["bin"])}</text>'
                   f'<text x="{x:.1f}" y="{H - 8:.0f}" text-anchor="middle" opacity=".7">{b["n"]:,}</text>'
                   for (x, yy), b in zip(pts, bins))
    return (f'<figure class="{cls} curve"><svg viewBox="0 0 {W:.0f} {H:.0f}" role="img" '
            f'aria-label="Median separation between the public and operator predictions, rising with element age.">'
            f'{grid}{line}{dots}</svg><figcaption>Median separation between the two predictions, by how old the '
            f"public catalogue's information was. Log scale; the second line under each point is how many "
            f'comparisons it holds. Cycle {esc(report["cycle"][6:])}, scored {esc(utc_min(report["as_of"]))} UTC.'
            f"</figcaption></figure>")


def visibility_history(reports: list[dict], gen: str) -> str:
    """Per cycle, the share within 10 km at file start on a time axis. Cycles scored with hindsight
    are drawn hollow: their figure is not comparable and must not read as part of the trend. Past a
    year of cycles, one point per UTC day (the median of the day's live cycles)."""
    pts = [(parse_utc(r["first_seen_utc"]), r["at_file_start"]["within_km"]["10"], r["snapshot_relation"] == "before_cycle", r["cycle"][6:])
           for r in reports if r["at_file_start"] and r["first_seen_utc"]]
    if len(pts) < 2:
        return ""
    pts.sort()
    if len(pts) > 365:
        by_day: dict[str, list] = {}
        for t, v, live, sha in pts:
            by_day.setdefault(t.strftime("%Y-%m-%d"), []).append((t, v, live, sha))
        agg = []
        for day, items in sorted(by_day.items()):
            live = [i for i in items if i[2]] or items
            vals = sorted(i[1] for i in live)
            agg.append((live[0][0], vals[len(vals) // 2], bool([i for i in items if i[2]]), f"{day}, {len(items)} cycles"))
        pts = agg
    W, H, L, R, T, B = 1000.0, 220.0, 46.0, 16.0, 14.0, 34.0
    t0, t1 = pts[0][0], pts[-1][0]
    span = max((t1 - t0).total_seconds(), 1.0)
    x = lambda t: L + (t - t0).total_seconds() / span * (W - L - R)   # noqa: E731
    y = lambda v: T + (H - T - B) * (1 - v)                            # noqa: E731
    grid = "".join(f'<line class="grid" x1="{L}" y1="{y(v):.1f}" x2="{W - R:.0f}" y2="{y(v):.1f}"/>'
                   f'<text x="{L - 8:.0f}" y="{y(v) + 4:.1f}" text-anchor="end">{int(v * 100)}%</text>' for v in (0.25, 0.5, 0.75, 1.0))
    marks = "".join((f'<a href="#s-{esc(sha)}"><circle class="{"live" if live else "hind"}" cx="{x(t):.1f}" cy="{y(v):.1f}" r="4.5">'
                     f'<title>{esc(sha)}: {pct(v)} within 10 km at file start{"" if live else " (scored with hindsight, not comparable)"}</title>'
                     f'</circle></a>') for t, v, live, sha in pts)
    labels = "".join(f'<text x="{x(t):.1f}" y="{H - 10:.0f}" text-anchor="middle">{t:%d %b}</text>'
                     for t in (t0, t0 + (t1 - t0) / 2, t1))
    live_n = sum(1 for p in pts if p[2])
    return (f'<figure class="z-full history"><svg viewBox="0 0 {W:.0f} {H:.0f}" role="img" '
            f'aria-label="Share of satellites within 10 km at file start, one point per scored cycle on a time axis.">'
            f'{grid}{labels}{marks}</svg><figcaption>Every scored cycle: the share of scored satellites the public '
            f"catalogue places within 10 km at the first instant of the file. A hollow point is a cycle scored with "
            f"hindsight, whose figure is not comparable and is drawn only so the record is complete. {live_n} live, "
            f"{len(pts) - live_n} hindsight. Each point links to its row. As of {esc(gen)} UTC.</figcaption></figure>")


# ---------------------------------------------------------------- shared text blocks


def health_line(ledger: dict, r: dict) -> str:
    """The register's truth-health indicator for a scored cycle: files received, poller coverage,
    element age, Space-Track status. Printed wherever a scored figure is."""
    c, o, cage = r["counts"], r["overall"], r["catalogue_age"]
    uncat = c.get("uncatalogued", 0)
    cat = ledger["catalogue"]
    age = (f"Averaged over every comparison, which run out to three days into the operator file, element age is "
           f"{o['mean_age_h']:.1f} h: the difference is the file's own prediction horizon, not catalogue staleness. "
           if o else "No comparison was made for this cycle. ")
    return (f"{c['scored']:,} of {c['files']:,} operator files scored. {c['no_public_set']:,} have no entry in the "
            f"public catalogue" + (f", of which {uncat:,} are new satellites the catalogue has not numbered yet" if uncat else "")
            + f"; {c['decayed_set']:,} marked decayed; {c['propagation_failed']:,} failed to propagate; "
            f"{c['unreadable']:,} unreadable; {c.get('corrupt', 0):,} no longer matching the record. "
            + (f"Public element sets were a mean of <b>{cage['mean_h']:.1f} h</b> old when the snapshot was taken "
               f"(median {cage['median_h']:.1f} h, 90th percentile {cage['p90_h']:.1f} h, {cage['over_72h']} over 72 h). "
               if cage else "")
            + age + f"Space-Track: {ledger['catalogue_snapshots']} snapshots held, last fetched "
            + (f"{esc(utc_min(cat[0]['fetched_utc']))} UTC with {cat[0]['records']:,} element sets" if cat else "none")
            + ". Poller heartbeat coverage over the last 24 h: "
            + (f"{100 * ledger['coverage_24h']:.1f}%" if ledger["coverage_24h"] is not None else "not yet measured") + ".")


def lost_line(start: dict | None) -> str:
    if not start or not start["lost"]:
        return ""
    return (f'<p class="fine"><b class="warnk">{start["lost"]}</b> satellites ({pct(start["lost_fraction"])}) are more '
            f"than {LOST_KM:,} km from the public prediction at publication, which is a large part of an orbit. For "
            f"those the public element set is not on the operator's trajectory at all. Ephemera does not label any "
            f"separation as a manoeuvre; that needs a detector this project has not built.</p>")


def lede(start: dict, far: dict | None) -> str:
    return (f'<p class="lede">At the first instant of each operator file, the public catalogue puts '
            f'<b>{pct(start["within_km"]["10"])}</b> of the scored Starlink satellites within 10 km of where the '
            f'operator says they are. The middle satellite is <b>{start["median_km"]:.1f} km</b> away, with the public '
            f'information a median of {start["median_age_h"]:.0f} hours old'
            + (f". Where the public information is two to three days old, the two predictions are about "
               f"<b>{far['median_km']:.0f} km</b> apart" if far else "")
            + ". Both sides are predictions, and most of that spread is planned trajectory changes the public "
            "catalogue cannot know about.</p>")


EXPLAINER = ("<p>Everyone outside SpaceX sees Starlink through the public catalogue of orbital elements. Ephemera takes "
             "that public element set for each satellite, propagates it with SGP4, and compares it against the "
             "operator's own published trajectory for the same satellite at the same instants. The distance between "
             "the two is what this measures. It is not an error of the satellite, and it is not a statement about "
             "which side is right.</p>")

ARCHIVE_PROSE = ("<p>The operator side of every comparison comes from files this project caught before they were "
                 "replaced. Each cycle is hashed file by file into one Merkle root, the root is stamped into the "
                 "Bitcoin blockchain through OpenTimestamps, and the manifest plus ten files chosen by the root itself "
                 "are pushed into the Wayback Machine so an independent copy exists that this project does not "
                 "control.</p>")


def archive_asof(ledger: dict) -> str:
    t = ledger["totals"]
    cov = (f"{100 * ledger['coverage_24h']:.1f}%" if ledger["coverage_24h"] is not None
           else "not yet measured, the heartbeat history is shorter than 24 hours")
    return (f'<p class="fine">As of <b>{esc(utc_min(ledger["generated_utc"]))} UTC</b>: <b>{t["cycles"]}</b> cycles, '
            f'<b>{t["complete"]}</b> complete with roots, <b>{t["attested"]}</b> anchored in Bitcoin, '
            f'<b>{t["witness_defects"]}</b> with a defect in the independent copy. Source bytes archived: '
            f'<b>{gb(t["bytes_raw"])} GB</b> across {t["files"]:,} files as served. Stored gzipped as '
            f'<b>{gb(t["bytes_stored"])} GB</b>, of which {gb(t["bytes_stored_local"])} GB is on the poller\'s disk and '
            f'{gb(t["bytes_stored_cold_only"])} GB exists only in cold object storage. Cadence holds, meaning a set '
            f'served longer than nine hours: <b>{t["cadence_holds"]}</b>. Poller heartbeat coverage over the last 24 '
            f"hours: <b>{cov}</b>. This project exists because SpaceX publishes the feed openly.</p>")


def archive_pulls(ledger: dict, rel: str, more: bool) -> str:
    t = ledger["totals"]
    gen = utc_min(ledger["generated_utc"])
    long = " long" if len(f"{t['attested']} of {t['complete']}") > 7 else ""
    return (f'<aside class="z-side pulls" aria-label="Archive figures">'
            f'<div class="pull{long}"><b class="held">{t["attested"]} of {t["complete"]}</b><span>cycle roots anchored in '
            f'Bitcoin through OpenTimestamps</span><small>as of {esc(gen)} UTC</small></div>'
            f'<div class="pull"><b class="warnk">{t["witness_defects"]}</b><span>cycles whose independent copy has a '
            f'defect, printed on their rows</span><small>as of {esc(gen)} UTC</small></div>'
            + (f'<p class="more"><a href="{rel}archive/">The archive record</a>: every cycle, its root, its stamp, its '
               f"independent copy, and the daily roots.</p>" if more else "")
            + "</aside>")


def verify_kit(ledger: dict) -> dict | None:
    latest = next((c for c in ledger["cycles"]
                   if c["merkle_root"] and c["ots"]["attested_block"] and c["wayback"]["manifest_copy_url"]), None)
    return latest


def scored_row(r: dict, rel: str) -> str:
    ro, rs = r["overall"], r["at_file_start"]
    sha = r["cycle"][6:]
    rel_txt = ("scored live" if r["snapshot_relation"] == "before_cycle" else
               "scored with hindsight" if r["snapshot_relation"] == "after_cycle" else "pairing not recorded")
    cls = "" if r["snapshot_relation"] == "before_cycle" else "hind"
    link = f'<a href="{rel}archive/#c-{sha}">{sha}</a>'
    if ro is not None and rs is None:
        return (f'<tr class="warn" id="s-{sha}"><td>{esc(utc_min(r["first_seen_utc"]))}</td><td class="mono">{link}</td>'
                f'<td class="num">{r["counts"]["scored"]:,}</td><td class="state" colspan="5">scored before the '
                f"comparable headline existed; rerun score/resummarise.py to fill it in</td></tr>")
    if ro is None:
        return (f'<tr class="gap" id="s-{sha}"><td>{esc(utc_min(r["first_seen_utc"]))}</td><td class="mono">{link}</td>'
                f'<td class="num">{r["counts"]["scored"]:,}</td><td colspan="5">NOTHING SCORED: '
                f'{r["counts"]["unreadable"]:,} unreadable, {r["counts"].get("corrupt", 0):,} no longer matching the record</td></tr>')
    return (f'<tr class="{cls}" id="s-{sha}"><td>{esc(utc_min(r["first_seen_utc"]))}</td><td class="mono">{link}</td>'
            f'<td class="num">{r["counts"]["scored"]:,}</td><td class="{"" if not cls else "warnk"}">{rel_txt}</td>'
            f'<td class="num">{rs["median_age_h"]:.1f}</td><td class="num">{rs["median_km"]:.1f}</td>'
            f'<td class="num">{pct(rs["within_km"]["10"])}</td><td class="num">{rs["lost"]:,}</td></tr>')


def archive_row(c: dict, rel: str, scored: set) -> str:
    in_progress = c["status"] == "in-progress"
    gap = c["merkle_root"] is None and not in_progress
    defect = witness_defect(c)
    wb = c["wayback"]
    if not wb.get("attempted"):
        state = "follows the pull" if in_progress else "pending"
    elif wb["skipped"]:
        state = f"no independent copy: {esc(wb['skipped'])}"
    elif not wb["manifest_verified"]:
        state = (("manifest NEVER CAPTURED" if not wb["manifest_captured"]
                  else "manifest COPY DOES NOT MATCH (the archived copy is another cycle's manifest)")
                 + f", {wb['samples_verified']}/{wb['samples_total']} samples verified")
        if wb["losses"]:
            state += f", {wb['losses']} lost"
    elif wb["samples_total"]:
        state = f"manifest ok, {wb['samples_verified']}/{wb['samples_total']} samples verified"
        if wb["losses"]:
            state += f", {wb['losses']} lost"
    else:
        state = "pending"
    if wb.get("manifest_copy_url") and wb.get("manifest_verified"):
        state = f'<a href="{esc(wb["manifest_copy_url"])}">{state}</a>'
    ots = (f"block {c['ots']['attested_block']}" if c["ots"]["attested_block"] else
           "stamped, attestation pending" if c["ots"]["stamped"] else
           "follows the pull" if in_progress else "pending")
    files = (f"pulling now: {c['files_recorded']:,} of {c['files_listed']:,} so far" if in_progress else
             f"INCOMPLETE: {c['files_failed']:,} of {c['files_listed']:,} missing, recorded" if gap else
             f"{c['files_recorded']:,}")
    where = ("spool and cold storage" if c["storage"]["local_files"] and c["storage"]["bytes_stored"]
             else "cold storage only" if c["storage"]["bytes_stored"] else "spool only")
    sha = c["cycle"][6:]
    cell = f'<a href="{rel}scored/#s-{sha}">{sha}</a>' if sha in scored else sha
    cls = "gap" if gap else "warn" if defect else ""
    return (f'<tr class="{cls}" id="c-{sha}"><td>{esc(utc_min(c["first_seen_utc"]))}</td><td class="mono">{cell}</td>'
            f'<td class="num">{files}</td><td class="num">{c["bytes_raw"] / 1e9:.1f}</td>'
            f'<td class="mono">{esc((c["merkle_root"] or "none")[:12])}</td><td class="wrap">{esc(ots)}</td>'
            f'<td class="state wrap">{state}</td><td class="wrap">{esc(where)}</td></tr>')


def month_sections(items: list[dict], key: str, row_fn, head_fn, colspan: int) -> tuple[str, str]:
    """(months nav links, tbodies) for a list already sorted newest first, grouped by UTC month."""
    groups: dict[str, list[dict]] = {}
    for it in items:
        ym = (it.get(key) or "")[:7]
        if ym:
            groups.setdefault(ym, []).append(it)
    links = "".join(f'<a href="#m-{ym}">{esc(month_label(ym))} ({len(v)})</a>' for ym, v in groups.items())
    bodies = "".join(f'<tbody class="month" id="m-{ym}"><tr class="head"><th colspan="{colspan}">{esc(month_label(ym))} '
                     f'<small>{esc(head_fn(v))}</small></th></tr>{"".join(row_fn(it) for it in v)}</tbody>'
                     for ym, v in groups.items())
    return links, bodies


TOGGLE = ("""<script>(function(){var b=document.getElementById('only-defects');if(!b)return;"""
          """b.addEventListener('change',function(){document.body.classList.toggle('only-defects',b.checked);});})();</script>""")


# ---------------------------------------------------------------- the pages


def home(ledger: dict, pack_mb: float | None) -> str:
    gen = utc_min(ledger["generated_utc"])
    reports = ledger["visibility"]["reports"]
    head = headline_report(reports)
    start = head["at_file_start"] if head else None
    far = next((b for b in head["by_age"] if b["bin"] == "48-72 h"), None) if head else None
    t = ledger["totals"]
    deck_extra = ("" if reports else " No cycle has been scored yet. Scoring starts once the public catalogue feed "
                  "has a snapshot to pair with an archived cycle.")

    if start:
        pulls = (f'<aside class="z-side pulls" aria-label="Headline figures">'
                 f'<div class="pull"><b>{pct(start["within_km"]["10"])}</b><span>of the scored Starlink satellites within '
                 f"10 km of the operator's trajectory, at file start</span><small>cycle {esc(head['cycle'][6:])}, scored "
                 f'{esc(utc_min(head["as_of"]))} UTC</small></div>'
                 f'<div class="pull"><b>{start["median_km"]:.1f} km</b><span>median separation between the two '
                 f"predictions, at file start</span><small>same cycle, same instant</small></div></aside>")
    else:
        pulls = archive_pulls(ledger, "", more=False)

    if head:
        finding = f"""  <header class="z-full section" id="finding">
    <h2>What the public catalogue can see</h2>
    <p class="stamp">Headline figures from cycle <b>{esc(head["cycle"][6:])}</b>, first seen {esc(utc_min(head["first_seen_utc"]))} UTC,
    scored {esc(utc_min(head["as_of"]))} UTC against the public catalogue snapshot fetched
    {esc(utc_min(head["snapshot_fetched_utc"]))} UTC ({head["catalogue_sets"]:,} element sets).{esc(newer_not_comparable(reports, head))}</p>
  </header>
  <div class="z-prose">
    {lede(start, far)}
    {EXPLAINER}
    {lost_line(start)}
  </div>
  {visibility_curve(head)}
  <div class="z-prose">
    <p class="fine"><b>Feed health for this cycle.</b> {health_line(ledger, head)}</p>
  </div>
  <aside class="z-side note">
    <h3>Further</h3>
    <ul>
      <li><a href="finding/">The full finding</a>: the same curve as numbers, by element age and by altitude shell, with the method.</li>
      <li><a href="scored/">Every scored cycle</a>: one row per cycle, measured at the first instant of each file.</li>
      <li><a href="globe/">See it on the globe</a>: every satellite drawn twice, the operator trajectory and the public catalogue's ghost{f" (a {pack_mb:.1f} MB pack, needs WebGL)" if pack_mb else ""}.</li>
    </ul>
  </aside>
"""
    else:
        why = no_headline_reason(reports)
        finding = f"""  <header class="z-full section" id="finding">
    <h2>What the public catalogue can see</h2>
    <p class="stamp">{esc(why)} As of {esc(gen)} UTC.</p>
  </header>
  <div class="z-prose">{EXPLAINER}<p class="fine">{esc(why)}</p></div>
  <aside class="z-side note"><h3>Further</h3><ul>
    <li><a href="scored/">Every scored cycle</a>, when there is one.</li>
    <li><a href="archive/">The archive record</a>: every cycle, its root, its stamp, its independent copy.</li>
  </ul></aside>
"""

    kit = verify_kit(ledger)
    if kit:
        wb = kit["wayback"]
        check = (f'<p>None of this is worth anything if you have to take my word for it. Three things you can run right '
                 f'now, for cycle <span class="mono">{esc(kit["cycle"][6:])}</span>:</p><ol>'
                 f'<li>Fetch the <a href="{esc(wb["manifest_copy_url"])}">independent copy</a> of the file list and hash '
                 f'it. SHA-256 <code>{esc(wb["manifest_copy_sha256"] or "")}</code>.</li>'
                 f'<li>Recompute which ten files were copied: <code>int(sha256(root + ":" + k), 16) mod n</code> for k from 0 to 9.</li>'
                 f'<li>Run <code>ots verify root.txt.ots</code> against a Bitcoin node: this root is in block '
                 f'{esc(kit["ots"]["attested_block"])}.</li></ol>'
                 f'<p class="more"><a href="check/">The full procedure</a>, and what still needs the data release.</p>')
    else:
        check = ("<p>No cycle yet has both a Bitcoin attestation and an independent copy, so there is nothing here a "
                 'stranger could run today. This fills in as soon as one does.</p><p class="more"><a href="check/">The '
                 "procedure</a>, ready for when it does.</p>")

    seen = sorted(c["first_seen_utc"] for c in ledger["cycles"] if c["first_seen_utc"])
    days = (parse_utc(seen[-1]) - parse_utc(seen[0])).total_seconds() / 86400 if seen else 0
    span = "An empty archive" if not seen else "Less than a day" if days < 1 else f"{days:.0f} days"

    body = f"""  <div class="z-prose">
    <p class="deck">Every eight hours, SpaceX publishes where each of about eleven thousand Starlink satellites will be
    for the next three days, and how sure it is. Eight hours later that set is gone, replaced by the next one.
    <strong>Ephemera keeps them, and measures what the public catalogue can see.</strong>{esc(deck_extra)}</p>
    <p class="fine">The files carry a full position and velocity uncertainty every sixty seconds, read from the feed
    on 30 August 2026. Starlink is the only operator with public covariance; other operators enter via CelesTrak
    SupGP without covariance.</p>
  </div>
  {pulls}

{finding}
  <header class="z-full section" id="archive">
    <h2>The archive behind it</h2>
    <p class="stamp">As of {esc(gen)} UTC. Poller: {esc(ledger["poller"])}.</p>
  </header>
  <div class="z-prose">
    {ARCHIVE_PROSE}
    {archive_asof(ledger)}
  </div>
  {archive_pulls(ledger, "", more=True)}
  {cycle_strip(ledger, "", rows=1)}

  <section class="z-c1 col" id="check">
    <h2>Check it yourself</h2>
    {check}
  </section>
  <section class="z-c2 col" id="data">
    <h2>Data, licence and citation</h2>
    <p><a href="ledger.json">ledger.json</a> carries every cycle, its root, its attestation, its witness state and
    every scored summary, as the JSON the pages are built from. The globe's per-cycle pack is at
    <a href="globe/pack.json">globe/pack.json</a>{f" ({pack_mb:.1f} MB)" if pack_mb else ""}. The full per-comparison
    rows, about 140,000 per cycle, are available on request.</p>
    <p>Code is MIT, though the repository is not public yet. Figures derived by this project are intended for
    CC BY 4.0. The raw SpaceX files carry no stated licence; a written request went to SpaceX on 31 August 2026
    and is unanswered as of this build.
    <a href="check/#data">Licence and citation in full.</a></p>
  </section>
  <section class="z-c3 col" id="next">
    <h2>Not here yet</h2>
    <p>{esc(span)} of archive is not a long record, and this page should not pretend otherwise. What is not running:</p>
    <ul>
      <li>A second poller on a different machine in a different country.</li>
      <li>The self-consistency scoreboard, prediction against later prediction.</li>
      <li>The manoeuvre census: three differently defined counts side by side, never a ratio.</li>
      <li>Other constellations, via CelesTrak SupGP without covariance.</li>
      <li>A restore drill from cold storage.</li>
    </ul>
  </section>
"""
    return page("", "", DESCRIPTION, "", body, ledger, pack_mb, standfirst=False, skip="#finding")


def finding(ledger: dict, pack_mb: float | None) -> str:
    gen = utc_min(ledger["generated_utc"])
    reports = ledger["visibility"]["reports"]
    head = headline_report(reports)
    if not head:
        why = no_headline_reason(reports)
        body = (f'<header class="z-full section" id="finding"><h2>What the public catalogue can see</h2>'
                f'<p class="stamp">{esc(why)} As of {esc(gen)} UTC.</p></header><div class="z-prose">{EXPLAINER}</div>')
        return page("The finding", "finding/", "How far the public catalogue's prediction sits from the operator's, "
                    "for every Starlink satellite in the latest scored cycle.", "finding/", body, ledger, pack_mb)
    start = head["at_file_start"]
    far = next((b for b in head["by_age"] if b["bin"] == "48-72 h"), None)
    age_rows = "".join(
        f'<tr><td>{esc(b["bin"])}</td><td class="num">{b["n"]:,}</td><td class="num">{b["median_km"]:.1f}</td>'
        f'<td class="num">{b["p90_km"]:.1f}</td><td class="num">{pct(b["within_km"]["10"])}</td>'
        f'<td class="num">{pct(b["within_km"]["30"])}</td></tr>' for b in head["by_age"])
    shell_rows = "".join(
        f'<tr><td>{esc(b["bin"])}</td><td class="num">{b["n"]:,}</td><td class="num">{b["median_km"]:.1f}</td>'
        f'<td class="num">{pct(b["within_km"]["10"])}</td></tr>' for b in head["by_shell"])
    body = f"""  <header class="z-full section" id="finding">
    <h2>What the public catalogue can see</h2>
    <p class="stamp">Cycle <b>{esc(head["cycle"][6:])}</b>, first seen {esc(utc_min(head["first_seen_utc"]))} UTC, scored
    {esc(utc_min(head["as_of"]))} UTC against the public catalogue snapshot fetched {esc(utc_min(head["snapshot_fetched_utc"]))}
    UTC ({head["catalogue_sets"]:,} element sets).{esc(newer_not_comparable(reports, head))}</p>
  </header>
  <div class="z-prose">{lede(start, far)}{EXPLAINER}{lost_line(start)}</div>
  {visibility_curve(head, cls="z-full")}
  <div class="tablewrap"><table>
    <caption>The same curve as numbers, for cycle {esc(head["cycle"][6:])}. Scored {esc(utc_min(head["as_of"]))} UTC.</caption>
    <thead><tr><th scope="col">element age</th><th scope="col" class="num">comparisons</th>
      <th scope="col" class="num">median km</th><th scope="col" class="num">90th pct km</th>
      <th scope="col" class="num">within 10 km</th><th scope="col" class="num">within 30 km</th></tr></thead>
    <tbody>{age_rows}</tbody>
  </table></div>
  <div class="z-prose"><p class="fine">Element age is how old the public catalogue's information was at the instant
  compared. It runs larger than catalogue staleness because a single operator file predicts three days ahead, so a
  comparison late in the file is both further ahead and matched against an older element set. The two effects are not
  separated within one cycle, which is why the headline uses only the first instant of each file.</p></div>
  {'<div class="tablewrap"><table><caption>By altitude shell. The lowest shell is where satellites are being raised and lowered, so its spread is the widest.</caption><thead><tr><th scope="col">shell</th><th scope="col" class="num">comparisons</th><th scope="col" class="num">median km</th><th scope="col" class="num">within 10 km</th></tr></thead><tbody>' + shell_rows + '</tbody></table></div>' if shell_rows else ''}
  <div class="z-prose"><p class="fine"><b>Feed health for this cycle.</b> {health_line(ledger, head)}</p></div>
  <aside class="z-side note">
    <h3>How this was measured</h3>
    <p>{esc(head["method"])}</p>
    <p>Snapshot <span class="mono">{esc(head["snapshot"])}</span>. Evaluation every {head["eval_step_min"]:g} minutes
    across each file's own record epochs. Public element sets come from Space-Track.org and are redistributed under
    Space-Track's blanket approval for basic space situational awareness data, with citation.</p>
    <p><a href="../scored/">Every scored cycle</a> &nbsp; <a href="../globe/">See it on the globe</a></p>
  </aside>
"""
    return page("The finding", "finding/", "How far the public catalogue's prediction sits from the operator's, for every "
                "Starlink satellite in the latest scored cycle, by element age and altitude shell.", "finding/",
                body, ledger, pack_mb)


def scored(ledger: dict, pack_mb: float | None) -> str:
    gen = utc_min(ledger["generated_utc"])
    reports = ledger["visibility"]["reports"]
    live = sum(1 for r in reports if r["snapshot_relation"] == "before_cycle")
    hind = sum(1 for r in reports if r["snapshot_relation"] == "after_cycle")
    year = (reports[0]["first_seen_utc"] or gen)[:4] if reports else gen[:4]
    if not reports:
        body = (f'<header class="z-full section" id="scored"><h2>Every scored cycle</h2><p class="stamp">No cycle has been '
                f'scored yet. As of {esc(gen)} UTC.</p></header><div class="z-prose"><p>Scoring starts once the public '
                f"catalogue feed has a snapshot to pair with an archived cycle.</p></div>")
        return page("Scored cycles", "scored/", "Every scored Starlink cycle, one row per cycle.", "scored/", body, ledger, pack_mb)
    head = headline_report(reports)
    health = (f'<p class="fine"><b>Feed health for this cycle.</b> The headline cycle, <b>{esc(head["cycle"][6:])}</b>: '
              f'{health_line(ledger, head)}</p>' if head else "")
    links, bodies = month_sections(
        reports, "first_seen_utc", lambda r: scored_row(r, "../"),
        lambda v: f"{len(v)} cycles, {sum(1 for r in v if r['snapshot_relation'] == 'before_cycle')} live, "
                  f"{sum(1 for r in v if r['snapshot_relation'] == 'after_cycle')} hindsight, "
                  f"{sum(1 for r in v if r['overall'] is None)} with nothing scored", 8)
    body = f"""  <header class="z-full section" id="scored">
    <h2>Every scored cycle</h2>
    <p class="stamp">{esc(year)}: <b>{len(reports)}</b> scored, {live} live, {hind} with hindsight. As of {esc(gen)} UTC.</p>
  </header>
  <div class="z-prose">
    <p>One row per cycle, measured at the first instant of each operator file so the rows are comparable. A cycle
    marked <b class="warnk">scored with hindsight</b> was matched against a catalogue snapshot fetched after it, because
    the cycle predates this project's catalogue feed. Its element sets already know what the satellite did during the
    file, so its numbers look better than they should and are not comparable with the rest. {hind} of {len(reports)}
    scored cycles are in that state, and the count only falls from here.</p>
  </div>
  <aside class="z-side pulls" aria-label="Scored cycle counts">
    <div class="pull"><b>{len(reports)}</b><span>cycles scored so far</span><small>as of {esc(gen)} UTC</small></div>
    <div class="pull"><b>{live}</b><span>scored live, comparable between cycles</span><small>{hind} with hindsight</small></div>
  </aside>
  {visibility_history(reports, gen)}
  <nav class="months z-full" aria-label="Months">{links}<label><input type="checkbox" id="only-defects"> only rows with a defect or hindsight</label></nav>
  <div class="tablewrap"><table>
    <caption>One row per cycle, measured at the first instant of each file. Newest first. As of {esc(gen)} UTC.</caption>
    <thead><tr><th scope="col">cycle first seen</th><th scope="col">cycle</th><th scope="col" class="num">scored</th>
      <th scope="col">pairing</th><th scope="col" class="num">median age h</th><th scope="col" class="num">median km</th>
      <th scope="col" class="num">within 10 km</th><th scope="col" class="num">lost</th></tr></thead>
    {bodies}
  </table></div>
  <div class="z-prose"><p class="fine">Method: {esc(reports[0]["method"])}</p>{health}</div>
  {TOGGLE}
"""
    return page("Scored cycles", "scored/", "Every scored Starlink cycle, one row per cycle, measured at the first "
                "instant of each operator file.", "scored/", body, ledger, pack_mb)


def archive(ledger: dict, pack_mb: float | None) -> str:
    gen = utc_min(ledger["generated_utc"])
    cycles = ledger["cycles"]
    scored_ids = {r["cycle"][6:] for r in ledger["visibility"]["reports"]}
    year = (cycles[0]["first_seen_utc"] or gen)[:4] if cycles else gen[:4]
    links, bodies = month_sections(
        cycles, "first_seen_utc", lambda c: archive_row(c, "../", scored_ids),
        lambda v: f"{len(v)} cycles, {sum(1 for c in v if c['merkle_root'])} complete, "
                  f"{sum(1 for c in v if not c['merkle_root'] and c['status'] != 'in-progress')} incomplete, "
                  f"{sum(1 for c in v if witness_defect(c))} with a witness defect", 8)
    droots = "".join(
        f'<tr><td>{esc(d["date"])}</td><td class="mono">{esc(d["merkle_root"][:12])}</td><td class="num">{d["leaves"]}</td>'
        f'<td>{("block " + str(d["attested_block"])) if d["attested_block"] else "stamp pending"}</td>'
        f'<td class="wrap">{"none" if not d["excluded"] else "excluded " + ", ".join(f"{esc(n[6:])} ({esc(w)})" for n, w in d["excluded"])}</td></tr>'
        for d in ledger["daily_roots"])
    body = f"""  <header class="z-full section" id="archive">
    <h2>The archive record</h2>
    <p class="stamp">As of {esc(gen)} UTC. Poller: {esc(ledger["poller"])}. {esc(year)} so far; earlier years get their
    own page once they exist.</p>
  </header>
  <div class="z-prose">{ARCHIVE_PROSE}{archive_asof(ledger)}</div>
  {archive_pulls(ledger, "../", more=False)}
  {cycle_strip(ledger, "../", rows=None)}
  <nav class="months z-full" aria-label="Months" id="cycles">{links}<label><input type="checkbox" id="only-defects"> only rows with a defect</label></nav>
  <div class="tablewrap"><table>
    <caption>Every cycle of {esc(year)}, newest first. Amber marks a cycle whose own pull succeeded but whose independent
    copy did not; red is an incomplete pull, kept and printed. As of {esc(gen)} UTC.</caption>
    <thead><tr><th scope="col">first seen (utc)</th><th scope="col">cycle</th><th scope="col" class="num">files</th>
      <th scope="col" class="num">source gb</th><th scope="col">merkle root</th><th scope="col">opentimestamps</th>
      <th scope="col">wayback machine</th><th scope="col">held</th></tr></thead>
    {bodies}
  </table></div>
  <div class="z-prose"><p class="fine">Method: {esc(ledger["method"])}. Poller: {esc(ledger["poller"])}.</p></div>
  <div class="tablewrap"><table>
    <caption>Daily roots. A root over each day's complete cycle roots, built shortly after midnight UTC and stamped separately.</caption>
    <thead><tr><th scope="col">date</th><th scope="col">root</th><th scope="col" class="num">leaves</th>
      <th scope="col">opentimestamps</th><th scope="col">note</th></tr></thead>
    <tbody>{droots or '<tr><td colspan="5">the first daily root arrives after the first full UTC day</td></tr>'}</tbody>
  </table></div>
  <div class="z-prose"><p class="fine">A cycle still pulling at midnight is left out of that day's root and stays out. It
  keeps its own cycle root and its own OpenTimestamps proof, so nothing is unwitnessed, but it sits under no daily
  root.</p></div>
  {TOGGLE}
"""
    return page("The archive", "archive/", "Every archived Starlink cycle: its Merkle root, its Bitcoin attestation, "
                "its independent Wayback copy, and the daily roots.", "archive/", body, ledger, pack_mb, skip="#cycles")


def check(ledger: dict, pack_mb: float | None) -> str:
    gen = utc_min(ledger["generated_utc"])
    kit = verify_kit(ledger)
    if kit:
        wb = kit["wayback"]
        prose = f"""  <div class="z-prose">
    <p>None of this is worth anything if you have to take my word for it. Here is what you can run right now, and
    what still needs data this site does not publish yet. I would rather say which is which.</p>
    <p><b>Fetch an independent copy and hash it.</b> Each cycle's file list is pushed into the Wayback Machine the
    moment it is caught, so a copy exists that I do not control. For cycle <span class="mono">{esc(kit["cycle"][6:])}</span>
    that copy is <a href="{esc(wb["manifest_copy_url"])}">here</a>, and its SHA-256 is
    <code>{esc(wb["manifest_copy_sha256"] or "")}</code>. Download it, hash it, and you have checked that the list of
    files I claim to have caught is the list the source was actually serving. Ten files from each cycle are copied the
    same way, and every copy URL and digest is in <a href="../ledger.json">ledger.json</a>.</p>
    <p><b>Check which ten files were copied.</b> I do not get to choose them. File number
    <code>int(sha256(root + ":" + k), 16) mod n</code> for k from 0 to 9, where n is the number of files in the list
    you just downloaded. Run that and you get the same ten names this site published.</p>
    <p><b>Check the timestamp.</b> Each cycle root is stamped through OpenTimestamps. Running
    <code>ots verify root.txt.ots</code> against a Bitcoin node shows this cycle's root committed in block
    {esc(kit["ots"]["attested_block"])}, which fixes the latest moment it could have been written. Nobody, including me,
    can move a root backwards once it is in a block. The proof files ship with the data release.</p>
    <p class="fine">What you cannot do from this page alone is rebuild the Merkle root, because that needs the SHA-256
    of every one of the {kit["files_recorded"]:,} files in the cycle and this site publishes the summary rather than the
    full digest list. Those digests, and the exact byte format of the root file, come with the data release described
    below. The construction is the plain one: leaves are the file digests in manifest order, adjacent pairs are hashed
    as SHA-256 of the two digests joined end to end, and an odd trailing node is paired with a copy of itself.</p>
  </div>
  <aside class="z-side note">
    <h3>The kit for cycle {esc(kit["cycle"][6:])}</h3>
    <ul>
      <li>manifest copy: <a href="{esc(wb["manifest_copy_url"])}">web.archive.org</a></li>
      <li>SHA-256 of the copy: <code>{esc(wb["manifest_copy_sha256"] or "")}</code></li>
      <li>Bitcoin block: {esc(kit["ots"]["attested_block"])}</li>
      <li>files in the cycle: {kit["files_recorded"]:,}</li>
      <li>root: <code>{esc(kit["merkle_root"])}</code></li>
      <li>first seen: {esc(utc_min(kit["first_seen_utc"]))} UTC</li>
      <li><a href="../archive/#c-{esc(kit["cycle"][6:])}">its row on the archive page</a></li>
    </ul>
  </aside>
"""
    else:
        prose = ('  <div class="z-prose"><p>No cycle yet has both a Bitcoin attestation and an independent copy, so there '
                 "is nothing here a stranger could run today. This section fills in as soon as one does.</p></div>")
    body = f"""  <header class="z-full section" id="check">
    <h2>Check it yourself</h2>
    <p class="stamp">{("Cycle <b>" + esc(kit["cycle"][6:]) + "</b>, block " + esc(kit["ots"]["attested_block"]) + ". ") if kit else ""}As of {esc(gen)} UTC.</p>
  </header>
{prose}
  <header class="z-full section" id="data">
    <h2>Data, licence and citation</h2>
    <p class="stamp">As of {esc(gen)} UTC.</p>
  </header>
  <div class="z-prose">
    <ul>
      <li><a href="../ledger.json">ledger.json</a> carries every cycle, its root, its attestation, its witness state and
      every scored summary on this site, as machine-readable JSON. It is the same file the pages are built from.</li>
      <li>The globe's per-cycle pack, with the element sets and the scored separations, is at
      <a href="../globe/pack.json">globe/pack.json</a>{f" ({pack_mb:.1f} MB)" if pack_mb else ""} for the newest scored cycle.</li>
      <li>The full per-comparison rows, about 140,000 per cycle, are kept in the archive and are available on request.
      They move to public object storage once the storage layer is finished.</li>
      <li>The raw operator files are held as published, hashed and witnessed. They are not re-published here while the
      licence question below is open.</li>
    </ul>
    <p class="fine"><b>Licence.</b> Code is MIT. The repository is not public yet, so the propagation and the
    scoring cannot be read from here today; that is a gap in what this page asks you to check, and it is named
    rather than left for you to find. Figures derived by this project are intended for CC BY 4.0. The raw
    SpaceX files carry no stated licence; a written request went to SpaceX on 31 August 2026 and is unanswered as of
    this build, and any file comes down on request. Public element sets come from Space-Track.org and are redistributed
    under Space-Track's blanket approval for basic space situational awareness data, with citation.</p>
    <p class="fine"><b>Citation.</b> Ryan, K. (2026). <i>Ephemera: an archive of the public Starlink ephemerides and a
    daily measure of public catalogue visibility.</i> https://ephemera.space, retrieved {esc(gen)} UTC.</p>
  </div>
"""
    return page("Check it", "check/", "How to verify an archived Starlink cycle yourself: the independent copy, the "
                "sample rule, the OpenTimestamps proof, and the data and licence.", "check/", body, ledger, pack_mb)


def not_found(ledger: dict, pack_mb: float | None) -> str:
    body = """  <header class="z-full section"><h2>There is no page at this address</h2>
    <p class="stamp">The archive, the scored cycles and the checks are in the tabs above.</p></header>
  <div class="z-prose"><p>If a link brought you here, the page it named has moved or never existed. Every table row on
  this site has a permanent address of the form <code>archive/#c-&lt;cycle&gt;</code> or
  <code>scored/#s-&lt;cycle&gt;</code>, and the front page is one tab to the left.</p></div>
"""
    # Cloudflare Pages serves this file for a missing path at any depth, so a relative link on it
    # would resolve under whatever directory the visitor typed. Every internal href (icons, tabs,
    # the wordmark, ledger.json) is rewritten to start at the site root; external links, mailto
    # and fragments are left alone.
    out = page("Not found", "404.html", "There is no page at this address.", "", body, ledger, pack_mb)
    return re.sub(r'href="(?!https?:|mailto:|#|/)(?:\./)?', 'href="/', out)


def render_site(ledger: dict, pack_bytes: int | None) -> dict[str, str]:
    """Every page the site publishes, keyed by its path under the site root."""
    pack_mb = pack_bytes / 1e6 if pack_bytes else None
    return {
        "index.html": home(ledger, pack_mb),
        "finding/index.html": finding(ledger, pack_mb),
        "scored/index.html": scored(ledger, pack_mb),
        "archive/index.html": archive(ledger, pack_mb),
        "check/index.html": check(ledger, pack_mb),
        "404.html": not_found(ledger, pack_mb),
    }


def globe_chrome(ledger: dict, pack_bytes: int | None) -> tuple[str, str]:
    """What build.py injects into the globe page: (the masthead-and-tabs block, the status line)."""
    pack_mb = pack_bytes / 1e6 if pack_bytes else None
    block = (f'{brand.inline_mark(22)} <span class="wm">Ephemera</span>\n'
             f'  {tabs("globe/", "../", pack_mb).replace(chr(10), chr(10) + "  ")}')
    status = (f"Loading the globe pack ({pack_mb:.1f} MB, WebGL needed)." if pack_mb
              else "Loading the latest globe pack.")
    return block, status
