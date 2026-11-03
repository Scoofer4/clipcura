"""The Monogram (an open C around a play button, ui/public/favicon.svg) drawn with Pillow.

Drawing it in code lets the notification-area icon carry the batch progress in the logo itself: the C fills
with the brand gradient from its top end as conversions finish, and a badge appears when an assistant waits
for approval. The same drawing produces the .ico for the executable and the installer.
"""
from __future__ import annotations

import io
import math
from itertools import pairwise
from pathlib import Path

from PIL import Image, ImageDraw

# Colours from ui/src/design-system/tokens.css (dark theme) and the brand gradient in favicon.svg.
BG = (0x12, 0x15, 0x1A)
INK = (0xE8, 0xEA, 0xED)
TRACK = (0x3A, 0x40, 0x48)
ATTENTION = (0xFF, 0x8A, 0x3D)   # --human: needs a person
_STOPS = ((0.0, (0xBF, 0x1B, 0x2C)), (0.55, (0xE5, 0x2C, 0x3F)), (1.0, (0xFE, 0x6C, 0x61)))

# Geometry in the 64-unit grid of favicon.svg: the C is a 270° arc open to the right.
_CENTER, _RADIUS, _STROKE = 32.0, 22.0, 7.0
_TOP_END, _BOTTOM_END = 315.0, 45.0     # Pillow angles: degrees clockwise from 3 o'clock
_SWEEP = 270.0
_SUPERSAMPLE = 4


def _gradient_color(t: float) -> tuple[int, int, int]:
    t = min(1.0, max(0.0, t))
    for (t0, c0), (t1, c1) in pairwise(_STOPS):
        if t <= t1:
            k = (t - t0) / (t1 - t0)
            return tuple(round(a + (b - a) * k) for a, b in zip(c0, c1, strict=True))
    return _STOPS[-1][1]


def _gradient(size: int, scale: float) -> Image.Image:
    """favicon.svg's gradient runs from (6, 58) to (58, 6); along that diagonal t depends on x - y only, so one
    strip of colours, shifted per row, fills the whole canvas quickly."""
    strip = bytearray()
    for k in range(-size, size):
        strip += bytes(_gradient_color((k / scale + 52) / 104))
    rows = bytearray()
    for y in range(size):
        rows += strip[(size - y) * 3:(2 * size - y) * 3]
    return Image.frombytes("RGB", (size, size), bytes(rows))


def _arc_mask(size: int, scale: float, start: float, end: float) -> Image.Image:
    """A round-capped arc from `start` to `end` (clockwise), as a mask."""
    mask = Image.new("L", (size, size), 0)
    if end <= start:
        return mask
    d = ImageDraw.Draw(mask)
    c, r, w = _CENTER * scale, _RADIUS * scale, _STROKE * scale
    d.arc((c - r - w / 2, c - r - w / 2, c + r + w / 2, c + r + w / 2), start, end, fill=255, width=round(w))
    for angle in (start, end):
        x, y = c + r * math.cos(math.radians(angle)), c + r * math.sin(math.radians(angle))
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=255)
    return mask


def draw(size: int, progress: float | None = None, attention: bool = False) -> Image.Image:
    """The Monogram at `size` px. `progress` 0..1 shows how much of the batch is done (None = idle, full C)."""
    big = size * _SUPERSAMPLE
    scale = big / 64
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, big - 1, big - 1), radius=round(14 * scale), fill=BG)

    gradient = _gradient(big, scale)
    if progress is None:
        img.paste(gradient, (0, 0), _arc_mask(big, scale, _BOTTOM_END, _TOP_END))
    else:
        done = _SWEEP * min(1.0, max(0.0, progress))
        img.paste(TRACK, (0, 0, big, big), _arc_mask(big, scale, _BOTTOM_END, _TOP_END))
        if done > 0:
            img.paste(gradient, (0, 0), _arc_mask(big, scale, _TOP_END - done, _TOP_END))

    triangle = [(28 * scale, 23.5 * scale), (41.5 * scale, 32 * scale), (28 * scale, 40.5 * scale)]
    d.polygon(triangle, fill=INK)
    d.line([*triangle, triangle[0]], fill=INK, width=round(2 * scale), joint="curve")

    if attention:
        x, y, r = 52 * scale, 12 * scale, 7 * scale
        ring = 2.5 * scale
        d.ellipse((x - r - ring, y - r - ring, x + r + ring, y + r + ring), fill=BG)
        d.ellipse((x - r, y - r, x + r, y + r), fill=ATTENTION)
    # Box filtering averages each 4x4 block: smooth edges, exact colours inside shapes.
    return img.resize((size, size), Image.Resampling.BOX)


def png(size: int, progress: float | None = None, attention: bool = False) -> bytes:
    buf = io.BytesIO()
    draw(size, progress, attention).save(buf, format="PNG")
    return buf.getvalue()


ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def write_ico(path: Path) -> Path:
    """Windows icon for the executable and installer, every size drawn separately (no blurry downscales)."""
    images = [draw(s) for s in ICO_SIZES]
    images[-1].save(path, format="ICO", sizes=[(s, s) for s in ICO_SIZES], append_images=images[:-1])
    return path
