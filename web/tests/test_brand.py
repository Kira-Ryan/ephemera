"""The mark is generated from geometry, so the geometry is what gets tested: the arcs sit on the
ring, the pieces land on the 4-unit grid that makes a 16 pixel favicon crisp, the SVG is
self-contained, and the raster assets come out the right size. The one thing a test cannot judge is
whether it looks good; that was checked by rendering it at true favicon sizes in a browser.
"""
from __future__ import annotations

import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import brand  # noqa: E402


def test_every_arc_endpoint_lies_on_the_ring():
    for start, end, _ in brand.ARCS:
        for angle in (start, end):
            x, y = brand.point(angle)
            assert math.isclose(math.hypot(x - brand.CENTRE, y - brand.CENTRE), brand.RADIUS, abs_tol=1e-9)


def test_arcs_and_gaps_cover_the_circle_exactly_once():
    spans = sorted((min(s, e), max(s, e)) for s, e, _ in brand.ARCS)
    covered = sum(hi - lo for lo, hi in spans)
    gaps = [spans[i + 1][0] - spans[i][1] for i in range(len(spans) - 1)]
    assert math.isclose(covered, 276.0)                 # three 92 degree arcs
    assert all(math.isclose(g, 20.0) for g in gaps)     # 20 degree gaps between them
    assert math.isclose(360.0 - covered - sum(gaps), 44.0)   # and 44 degrees left for the head


def test_head_sits_inside_the_wide_gap_and_clear_of_the_arcs():
    ends = [a for s, e, _ in brand.ARCS for a in (s, e)]
    nearest = min(abs(brand.HEAD - a) for a in ends)
    assert nearest >= 20.0, "the head would fuse with an arc end"
    # and clear of the centre block: the head is on the ring, the block is a square at the centre
    hx, hy = brand.point(brand.HEAD)
    assert math.hypot(hx - brand.CENTRE, hy - brand.CENTRE) - brand.BULB_R > brand.BLOCK / 2 * math.sqrt(2)


def test_geometry_lands_on_the_grid_that_makes_16px_crisp():
    """64 units render into 16 device pixels, so one pixel is 4 units. The pieces that carry
    recognition at that size are sized in whole pixels."""
    for value in (brand.BOX, brand.STROKE, brand.BLOCK):
        assert value % 4 == 0, value
    assert (brand.CENTRE - brand.BLOCK / 2) % 4 == 0
    assert brand.RADIUS * 2 % 4 == 0


def test_mark_is_self_contained_valid_svg():
    svg = brand.mark_svg()
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg") and root.get("viewBox") == "0 0 64 64"
    assert "href" not in svg and "url(" not in svg and "<image" not in svg and "font" not in svg
    assert len(svg) < 3000
    paths = [e for e in root.iter() if e.tag.endswith("path")]
    assert len(paths) == len(brand.ARCS)
    for p in paths:
        assert re.fullmatch(r"M[\d.]+ [\d.]+A22 22 0 [01] 0 [\d.]+ [\d.]+", p.get("d")), p.get("d")
    assert [e for e in root.iter() if e.tag.endswith("circle")]
    assert len([e for e in root.iter() if e.tag.endswith("rect")]) == 2   # plate and centre block


def test_the_three_arcs_fade():
    root = ET.fromstring(brand.mark_svg())
    ops = [float(p.get("opacity", 1.0)) for p in root.iter() if p.tag.endswith("path")]
    assert ops == sorted(ops, reverse=True) and ops[0] == 1.0 and ops[-1] < 0.3


def test_transparent_variant_has_no_plate_and_a_single_colour_variant_exists():
    plain = brand.mark_svg(ground=None)
    assert plain.count("<rect") == 1                        # the centre block only
    mono = brand.mark_svg(ground=None, ink="currentColor")
    assert "currentColor" in mono and "#ffb347" not in mono


def test_inline_mark_is_decorative_and_sized():
    m = brand.inline_mark(44)
    assert 'class="mark"' in m and 'width="44"' in m
    assert 'aria-hidden="true"' in m and "<title>" not in m   # the wordmark beside it says the name
    assert 'role="img"' not in m


def test_raster_assets_are_written_at_the_right_sizes(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image
    written = brand.write_all(tmp_path, "headline line one\nline two", "sub")
    assert {p.name for p in written} == {"icon.svg", "icon-180.png", "icon-512.png", "social.png"}
    assert Image.open(tmp_path / "icon-180.png").size == (180, 180)
    assert Image.open(tmp_path / "icon-512.png").size == (512, 512)
    assert Image.open(tmp_path / "social.png").size == (1200, 630)


def test_icon_is_actually_drawn_and_not_a_blank_plate(tmp_path):
    """A generator that silently drew nothing would still write a valid PNG."""
    pytest.importorskip("PIL")
    from PIL import Image
    brand.write_icon_png(tmp_path / "i.png", 64)
    img = Image.open(tmp_path / "i.png").convert("RGB")
    pixels = [img.getpixel((x, y)) for x in range(img.width) for y in range(img.height)]
    amber = sum(1 for px in pixels if px[0] > 180 and 120 < px[1] < 220 and px[2] < 140)
    assert amber > 300, f"only {amber} amber pixels: the mark did not draw"
    assert img.getpixel((2, 2)) != img.getpixel((32, 32)), "centre and corner are identical"
