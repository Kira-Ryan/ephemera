"""D20's year rule and the /scored/ chart past 365 reports: what the pages say from the first cycle of
a new year, where the older rows go, and that no published address breaks when they move."""
from __future__ import annotations

import json
import posixpath
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402
from test_build import CHROME, serve, utc  # noqa: E402
from test_build_visibility import add_catalogue, add_score, make_spool, page_at, text  # noqa: E402

# make_spool places cycles a and b on 31 Dec 2026 and c and e on 1 Jan 2027.
TURN = datetime(2027, 1, 1, 10, 0, tzinfo=timezone.utc)
A, B, C, E = "aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc", "eeeeeeeeeeee"


def two_year_site(tmp_path: Path, monkeypatch) -> tuple[dict, Path]:
    spool = make_spool(tmp_path, TURN)
    add_catalogue(spool)
    add_score(spool, cycle=f"cycle_{C}", first_seen=utc(TURN - timedelta(hours=8)))
    add_score(spool, cycle=f"cycle_{A}", first_seen=utc(TURN - timedelta(hours=30)))
    out = tmp_path / "dist"
    monkeypatch.setattr(build, "utc_now", lambda: TURN)
    assert build.main(["--spool", str(spool), "--out", str(out)]) == 0
    return json.loads((out / "ledger.json").read_text(encoding="utf-8")), out


def said(doc: str) -> str:
    """The page's words, with the space text() leaves where a link's closing tag met a full stop."""
    return text(doc).replace(" .", ".")


def row_ids(page: str, prefix: str) -> set[str]:
    return set(re.findall(rf'<tr[^>]*\bid="{prefix}-([0-9a-f]{{12}})"', page))


def test_each_year_holds_its_own_rows(tmp_path, monkeypatch):
    """Mutation: render every cycle on the landing page, or drop the year pages from
    pages.render_site, and this fails."""
    _, out = two_year_site(tmp_path, monkeypatch)
    landing, older = page_at(out, "archive"), (out / "archive" / "2026" / "index.html").read_text(encoding="utf-8")
    assert row_ids(landing, "c") == {C, E} and row_ids(older, "c") == {A, B}
    scored, scored_older = page_at(out, "scored"), (out / "scored" / "2026" / "index.html").read_text(encoding="utf-8")
    assert row_ids(scored, "s") == {C} and row_ids(scored_older, "s") == {A}
    assert '<tbody class="month" id="m-2026-12"' not in landing and '<tbody class="month" id="m-2026-12"' in older
    assert '<tbody class="month" id="m-2027-01"' in landing and '<tbody class="month" id="m-2027-01"' not in older
    assert 'href="https://ephemera.space/archive/2026/"' in older or 'canonical" href="https://ephemera.space/archive/2026/"' in older
    assert '<title>Ephemera: The archive, 2026</title>' in older and '<title>Ephemera: Scored cycles, 2026</title>' in scored_older
    # a year page's strip links to the rows on that page, not round through the landing page's stubs
    assert f'<a href="#c-{A}"><rect' in older and f'href="../../archive/#c-{A}"><rect' not in older
    # the tab bar still marks the archive as the current page, from one level further down
    assert '<a href="../../archive/" aria-current="page">' in older


def test_the_year_statements_are_true_on_both_pages(tmp_path, monkeypatch):
    """From the first cycle of 2027 the old code printed "2027 so far; earlier years get their own page
    once they exist" above 2026's rows, and "2027: 205 scored" counting every year.

    Mutation: count every report in the /scored/ stamp, or keep the old sentence, and this fails."""
    _, out = two_year_site(tmp_path, monkeypatch)
    landing = said(page_at(out, "archive"))
    assert "2027 so far. Earlier years: 2026." in landing and "once they exist" not in landing
    assert "Every cycle of 2027, newest first" in landing and "Every cycle of 2027, one block per cycle" in landing
    older = said((out / "archive" / "2026" / "index.html").read_text(encoding="utf-8"))
    assert "Every cycle of 2026. Other years: 2027." in older
    assert "Every cycle of 2026, newest first" in older and "Every cycle of 2026, one block per cycle" in older
    scored = said(page_at(out, "scored"))
    assert "2027: 1 scored, 1 live, 0 with hindsight. Earlier years: 2026." in scored
    assert "Every scored cycle of 2027: the share" not in scored         # one point draws no chart
    older_scored = said((out / "scored" / "2026" / "index.html").read_text(encoding="utf-8"))
    assert "2026: 1 scored, 1 live, 0 with hindsight. Other years: 2027." in older_scored
    # the figures that are about everything stay about everything, on every year's page
    for doc in (scored, older_scored):
        assert "2 cycles scored so far" in doc


def test_a_day_root_sits_with_its_own_year(tmp_path, monkeypatch):
    _, out = two_year_site(tmp_path, monkeypatch)
    older, landing = (out / "archive" / "2026" / "index.html").read_text(encoding="utf-8"), page_at(out, "archive")
    assert "<td>2026-12-31</td>" in older and "<td>2026-12-31</td>" not in landing
    assert "the first daily root of 2027 arrives after its first full UTC day" in text(landing)


def test_every_row_link_resolves_from_every_page(tmp_path, monkeypatch):
    """D20: a row's URL never moves. Every link to a row on every page, followed as a browser would,
    lands on an element with that id: the row itself, or the stub that sends the reader on.

    Mutation: drop moved_rows from either landing page, or link the strip on a year page to the wrong
    place, and this fails."""
    _, out = two_year_site(tmp_path, monkeypatch)
    pages_built = [p.relative_to(out).as_posix() for p in out.rglob("index.html")]
    checked = 0
    for path in pages_built:
        doc = (out / path).read_text(encoding="utf-8")
        for href, frag in re.findall(r'href="([^"#]*)#((?:c|s|m)-[0-9a-f-]+)"', doc):
            target = path if not href else posixpath.normpath(posixpath.join(posixpath.dirname(path), href, "index.html"))
            assert f'id="{frag}"' in (out / target).read_text(encoding="utf-8"), (path, href, frag)
            checked += 1
    assert checked > 10
    # and the addresses already published, written the only way they have ever been written
    for page, frag in (("archive", f"c-{A}"), ("archive", f"c-{B}"), ("archive", "m-2026-12"), ("scored", f"s-{A}")):
        assert f'id="{frag}"' in page_at(out, page), frag


def test_the_stub_sends_the_reader_to_the_row_in_a_real_browser(tmp_path, monkeypatch):
    """A green flag is not a picture: an address published last year has to reach its row today.

    Mutation: drop MOVED_SCRIPT from moved_rows and this fails, because the browser stays put."""
    if CHROME is None:
        pytest.skip("no Chrome/Chromium installed")
    _, out = two_year_site(tmp_path, monkeypatch)
    srv = serve(out)
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}/"
        doms = {}
        for name, url in (("archive", f"archive/#c-{A}"), ("scored", f"scored/#s-{A}"), ("current", f"archive/#c-{C}")):
            r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--virtual-time-budget=5000", "--dump-dom", base + url],
                               capture_output=True, timeout=90)
            doms[name] = r.stdout.decode("utf-8", "replace")
    finally:
        srv.shutdown()
    assert 'rel="canonical" href="https://ephemera.space/archive/2026/"' in doms["archive"]
    assert re.search(rf'<tr[^>]*id="c-{A}"', doms["archive"])
    assert 'rel="canonical" href="https://ephemera.space/scored/2026/"' in doms["scored"]
    # a row of the current year stays where it is
    assert 'rel="canonical" href="https://ephemera.space/archive/"' in doms["current"]


def test_one_year_has_no_year_pages_and_keeps_its_wording(tmp_path):
    spool = make_spool(tmp_path, datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc))
    add_catalogue(spool)
    add_score(spool)
    out = tmp_path / "dist"
    assert build.main(["--spool", str(spool), "--out", str(out)]) == 0
    assert not (out / "archive" / "2026").exists() and not (out / "scored" / "2026").exists()
    archive = text(page_at(out, "archive"))
    assert "2026 so far; earlier years get their own page once they exist." in archive
    assert "Every cycle kept, one block per cycle" in archive
    assert "data-year" not in page_at(out, "archive") and "data-year" not in page_at(out, "scored")


def test_the_history_chart_keeps_one_linked_point_per_report_past_365(tmp_path):
    """The old code folded the chart into one point per UTC day at the 366th report, about 113 days of
    cycles, not the year its comment said. Its links then pointed at "#s-2026-08-31, 1 cycles", which
    resolves to nothing, and the caption's counts became counts of days.

    Mutation: restore the daily fold in pages.visibility_history and this fails."""
    spool = make_spool(tmp_path, datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc))
    add_catalogue(spool)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    shas = [f"{i:012x}" for i in range(400)]
    for i, sha in enumerate(shas):
        add_score(spool, cycle=f"cycle_{sha}", with_pack=False, first_seen=utc(start + timedelta(hours=7 * i)))
    out = tmp_path / "dist"
    assert build.main(["--spool", str(spool), "--out", str(out)]) == 0
    doc = page_at(out, "scored")
    points = re.findall(r'<a href="#s-([0-9a-f]{12})"><circle', doc)
    assert sorted(points) == sorted(shas)
    assert row_ids(doc, "s") == set(shas)
    assert "400 live, 0 hindsight" in text(doc)
