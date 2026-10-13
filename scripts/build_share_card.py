#!/usr/bin/env python3
"""Render frontend/share-card.png, the image behind the Open Graph and
Twitter tags in index.html and how-it-works.html.

Run from the repository root after changing the copy constants below:

    pip install pillow fonttools brotli
    python scripts/build_share_card.py

Pillow renders the card. fontTools and brotli unpack the site's own woff2
faces (frontend/fonts) into TrueType files Pillow can read, in a temporary
directory. None of the three is a runtime dependency of the app; the PNG is
committed and served as a static file.

The layout mirrors the hero: the city photograph under the navy wash of
styles.css `.hero-wash`, Manrope at weight 200 for the name, Inter for the
rest, white type, 80px side and 72px top/bottom padding (the same frame the
OfferBirds social card uses). Link unfurlers want 1200x630; LinkedIn,
Slack, iMessage and X all read this size.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
OUTPUT = FRONTEND / "share-card.png"
CITY_PHOTO = FRONTEND / "city-window.webp"
FONT_DISPLAY_WOFF2 = FRONTEND / "fonts" / "manrope-200-800-latin.woff2"
FONT_BODY_WOFF2 = FRONTEND / "fonts" / "inter-100-900-latin.woff2"

WIDTH, HEIGHT = 1200, 630
PAD_X, PAD_Y = 80, 72
CONTENT_WIDTH = WIDTH - 2 * PAD_X

# styles.css tokens: --ink and the hero wash stops.
NAVY = (11, 19, 40)
WASH_STOPS = ((0.0, 0.74), (0.55, 0.40), (1.0, 0.22))
WHITE = (255, 255, 255)

# Copy. The kicker and tagline match the hero in index.html.
KICKER = "AI Strategy, Senior Product Manager @ Morgan Stanley"
NAME_LINES = ("Dakota", "Radigan")
TAGLINE = (
    "I turn emerging AI capabilities into products, workflows, "
    "and systems people actually use."
)
FOOTER = (
    "dakotaradigan.io  ·  Chat with the resume  ·  Compare a role  ·  "
    "Connect your agent over MCP"
)


def unpack_font(woff2: Path, out_dir: Path) -> Path:
    """Write the TrueType form of a woff2 face; Pillow cannot open woff2."""
    font = TTFont(str(woff2))
    font.flavor = None
    out = out_dir / (woff2.stem + ".ttf")
    font.save(str(out))
    return out


def font_at(path: Path, size: int, weight: int) -> ImageFont.FreeTypeFont:
    """A variable font at ``size`` with its weight axis set. Inter also has an
    optical-size axis, which follows the point size."""
    font = ImageFont.truetype(str(path), size)
    values = []
    for axis in font.get_variation_axes():
        name = axis["name"]
        name = name.decode("latin-1") if isinstance(name, bytes) else str(name)
        wanted = weight if name.lower() == "weight" else size
        values.append(max(axis["minimum"], min(axis["maximum"], wanted)))
    if values:
        font.set_variation_by_axes(values)
    return font


def draw_tracked(
    draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
    font: ImageFont.FreeTypeFont, fill: tuple[int, ...], tracking: float,
) -> None:
    """Draw ``text`` glyph by glyph with ``tracking`` pixels added between
    glyphs (negative tightens, like CSS letter-spacing)."""
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += draw.textlength(char, font=font) + tracking


def wrap(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int,
) -> list[str]:
    """Greedy word wrap."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def cover(photo: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale to fill ``size`` and crop the centre, like background-size: cover."""
    width, height = size
    scale = max(width / photo.width, height / photo.height)
    scaled = photo.resize(
        (round(photo.width * scale), round(photo.height * scale)), Image.LANCZOS
    )
    left = (scaled.width - width) // 2
    top = (scaled.height - height) // 2
    return scaled.crop((left, top, left + width, top + height))


def wash(size: tuple[int, int]) -> Image.Image:
    """The hero's left-to-right navy gradient as an RGBA layer."""
    width, height = size
    alphas = bytearray()
    for x in range(width):
        position = x / (width - 1)
        for (p0, a0), (p1, a1) in zip(WASH_STOPS, WASH_STOPS[1:]):
            if position <= p1:
                t = (position - p0) / (p1 - p0)
                alpha = a0 + (a1 - a0) * t
                break
        alphas.append(round(alpha * 255))
    mask = Image.frombytes("L", (width, 1), bytes(alphas)).resize((width, height))
    layer = Image.new("RGBA", size, NAVY + (255,))
    layer.putalpha(mask)
    return layer


def star(size: int) -> Image.Image:
    """The favicon's four-point star, from the same cubic curves as its SVG
    path, drawn at 4x and downsampled for smooth edges."""
    scale = 4 * size / 32
    # (start, control 1, control 2, end) per curve, in the SVG's 32px box.
    curves = (
        ((16, 6), (16.8, 12), (20, 15.2), (26, 16)),
        ((26, 16), (20, 16.8), (16.8, 20), (16, 26)),
        ((16, 26), (15.2, 20), (12, 16.8), (6, 16)),
        ((6, 16), (12, 15.2), (15.2, 12), (16, 6)),
    )
    points = []
    for p0, p1, p2, p3 in curves:
        for step in range(24):
            t = step / 24
            u = 1 - t
            x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
            y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
            points.append((x * scale, y * scale))
    big = Image.new("RGBA", (4 * size, 4 * size), (0, 0, 0, 0))
    ImageDraw.Draw(big).polygon(points, fill=WHITE + (255,))
    return big.resize((size, size), Image.LANCZOS)


def build_card(display_ttf: Path, body_ttf: Path) -> Image.Image:
    card = cover(Image.open(CITY_PHOTO).convert("RGB"), (WIDTH, HEIGHT)).convert("RGBA")
    card = Image.alpha_composite(card, wash((WIDTH, HEIGHT)))
    draw = ImageDraw.Draw(card)

    # Kicker: small caps-style label, tracked out, like the hero's.
    kicker_font = font_at(body_ttf, 22, 500)
    y = PAD_Y
    draw_tracked(draw, (PAD_X, y), KICKER.upper(), kicker_font, WHITE + (209,), 2.6)
    y += 22 + 26

    # Name: Manrope 200, -0.05em tracking, 0.94 line height, two lines like the hero.
    name_size = 136
    name_font = font_at(display_ttf, name_size, 200)
    ascent, _ = name_font.getmetrics()
    for line in NAME_LINES:
        draw_tracked(draw, (PAD_X - 6, y), line, name_font, WHITE + (255,), -0.05 * name_size)
        y += round(name_size * 0.94)
    y += 48

    # Tagline: Inter 400, wrapped to the hero's measure.
    tagline_font = font_at(body_ttf, 30, 400)
    for line in wrap(draw, TAGLINE, tagline_font, 760):
        draw.text((PAD_X, y), line, font=tagline_font, fill=WHITE + (235,))
        y += 44

    # Footer: the star mark and the address line, on the bottom padding line.
    footer_font = font_at(body_ttf, 22, 500)
    mark = star(26)
    footer_y = HEIGHT - PAD_Y - 26
    card.alpha_composite(mark, (PAD_X, footer_y))
    draw.text((PAD_X + 26 + 16, footer_y + 1), FOOTER, font=footer_font, fill=WHITE + (199,))
    return card.convert("RGB")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        display_ttf = unpack_font(FONT_DISPLAY_WOFF2, tmp_dir)
        body_ttf = unpack_font(FONT_BODY_WOFF2, tmp_dir)
        card = build_card(display_ttf, body_ttf)
    card.save(OUTPUT, format="PNG", optimize=True)
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
