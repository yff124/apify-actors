#!/usr/bin/env python3
"""Generate 512x512 Apify Store icons for the three Actors.

Apify Store shows the Actor logo as a square. Keep it readable at 40px in the
Store grid, so: one strong silhouette, one short label, high contrast.

Usage:
    python make_icons.py            # writes <slug>.png next to this file
"""
from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).resolve().parent
SIZE = 512
FONT_PATH = pathlib.Path(
    "/Users/yangfei/WorkBuddy/2026-09-28-11-17-15/02_流量/字库/SourceHanSansCN-Bold.otf"
)


def font(px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), px)


def rounded_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def linear_bg(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    """Vertical gradient, drawn one row at a time (512 rows is cheap and exact)."""
    img = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(img)
    for y in range(size):
        t = y / (size - 1)
        d.line(
            [(0, y), (size, y)],
            fill=(
                round(top[0] + (bottom[0] - top[0]) * t),
                round(top[1] + (bottom[1] - top[1]) * t),
                round(top[2] + (bottom[2] - top[2]) * t),
            ),
        )
    return img


def centered(d: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, y: int, fill):
    left, top, right, bottom = d.textbbox((0, 0), text, font=f)
    w = right - left
    d.text(((SIZE - w) / 2 - left, y - top), text, font=f, fill=fill)


def icon_jobboard() -> Image.Image:
    """ats-job-board — a shortlist of job rows, the top one ticked.

    The check + three rows are laid out as one group and centred on the canvas
    (group height 282 -> starts at y=115), otherwise the icon reads top-heavy
    and leaves dead space under it.
    """
    img = linear_bg(SIZE, (13, 27, 62), (23, 79, 166))
    d = ImageDraw.Draw(img)
    d.line([(216, 150), (246, 180), (300, 120)], fill=(86, 158, 255), width=18, joint="curve")
    for i, y in enumerate((209, 281, 353)):
        shade = 255 - i * 52
        d.rounded_rectangle([96, y, 416, y + 44], radius=22, fill=(shade, shade, shade))
    img.putalpha(rounded_mask(SIZE, 112))
    return img


def icon_remote() -> Image.Image:
    """remote-tech-jobs — a globe with a pin, i.e. job anywhere."""
    img = linear_bg(SIZE, (10, 46, 38), (16, 122, 96))
    d = ImageDraw.Draw(img)
    ring = (150, 240, 205)
    d.ellipse([104, 104, 408, 408], outline=ring, width=20)
    d.ellipse([196, 104, 316, 408], outline=ring, width=12)      # meridian
    d.line([(104, 256), (408, 256)], fill=ring, width=12)         # equator
    d.arc([104, 150, 408, 362], start=0, end=180, fill=ring, width=12)
    # pin sitting on the globe
    d.ellipse([304, 56, 424, 176], fill=(255, 214, 92))
    d.ellipse([342, 94, 386, 138], fill=(10, 46, 38))
    img.putalpha(rounded_mask(SIZE, 112))
    return img


def icon_radar() -> Image.Image:
    """tech-ai-radar — radar sweep with a blip."""
    img = linear_bg(SIZE, (46, 20, 8), (176, 84, 18))
    d = ImageDraw.Draw(img)
    amber = (255, 214, 122)
    for r in (78, 122, 166):
        d.ellipse([256 - r, 256 - r, 256 + r, 256 + r], outline=amber, width=10)
    d.line([(256, 256), (368, 150)], fill=amber, width=14)        # sweep arm
    d.ellipse([344, 188, 392, 236], fill=(255, 255, 255))         # blip
    d.ellipse([246, 246, 266, 266], fill=amber)                   # centre
    img.putalpha(rounded_mask(SIZE, 112))
    return img


ICONS = {
    "ats-job-board-aggregator": icon_jobboard,
    "remote-tech-jobs-aggregator": icon_remote,
    "tech-ai-trend-radar": icon_radar,
}


def main() -> None:
    for slug, fn in ICONS.items():
        out = HERE / f"{slug}.png"
        fn().save(out, "PNG", optimize=True)
        with Image.open(out) as im:
            print(f"  {out.name:36s} {im.size} {im.mode}")
    print(f"\n{len(ICONS)} icons written to {HERE}")


if __name__ == "__main__":
    main()
