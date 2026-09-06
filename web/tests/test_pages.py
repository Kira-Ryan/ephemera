"""The multi-page site's structure (D20): six pages from one chrome, each with its own title and
canonical URL; a tab bar that marks exactly the page it is on; row ids that never move; a build
that prunes what it did not write; a 404 that works from any depth; a print palette; and a layout
that holds at phone, laptop and desktop widths in a real browser.

Every page is rendered from the synthetic spool that test_build.py and test_build_visibility.py
define (a healthy attested cycle, a gapped cycle, a witness loss, a cadence hold, a daily root and
one live scored cycle), so the pages under test carry every uncomfortable state. Each test names the
mutation that turns it red. Nothing here writes outside tmp_path.
"""
from __future__ import annotations

import html as htmllib
import json
import posixpath
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402
import pages  # noqa: E402
from test_build import CHROME, serve  # noqa: E402
from test_build_visibility import build_site  # noqa: E402

SITE = "https://ephemera.space/"
PAGE_PATHS = ("index.html", "finding/index.html", "scored/index.html", "archive/index.html",
              "check/index.html", "404.html")
FEED_HEALTH = "Feed health for this cycle."
# The existing browser tests' Chrome flags, with the window wide enough to hold the widest iframe
# the probes below open (headless Chrome will not open a window narrower than about 500 px, so a
# phone width is an iframe of that width rather than a window: measured 6 Sep 2026,
# --window-size=390,900 gives innerWidth 500).
CHROME_ARGS = ["--headless=new", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
               "--force-device-scale-factor=1", "--window-size=1600,1000", "--virtual-time-budget=40000",
               "--dump-dom"]


# ---------------------------------------------------------------- helpers


def site(tmp_path: Path):
    """The built site and every page rendered again from its ledger: (ledger, out, pages)."""
    ledger, _, out = build_site(tmp_path)
    pack = out / "globe" / "pack.json"
    return ledger, out, build.render_site(ledger, pack.stat().st_size if pack.exists() else None)


def title_of(page: str) -> str:
    return re.search(r"<title>(.*?)</title>", page).group(1)


def canonical_of(page: str) -> str:
    return re.search(r'<link rel="canonical" href="([^"]*)">', page).group(1)


def tab_bar(page: str) -> str:
    """The tab bar's markup alone. Counting aria-current over the whole page would also count the
    stylesheet's selector for it."""
    m = re.search(r'<nav class="tabs"[^>]*>(.*?)</nav>', page, re.S)
    assert m, "no tab bar on the page"
    return m.group(1)


def current_tabs(nav: str) -> list[tuple[str, str]]:
    """(href, label) of every tab anchor carrying aria-current="page"."""
    return [(href, label) for href, attrs, label in re.findall(r'<a href="([^"]*)"([^>]*)>([^<]*)</a>', nav)
            if 'aria-current="page"' in attrs]


def lands_in(page_path: str, href: str) -> str:
    """The site-root-relative directory an href lands in when followed from page_path ("." is the
    root). Root-absolute hrefs ignore the page's own depth, as a browser would."""
    target = href[1:] if href.startswith("/") else posixpath.join(posixpath.dirname(page_path), href)
    return posixpath.normpath(target) if target else "."


def own_dir(page_path: str) -> str:
    return posixpath.normpath(posixpath.dirname(page_path) or ".")


def hrefs(page: str) -> list[str]:
    return re.findall(r'href="([^"]*)"', page)


def css_block(css: str, opener: str) -> str:
    """The braces-balanced body of the first block that starts with `opener`."""
    start = css.index(opener)
    i = css.index("{", start)
    depth, j = 0, i
    for j in range(i, len(css)):
        depth += css[j] == "{"
        depth -= css[j] == "}"
        if depth == 0:
            break
    return css[i + 1:j]


def probe_json(out: Path, name: str, script: str) -> list:
    """Serve `out`, open a probe page whose script writes a JSON list into <pre id="probe">, and
    return that list. The probe page is written under `out` (same origin as the pages it opens in
    iframes) and removed afterwards; its name starts with "probe" so neither the build's prune nor
    the claims lint would treat it as a page."""
    probe = out / name
    probe.write_text('<!doctype html><meta charset="utf-8"><title>probe</title><body><script>' + script
                     + "</script></body>", encoding="utf-8")
    srv = serve(out)
    try:
        r = subprocess.run([CHROME, *CHROME_ARGS, f"http://127.0.0.1:{srv.server_address[1]}/{name}"],
                           capture_output=True, timeout=240)
        dom = r.stdout.decode("utf-8", "replace")
    finally:
        srv.shutdown()
        probe.unlink(missing_ok=True)
    m = re.search(r'<pre id="?probe"?>(.*?)</pre>', dom, re.S)
    assert m, "the probe never reported: " + " ".join(dom.split())[-400:]
    return json.loads(htmllib.unescape(m.group(1)))


def intersects(a: dict | None, b: dict | None) -> bool:
    """True when two rects share area. Touching edges do not count."""
    return bool(a and b) and not (a["r"] <= b["l"] or a["l"] >= b["r"] or a["b"] <= b["t"] or a["t"] >= b["b"])


# ---------------------------------------------------------------- the pages as text


def test_every_page_has_its_own_title_and_canonical(tmp_path):
    """Mutation: render one page under another's path, or drop the canonical link, and this fails."""
    _, _, rendered = site(tmp_path)
    assert set(rendered) == set(PAGE_PATHS)
    titles = {path: title_of(page) for path, page in rendered.items()}
    assert len(set(titles.values())) == len(PAGE_PATHS), f"pages share a title: {titles}"
    canonicals = {}
    for path, page in rendered.items():
        canonicals[path] = canonical_of(page)
        assert canonicals[path] == SITE + path.removesuffix("index.html"), (path, canonicals[path])
    assert len(set(canonicals.values())) == len(PAGE_PATHS), canonicals


def test_tab_bar_marks_exactly_the_current_page(tmp_path):
    """Every page, the globe included, marks one tab and it is the page's own. The 404 sits at the
    site root, so the tab it marks is the front page, and it marks it with a root-absolute href.

    Mutation: drop aria-current from pages.tabs and this fails on every page."""
    _, out, rendered = site(tmp_path)
    for path, page in rendered.items():
        current = current_tabs(tab_bar(page))
        assert len(current) == 1, f"{path}: {len(current)} tabs marked current: {current}"
        href, _ = current[0]
        assert lands_in(path, href) == own_dir(path), f"{path}: the current tab points at {href!r}"
    globe = (out / "globe" / "index.html").read_text(encoding="utf-8")
    current = current_tabs(tab_bar(globe))
    assert len(current) == 1, f"globe: {len(current)} tabs marked current: {current}"
    assert current[0][1] == "The globe"
    assert lands_in("globe/index.html", current[0][0]) == "globe", current[0]


def test_build_prunes_stale_html_but_keeps_probes(tmp_path):
    """A page this build did not write would otherwise ship forever with a frozen stamp. Probe
    pages are the exception: the browser tests plant them beside the site.

    Mutation: delete the prune loop at the end of build.main and the retired page survives."""
    _, out, rendered = site(tmp_path)
    retired = out / "retired" / "index.html"
    retired.parent.mkdir()
    retired.write_text("<!doctype html><title>retired</title>", encoding="utf-8")
    probe = out / "probe-something.html"
    probe.write_text("<!doctype html><title>probe</title>", encoding="utf-8")
    assert build.main(["--spool", str(tmp_path / "spool"), "--out", str(out)]) == 0
    assert not retired.exists(), "a page the build did not write survived the rebuild"
    assert probe.exists(), "the rebuild removed a probe page"
    for path in (*rendered, "globe/index.html"):
        assert (out / path).is_file(), path


def test_404_is_branded_and_links_home_absolutely(tmp_path):
    """Cloudflare Pages serves 404.html for a missing path at any depth, so a relative link on it
    resolves under whatever directory the visitor typed. Every link on the page must therefore be
    external, a fragment, or root-absolute: the wordmark's link home, the icons, the tabs, the
    ledger.

    Mutation: drop 404.html from render_site, or drop the root-relative rewrite in not_found, and
    this fails."""
    _, _, rendered = site(tmp_path)
    assert "404.html" in rendered, "render_site no longer publishes a 404 page"
    page = rendered["404.html"]
    wordmark = re.search(r'<h1><a href="([^"]*)">Ephemera</a></h1>', page)
    assert wordmark, "the 404 has no wordmark"
    assert '<svg class="mark"' in page, "the 404 has no mark"
    assert wordmark.group(1) == "/", f"the wordmark links home at {wordmark.group(1)!r}"
    icon = re.search(r'<link rel="icon" href="([^"]*)"', page)
    touch = re.search(r'<link rel="apple-touch-icon" href="([^"]*)"', page)
    assert icon and touch, "the 404 has no icon links"
    for link in (icon.group(1), touch.group(1)):
        assert link.startswith("/"), f"icon linked relatively: {link!r}"
    relative = sorted({h for h in hrefs(page)
                       if not h.startswith(("/", "#", "http://", "https://", "mailto:"))})
    assert not relative, f"relative links on the 404, broken at any depth: {relative}"


def test_print_palette_overrides_dark_tokens():
    """The pages are dark on screen. On paper the same tokens must carry a light palette, or the
    print is a black page with black text on it.

    Mutation: drop the :root block from the @media print rule and this fails."""
    root = css_block(pages.CSS, ":root")
    screen = {name: value.strip() for name, value in re.findall(r"(--bg|--ink)\s*:\s*([^;]+);", root)}
    assert set(screen) == {"--bg", "--ink"}, screen
    printed = css_block(pages.CSS, "@media print")
    paper = {name: value.strip() for name, value in re.findall(r"(--bg|--ink)\s*:\s*([^;]+);", printed)}
    assert set(paper) == {"--bg", "--ink"}, f"the print block does not redefine both tokens: {paper}"
    for name in ("--bg", "--ink"):
        assert paper[name] != screen[name], f"{name} is the same on paper as on screen: {paper[name]}"


def test_feed_health_prints_on_every_scored_page(tmp_path):
    """The register's truth-health indicator goes wherever a scored figure is shown: the front
    page, the finding and the scored table. The section that prints it names the headline cycle, so
    a reader knows which cycle's feed the health line describes.

    Mutation: drop the health line from any of the three pages and this fails."""
    ledger, _, rendered = site(tmp_path)
    head = build.headline_report(ledger["visibility"]["reports"])
    assert head, "the fixture has no comparable scored cycle"
    sha12 = head["cycle"][6:]
    for path in ("index.html", "finding/index.html", "scored/index.html"):
        flat = " ".join(rendered[path].split())
        assert FEED_HEALTH in flat, f"{path} shows scored figures without the feed health line"
        section = next(s for s in flat.split('<header class="z-full section"') if FEED_HEALTH in s)
        assert sha12 in section, f"{path}: the section with the health line does not name cycle {sha12}"


def test_scored_and_archive_rows_keep_stable_ids(tmp_path):
    """Row ids are the permanent addresses D20 promises: one s-<sha12> per report, one c-<sha12>
    per cycle, and every block on the front page's strip points at a cycle row that exists.

    Mutation: drop the id from scored_row or archive_row, or the href from cycle_strip, and this
    fails."""
    ledger, _, rendered = site(tmp_path)
    reports = [r["cycle"][6:] for r in ledger["visibility"]["reports"]]
    cycles = [c["cycle"][6:] for c in ledger["cycles"]]
    assert reports and len(cycles) > 1, "the fixture must have a report and several cycles"
    scored_ids = re.findall(r'<tr[^>]*\bid="s-([0-9a-f]{12})"', rendered["scored/index.html"])
    assert sorted(scored_ids) == sorted(reports), (scored_ids, reports)
    archive_ids = re.findall(r'<tr[^>]*\bid="c-([0-9a-f]{12})"', rendered["archive/index.html"])
    assert sorted(archive_ids) == sorted(cycles), (archive_ids, cycles)
    # The front page shows one 30-day row, so its blocks are the cycles first seen within 30 days
    # of the newest one; every block links to that cycle's archive row.
    seen = {c["cycle"][6:]: pages.parse_utc(c["first_seen_utc"]) for c in ledger["cycles"] if c["first_seen_utc"]}
    newest = max(seen.values())
    expected = {sha for sha, t in seen.items() if t > newest - timedelta(days=pages.STRIP_DAYS)}
    blocks = re.findall(r'<a href="archive/#c-([0-9a-f]{12})"><rect', rendered["index.html"])
    assert blocks, "the front page strip has no linked blocks"
    assert sorted(blocks) == sorted(expected), (blocks, expected)
    assert set(blocks) <= set(archive_ids)


def test_pack_size_is_printed_wherever_the_globe_is_offered(tmp_path):
    """The globe tab, the front page's globe bullet, the check page's data list and the globe's own
    status line all say how big the pack is, because a multi-megabyte download on a phone is a
    decision the reader makes before clicking. Rendered without a pack, no figure appears at all.
    The pages are read from the build's output, so the figure has to travel from build.main.

    Mutation: pass None instead of pack_bytes from build.main to render_site and this fails."""
    ledger, out, _ = site(tmp_path)
    pack = out / "globe" / "pack.json"
    assert pack.exists(), "the fixture built no globe pack"
    mb = f"{pack.stat().st_size / 1e6:.1f} MB"
    for path in ("index.html", "check/index.html", "globe/index.html"):
        doc = (out / path).read_text(encoding="utf-8")
        assert f"loads a {mb} pack" in tab_bar(doc), f"{path}: the globe tab does not say the pack is {mb}"
    assert f"a {mb} pack, needs WebGL" in (out / "index.html").read_text(encoding="utf-8")
    assert f"({mb})" in (out / "check" / "index.html").read_text(encoding="utf-8")
    assert f"Loading the globe pack ({mb}, WebGL needed)." in (out / "globe" / "index.html").read_text(encoding="utf-8")
    without = build.render_site(ledger, None)
    assert "MB pack" not in without["index.html"], "the front page prints a pack size with no pack"
    assert "MB)" not in without["check/index.html"], "the check page prints a pack size with no pack"
    assert "loads a" not in tab_bar(without["index.html"])


def test_every_internal_link_and_asset_resolves(tmp_path):
    """Every href and src on every built page, the globe included, that is not external, mailto,
    data or a bare fragment must name a file the build wrote: resolved from the page's own
    directory, or from the root when it starts with a slash, with a directory standing for its
    index.html. A renamed asset or a page that moved shows up here before a visitor finds it.

    Mutation: stop copying icon.svg into globe/ in build.main, or misspell an href in pages.tabs,
    and this fails."""
    _, out, rendered = site(tmp_path)
    missing = []
    for path in (*rendered, "globe/index.html"):
        doc = (out / path).read_text(encoding="utf-8")
        for target in re.findall(r'(?:href|src)="([^"]*)"', doc):
            if target.startswith(("http://", "https://", "mailto:", "#", "data:")):
                continue
            bare = target.split("#", 1)[0].split("?", 1)[0]
            if not bare:
                continue
            rel = bare[1:] if bare.startswith("/") else posixpath.join(posixpath.dirname(path), bare)
            file = out / posixpath.normpath(rel)
            if file.is_dir():
                file = file / "index.html"
            if not file.is_file():
                missing.append((path, target))
    assert not missing, f"links to nothing: {missing}"


def test_strip_draws_a_pull_in_progress_hollow_not_red(tmp_path):
    """A pull still running is not a defect. The front page's strip draws it hollow in its own
    class and says so in the caption; only a gapped pull is red.

    Mutation: drop the in-progress branch from cycle_strip's class rule and this fails."""
    ledger, _, rendered = site(tmp_path)
    running = [c["cycle"][6:] for c in ledger["cycles"] if c["status"] == "in-progress"]
    gapped = [c["cycle"][6:] for c in ledger["cycles"] if c["status"] != "in-progress" and not c["merkle_root"]]
    assert running and gapped, "the fixture needs one pull in progress and one gapped pull"
    front = rendered["index.html"]
    for sha in running:
        assert re.search(rf'<a href="archive/#c-{sha}"><rect class="pulling"', front), f"{sha} is not drawn as a pull in progress"
    for sha in gapped:
        assert re.search(rf'<a href="archive/#c-{sha}"><rect class="miss"', front), f"{sha} is not drawn red"
    assert "a hollow block is a pull still running" in front


# ---------------------------------------------------------------- the pages in a browser


def test_only_defects_toggle_hides_the_healthy_rows(tmp_path):
    """The scored and archive tables grow by three rows a day. The box above each keeps only the
    rows with a defect (or hindsight) and the month heads, so a reader looking for trouble does not
    scroll past the healthy majority. Measured in a browser by ticking the box.

    Mutation: drop the TOGGLE script from the archive or scored page, or the body.only-defects rule
    from the stylesheet, and this fails."""
    if CHROME is None:
        pytest.skip("no Chrome/Chromium installed")
    _, out, _ = site(tmp_path)
    rows = probe_json(out, "probe-toggle.html", """
      const paths = ["archive/", "scored/"];
      function visible(doc) {
        return [...doc.querySelectorAll("tbody tr")].filter(tr => tr.getClientRects().length > 0)
               .map(tr => tr.className || "");
      }
      async function measure(path) {
        const f = document.createElement("iframe");
        f.style.cssText = "width:1200px;height:900px;border:0;display:block";
        document.body.appendChild(f);
        await new Promise((res) => { f.onload = res; f.src = "/" + path; });
        const doc = f.contentDocument, box = doc.getElementById("only-defects");
        const before = visible(doc);
        if (box) box.click();
        const after = visible(doc);
        f.remove();
        return {path, has_box: !!box, before, after};
      }
      addEventListener("load", async () => {
        const rows = [];
        for (const p of paths) rows.push(await measure(p));
        document.body.insertAdjacentHTML("afterbegin", "<pre id=probe>" + JSON.stringify(rows) + "</pre>");
      });
    """)
    kept = {"gap", "warn", "hind", "head"}
    assert [row["path"] for row in rows] == ["archive/", "scored/"], rows
    for row in rows:
        assert row["has_box"], f"{row['path']} has no only-defects box"
        healthy = [c for c in row["before"] if not set(c.split()) & kept]
        assert healthy, f"{row['path']}: the fixture has no healthy row to hide"
        assert row["after"] == [c for c in row["before"] if set(c.split()) & kept], (
            f"{row['path']}: ticking the box did not leave exactly the defect rows and month heads: {row}")



def test_layout_holds_at_three_widths(tmp_path):
    """No page scrolls sideways at 390, 1024 or 1440 px, and the front page's side column sits
    beside the prose in both multi-column regimes and below it on a phone.

    Each width is an iframe of exactly that width inside one 1600 px window, because headless
    Chrome will not open a window narrower than about 500 px (see CHROME_ARGS); media queries and
    vw units inside an iframe follow the iframe, so 390 is a true 390. The overflow check compares
    scrollWidth with clientWidth, which is innerWidth less the scrollbar and so the stricter of the
    two.

    Mutation: give `.z-side` a fixed width wider than its columns, or drop the 47.99rem media
    query, and this fails."""
    if CHROME is None:
        pytest.skip("no Chrome/Chromium installed")
    _, out, _ = site(tmp_path)
    rows = probe_json(out, "probe-layout.html", """
      const paths = %s, widths = [390, 1024, 1440];
      function box(doc, sel) { const e = doc.querySelector(sel); if (!e) return null;
        const r = e.getBoundingClientRect(); return {l: r.left, r: r.right, t: r.top, b: r.bottom}; }
      async function measure(path, w) {
        const f = document.createElement("iframe");
        f.style.cssText = "width:" + w + "px;height:900px;border:0;display:block";
        document.body.appendChild(f);
        await new Promise((res) => { f.onload = res; f.src = "/" + path; });
        const win = f.contentWindow, doc = win.document;
        const row = {path, w, inner: win.innerWidth, client: doc.documentElement.clientWidth,
                     scroll: doc.documentElement.scrollWidth, prose: box(doc, ".z-prose"), side: box(doc, ".z-side")};
        f.remove();
        return row;
      }
      addEventListener("load", async () => {
        const rows = [];
        for (const w of widths) for (const p of paths) rows.push(await measure(p, w));
        document.body.insertAdjacentHTML("afterbegin", "<pre id=probe>" + JSON.stringify(rows) + "</pre>");
      });
    """ % json.dumps(list(PAGE_PATHS)))
    assert len(rows) == 3 * len(PAGE_PATHS), rows
    for row in rows:
        assert row["inner"] == row["w"], f"{row['path']}: the iframe viewport is {row['inner']}, not {row['w']}"
        assert row["scroll"] <= row["client"], (f"{row['path']} scrolls sideways at {row['w']}px: "
                                                f"scrollWidth {row['scroll']} > clientWidth {row['client']}")
    front = {row["w"]: row for row in rows if row["path"] == "index.html"}
    for w in (1024, 1440):
        prose, side = front[w]["prose"], front[w]["side"]
        assert side["l"] > prose["r"], f"at {w}px the side column is not beside the prose: {prose} {side}"
    prose, side = front[390]["prose"], front[390]["side"]
    assert side["t"] >= prose["b"], f"at 390px the side column is not below the prose: {prose} {side}"


def test_globe_top_panel_never_overlaps_the_side_panel_or_caveats(tmp_path):
    """The globe's status panel (#top) is capped at 46vh and the caveats (#foot) sit above the
    timeline; the side panel (#right) hides under 800 px. At 400, 900 and 1560 px none of them may
    cover another. Widths are iframes for the reason test_layout_holds_at_three_widths gives.

    Mutation: remove the max-height from #top and this fails at 400 px."""
    if CHROME is None:
        pytest.skip("no Chrome/Chromium installed")
    _, out, _ = site(tmp_path)
    rows = probe_json(out, "probe-globe.html", """
      const widths = [400, 900, 1560];
      function box(doc, id) { const e = doc.getElementById(id); if (!e) return null;
        const r = e.getBoundingClientRect();
        if (doc.defaultView.getComputedStyle(e).display === "none" || r.height === 0) return null;
        return {l: r.left, r: r.right, t: r.top, b: r.bottom}; }
      async function measure(w) {
        const f = document.createElement("iframe");
        f.style.cssText = "width:" + w + "px;height:900px;border:0;display:block";
        document.body.appendChild(f);
        await new Promise((res) => { f.onload = res; f.src = "/globe/"; });
        await new Promise((res) => setTimeout(res, 3000));
        const doc = f.contentDocument;
        const row = {w, inner: f.contentWindow.innerWidth,
                     top: box(doc, "top"), right: box(doc, "right"), foot: box(doc, "foot")};
        f.remove();
        return row;
      }
      addEventListener("load", async () => {
        const rows = [];
        for (const w of widths) rows.push(await measure(w));
        document.body.insertAdjacentHTML("afterbegin", "<pre id=probe>" + JSON.stringify(rows) + "</pre>");
      });
    """)
    assert [row["w"] for row in rows] == [400, 900, 1560], rows
    for row in rows:
        w = row["w"]
        assert row["inner"] == w, f"the iframe viewport is {row['inner']}, not {w}"
        assert row["top"] and row["foot"], f"at {w}px the status panel or the caveats are not rendered: {row}"
        if w > 800:
            assert row["right"], f"at {w}px the side panel is not rendered: {row}"
        assert not intersects(row["top"], row["right"]), f"at {w}px #top covers #right: {row}"
        assert not intersects(row["top"], row["foot"]), f"at {w}px #top covers #foot: {row}"
