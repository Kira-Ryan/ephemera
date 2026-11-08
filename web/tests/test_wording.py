"""Sentences a check of the live site found to be false as written (5 Nov 2026). Each test holds the
wording to what the rendered page can stand behind, on the page a reader would see it on."""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402
from test_build import utc  # noqa: E402
from test_build_visibility import NOW, add_catalogue, add_score, build_site, make_spool, page_at, text  # noqa: E402

CAME = NOW - timedelta(hours=8)


def test_1000_km_is_not_called_most_of_an_orbit(tmp_path):
    """1,000 km is about 2.3% of a 43,000 km orbit, and specialists are the first audience.

    Mutation: restore either phrase in pages.lost_line or the globe's legend and this fails."""
    _, front, out = build_site(tmp_path)
    finding, globe = page_at(out, "finding"), (out / "globe" / "index.html").read_text(encoding="utf-8")
    for doc in (front, finding, globe):
        assert "most of an orbit" not in doc and "large part of an orbit" not in doc
    for doc in (front, finding):
        assert "more than two minutes of flight along the orbit" in text(doc)


def test_the_hindsight_sentence_says_the_share_falls(tmp_path):
    """The count has been 7 since September and cannot fall, because a scored cycle is never re-scored.

    Mutation: restore "the count only falls" in pages.scored and this fails."""
    _, _, out = build_site(tmp_path, relation="after_cycle")
    doc = text(page_at(out, "scored"))
    assert "that share only falls from here" in doc and "the count only falls" not in doc


def test_the_globe_does_not_describe_a_list_that_is_not_there(tmp_path):
    """The satellites past 1,000 km were said to be "listed apart" and were listed nowhere, under a
    heading calling the rest the largest deviations.

    Mutation: restore the sentence or the heading in web/globe/index.html and this fails."""
    _, _, out = build_site(tmp_path)
    globe = (out / "globe" / "index.html").read_text(encoding="utf-8")
    assert "listed apart" not in globe and "Largest deviation in this cycle" not in globe
    assert "They are left out of the list below" in globe and "Largest deviation up to 1,000 km" in globe
    # and the counts near either end of the timeline say what they are
    assert "the counts are mostly held values" in " ".join(globe.split())


def test_the_check_page_does_not_overclaim(tmp_path):
    """Mutation: restore any of these sentences in pages.check and this fails."""
    _, _, out = build_site(tmp_path)
    check = text(page_at(out, "check"))
    assert "the moment it is caught" not in check and "soon after it is caught" in check
    assert "an older globe can be replayed" not in check and "only loads the headline cycle's" in check
    assert "published under proofs/<cycle>/ and proofs/daily/<date>/" in check.replace("&lt;", "<").replace("&gt;", ">")


def test_the_archive_says_a_verified_link_can_answer_404(tmp_path):
    """Rows say "manifest ok" beside a link the Wayback Machine may not serve that week. The sentence
    is dated and carries its count, and it calls the cause what it is.

    Mutation: drop the sentence from pages.archive and this fails."""
    _, _, out = build_site(tmp_path)
    doc = text(page_at(out, "archive"))
    assert "Of the 18 that did on 5 Nov 2026, 15 served the right bytes again on 8 Nov" in doc
    assert "which is an inference" in doc
    assert "NEVER CAPTURED" not in doc


def test_the_404_says_only_what_is_true(tmp_path):
    """The daily-roots and finding tables have no row ids, and the front page is the first tab.

    Mutation: restore "Every table row" or "one tab to the left" in pages.not_found and this fails."""
    _, _, out = build_site(tmp_path)
    doc = text((out / "404.html").read_text(encoding="utf-8"))
    assert "Every table row" not in doc and "one tab to the left" not in doc
    assert "Every cycle has a permanent address" in doc and "the first tab above" in doc


def test_the_strip_caption_allows_for_the_poller_being_down(tmp_path):
    """The same page counts intervals that fell while the poller was down, so a gap is not always the
    feed's own cadence.

    Mutation: restore the unqualified sentence in pages.cycle_strip and this fails."""
    _, front, out = build_site(tmp_path)
    for doc in (front, page_at(out, "archive")):
        assert "the feed's own cadence, apart from any the poller was down for" in text(doc).replace("&#x27;", "'")


def test_a_month_of_one_cycle_is_not_plural(tmp_path):
    """Mutation: write the count without pages.n_cycles in either month heading and this fails."""
    _, _, out = build_site(tmp_path)
    assert "1 cycles," not in text(page_at(out, "scored"))
    assert "1 cycle, 1 live, 0 hindsight, 0 with nothing scored" in text(page_at(out, "scored"))
    assert " 1 cycles," not in text(page_at(out, "archive"))


def test_cycles_with_no_report_are_named_not_left_out(tmp_path):
    """/scored/ printed "0 with nothing scored" while six archived cycles had no report and no row, and
    the footer promises gapped or lost items are printed, never hidden. A cycle newer than the newest
    report is only waiting its turn and is not named.

    Mutation: drop missing_note from pages.scored, or the age test from pages.no_report, and this fails."""
    spool = make_spool(tmp_path, NOW)
    add_catalogue(spool)
    add_score(spool, first_seen=utc(CAME))                     # c and a are scored; b is older than c, e is newer
    add_score(spool, cycle="cycle_aaaaaaaaaaaa", first_seen=utc(NOW - timedelta(hours=30)))
    out = tmp_path / "dist"
    assert build.main(["--spool", str(spool), "--out", str(out)]) == 0
    doc = text(page_at(out, "scored"))
    assert "1 cycle in the archive has no report and no row here: bbbbbbbbbbbb." in doc
    assert "1 cycle, 1 live, 0 hindsight, 0 with nothing scored, 1 cycle with no report" in doc


def test_a_root_waiting_for_its_block_is_not_called_a_failing_copy(tmp_path):
    """The worked example is often not the newest cycle, because a new root waits hours for its block.
    /check/ then told readers the independent copies had been failing, which was on the live page on
    8 Nov 2026 with every copy healthy.

    Mutation: restore the fixed sentence in pages.kit_is_stale and this fails."""
    _, _, out = build_site(tmp_path)                           # cycle c's copy verified, its block is pending
    check = text(page_at(out, "check"))
    assert "is not the newest one" in check
    assert "cycles since then do not have all of these yet" in check
    assert "failed" not in check.split("is not the newest one")[1].split("Fetch an independent copy")[0]
    assert "have been failing" not in check
