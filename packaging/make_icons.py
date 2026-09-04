#!/usr/bin/env python3
"""Generate the CostSight app icons from code.

Producing the icons programmatically keeps them reproducible in CI and avoids
committing binary art nobody can edit. Run it whenever the mark changes:

    python packaging/make_icons.py

Outputs, all under packaging/icons/:
    icon.png    1024x1024 master
    icon.icns   macOS bundle icon  (built with iconutil; macOS only)
    icon.ico    Windows bundle icon (multi-resolution, built with Pillow)

The mark is a magnifier ringing three ascending cost bars, with the tallest
bar in amber — the expensive one you opened the tool to find. Everything is
drawn at 4x and downsampled, since Pillow has no anti-aliased primitives.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    sys.exit("Pillow is required: pip install Pillow")

OUT_DIR = Path(__file__).resolve().parent / "icons"

BG_TOP = (18, 32, 54)       # deep navy
BG_BOTTOM = (11, 20, 36)
RING = (241, 245, 249)      # near-white
BAR_COOL = (56, 189, 248)   # sky
BAR_HOT = (251, 191, 36)    # amber — the expensive bar

SS = 4  # supersample factor


def _vertical_gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    grad = Image.new("RGB", (1, size))
    px = grad.load()
    for y in range(size):
        t = y / max(size - 1, 1)
        px[0, y] = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return grad.resize((size, size), Image.NEAREST)


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def render(size: int = 1024) -> Image.Image:
    """Draw the mark at ``size`` px square, RGBA."""
    s = size * SS

    base = _vertical_gradient(s, BG_TOP, BG_BOTTOM).convert("RGBA")
    base.putalpha(_rounded_mask(s, radius=int(s * 0.225)))

    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    cx, cy = s * 0.455, s * 0.435
    ring_r = s * 0.295
    stroke = s * 0.052

    # Bars, ascending, sitting on a common baseline inside the ring.
    bar_w = s * 0.072
    gap = s * 0.046
    baseline = cy + ring_r * 0.50
    heights = (s * 0.145, s * 0.225, s * 0.315)
    colors = (BAR_COOL, BAR_COOL, BAR_HOT)
    total_w = 3 * bar_w + 2 * gap
    x = cx - total_w / 2
    for h, color in zip(heights, colors, strict=True):
        d.rounded_rectangle(
            (x, baseline - h, x + bar_w, baseline),
            radius=bar_w * 0.34,
            fill=(*color, 255),
        )
        x += bar_w + gap

    # Magnifier handle, drawn before the ring so the ring caps it cleanly.
    ang = 0.7071  # cos/sin of 45 degrees
    hx0, hy0 = cx + ring_r * ang, cy + ring_r * ang
    hx1, hy1 = cx + ring_r * ang * 1.92, cy + ring_r * ang * 1.92
    d.line((hx0, hy0, hx1, hy1), fill=(*RING, 255), width=int(s * 0.076))
    # Round the handle's far end.
    hr = s * 0.038
    d.ellipse((hx1 - hr, hy1 - hr, hx1 + hr, hy1 + hr), fill=(*RING, 255))

    d.ellipse(
        (cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r),
        outline=(*RING, 255),
        width=int(stroke),
    )

    out = Image.alpha_composite(base, layer)
    return out.resize((size, size), Image.LANCZOS)


def write_icns(master: Path, dest: Path) -> bool:
    """Build a .icns via macOS iconutil. Returns False off macOS."""
    if not shutil.which("iconutil"):
        return False
    src = Image.open(master)
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for px in (16, 32, 64, 128, 256, 512, 1024):
            src.resize((px, px), Image.LANCZOS).save(iconset / f"icon_{px}x{px}.png")
            # Retina variants are the 2x image named at the 1x size.
            if px >= 32:
                half = px // 2
                src.resize((px, px), Image.LANCZOS).save(iconset / f"icon_{half}x{half}@2x.png")
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(dest)],
            check=True,
        )
    return True


def write_ico(master: Path, dest: Path) -> None:
    """Multi-resolution .ico. Pillow writes these on every platform."""
    src = Image.open(master)
    sizes = [(px, px) for px in (16, 24, 32, 48, 64, 128, 256)]
    src.save(dest, format="ICO", sizes=sizes)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    master = OUT_DIR / "icon.png"
    render(1024).save(master)
    print(f"wrote {master.relative_to(Path.cwd())}")

    ico = OUT_DIR / "icon.ico"
    write_ico(master, ico)
    print(f"wrote {ico.relative_to(Path.cwd())}")

    icns = OUT_DIR / "icon.icns"
    if write_icns(master, icns):
        print(f"wrote {icns.relative_to(Path.cwd())}")
    else:
        print("skipped icon.icns (iconutil is macOS-only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
