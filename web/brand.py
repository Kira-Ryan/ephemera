#!/usr/bin/env python3
"""The Ephemera mark, generated from geometry rather than drawn by hand, plus the raster assets the
browser and the social crawlers need.

THE MARK. A ring cut into three arcs with the same amber at three brightnesses, and a solid block at
the centre. The ring is one day, cut into the three eight-hour cycles the feed actually publishes.
The bright arc at the top is the set on the wire now, the next one back is dimmer, the one behind
that is nearly gone: read anticlockwise the record is being erased in front of you, which is what
the source does every eight hours. The block in the middle does not fade. That is the archive, and
it is also a block in the sense the OpenTimestamps proof means, since the root of each cycle ends
up in one.

WHY IT IS GENERATED. The whole point of the project is that a number should carry how it was made.
The mark is held to the same standard: every coordinate comes from `RADIUS`, `CENTRE` and the arc
table below, so the geometry is checkable and the 16 pixel behaviour is a consequence of the grid
rather than a hope. The viewBox is 64 units and every edge lands on a multiple of 4, so one device
pixel at a 16 pixel favicon is exactly 4 units and nothing needs to be antialiased into mud.

Run this module directly to write the assets into web/dist.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

BOX = 64
CENTRE = 32.0
RADIUS = 22.0
STROKE = 8.0
BULB_R = 6.0
BLOCK = 16.0

# The whole figure is turned 45 degrees so the head sits at one o'clock. Upright, a node at twelve
# above a block at the centre reads as a head on a body, which is a thing this mark is not.
ROTATION = 45.0
HEAD = 45.0                      # the head of the trace, centred in the 44 degree gap

# (start angle, end angle, opacity). Degrees clockwise from twelve o'clock, before rotation; the
# arcs run anticlockwise from the head, so each pair goes from the larger angle to the smaller one.
# The gap at the head is 44 degrees so the node sits inside it instead of fusing with the bright
# arc; the other two gaps are 20 degrees, wide enough to survive a 16 pixel raster.
ARCS = tuple((s + ROTATION, e + ROTATION, o) for s, e, o in
             ((-22.0, -114.0, 1.00), (-134.0, -226.0, 0.52), (-246.0, -338.0, 0.26)))

INK = "#0c0f1d"
AMBER = "#ffb347"
BONE = "#eceada"


def point(angle_deg: float, radius: float = RADIUS) -> tuple[float, float]:
    """A point on the ring. Angle is degrees clockwise from twelve o'clock."""
    a = math.radians(angle_deg)
    return (CENTRE + radius * math.sin(a), CENTRE - radius * math.cos(a))


def arc_path(start_deg: float, end_deg: float) -> str:
    """An SVG arc from start to end the short way round, anticlockwise on screen (sweep 0)."""
    x1, y1 = point(start_deg)
    x2, y2 = point(end_deg)
    large = 1 if abs(end_deg - start_deg) > 180 else 0
    return f"M{x1:.2f} {y1:.2f}A{RADIUS:g} {RADIUS:g} 0 {large} 0 {x2:.2f} {y2:.2f}"


def mark_svg(ground: str | None = INK, ink: str = AMBER, radius: float = 12.0, title: str = "Ephemera") -> str:
    """The square mark. `ground` None gives a transparent plate for use inside a page."""
    bx, by = point(HEAD)
    body = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {BOX} {BOX}" role="img" aria-label="{title}">',
            f"<title>{title}</title>"]
    if ground:
        body.append(f'<rect width="{BOX}" height="{BOX}" rx="{radius:g}" fill="{ground}"/>')
    body.append(f'<g fill="none" stroke="{ink}" stroke-width="{STROKE:g}">')
    body += [f'<path d="{arc_path(s, e)}"{"" if o == 1.0 else f" opacity={chr(34)}{o:g}{chr(34)}"}/>' for s, e, o in ARCS]
    body.append("</g>")
    body.append(f'<circle cx="{bx:.2f}" cy="{by:.2f}" r="{BULB_R:g}" fill="{ink}"/>')
    body.append(f'<rect x="{CENTRE - BLOCK / 2:g}" y="{CENTRE - BLOCK / 2:g}" '
                f'width="{BLOCK:g}" height="{BLOCK:g}" fill="{ink}"/>')
    body.append("</svg>")
    return "".join(body)


def inline_mark(px: int = 40) -> str:
    """The mark for the masthead: no plate, sized, and hidden from assistive tech because the
    wordmark beside it already says the name."""
    svg = mark_svg(ground=None, title="")
    svg = svg.replace('<svg ', f'<svg class="mark" width="{px}" height="{px}" ', 1)
    svg = svg.replace(' role="img" aria-label=""', ' aria-hidden="true" focusable="false"')
    return svg.replace("<title></title>", "")


def _draw_mark(draw, size: int, scale: float, ox: float, oy: float, ink: tuple[int, int, int]) -> None:
    """The same geometry rendered with Pillow, for the raster assets."""
    def sc(v: float) -> float:
        return v * scale

    box = [ox + sc(CENTRE - RADIUS), oy + sc(CENTRE - RADIUS), ox + sc(CENTRE + RADIUS), oy + sc(CENTRE + RADIUS)]
    for start, end, opacity in ARCS:
        # Pillow measures degrees anticlockwise from three o'clock; the mark measures clockwise from
        # twelve. Both endpoints convert with a - 90, and the sweep direction flips with them.
        a1, a2 = min(start, end) - 90, max(start, end) - 90
        shade = tuple(round(c * opacity) for c in ink)
        draw.arc(box, a1, a2, fill=shade, width=max(1, round(sc(STROKE))))
    bx, by = point(HEAD)
    r = sc(BULB_R)
    draw.ellipse([ox + sc(bx) - r, oy + sc(by) - r, ox + sc(bx) + r, oy + sc(by) + r], fill=ink)
    h = sc(BLOCK) / 2
    draw.rectangle([ox + sc(CENTRE) - h, oy + sc(CENTRE) - h, ox + sc(CENTRE) + h, oy + sc(CENTRE) + h], fill=ink)


def _rgb(h: str) -> tuple[int, int, int]:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def write_icon_png(path: Path, size: int, ground: str | None = INK) -> None:
    from PIL import Image, ImageDraw  # noqa: PLC0415
    ss = 8                                    # supersample, then box filter down
    img = Image.new("RGBA", (size * ss, size * ss), (*_rgb(ground), 255) if ground else (0, 0, 0, 0))
    _draw_mark(ImageDraw.Draw(img), size, size * ss / BOX, 0, 0, _rgb(AMBER))
    img.resize((size, size), Image.LANCZOS).save(path)


def write_social_png(path: Path, headline: str, sub: str) -> None:
    """The 1200x630 card. Crawlers do not render SVG reliably, so this one is a raster."""
    from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415
    W, H, ss = 1200, 630, 2
    img = Image.new("RGB", (W * ss, H * ss), _rgb("#090c17"))
    d = ImageDraw.Draw(img)
    _draw_mark(d, 200, 200 * ss / BOX, 80 * ss, 74 * ss, _rgb(AMBER))

    def font(names: tuple[str, ...], size: int):
        for n in names:
            try:
                return ImageFont.truetype(n, size * ss)
            except OSError:
                continue
        return ImageFont.load_default(size * ss)

    mono = ("CascadiaMono.ttf", "consola.ttf", "DejaVuSansMono.ttf")
    serif = ("georgia.ttf", "DejaVuSerif.ttf")
    d.text((300 * ss, 92 * ss), "E P H E M E R A", font=font(mono, 46), fill=_rgb(AMBER))
    d.text((300 * ss, 156 * ss), "ephemera.space", font=font(mono, 22), fill=_rgb("#8f8da0"))
    y = 300
    for line in headline.split("\n"):
        d.text((80 * ss, y * ss), line, font=font(serif, 44), fill=_rgb(BONE))
        y += 62
    d.text((80 * ss, 520 * ss), sub, font=font(mono, 21), fill=_rgb("#8f8da0"))
    d.rectangle([0, (H - 8) * ss, W * ss, H * ss], fill=_rgb(AMBER))
    img.resize((W, H), Image.LANCZOS).save(path)


def write_all(out: Path, headline: str, sub: str) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    (out / "icon.svg").write_text(mark_svg(), encoding="utf-8")
    written.append(out / "icon.svg")
    for name, size in (("icon-180.png", 180), ("icon-512.png", 512)):
        write_icon_png(out / name, size)
        written.append(out / name)
    write_social_png(out / "social.png", headline, sub)
    written.append(out / "social.png")
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=REPO / "web" / "dist")
    ap.add_argument("--headline", default="An archive of the public Starlink ephemerides.")
    ap.add_argument("--sub", default="Kept, hashed, and anchored in Bitcoin.")
    args = ap.parse_args(argv)
    for p in write_all(args.out, args.headline, args.sub):
        print(f"{p} ({p.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
