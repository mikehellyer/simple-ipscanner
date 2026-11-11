"""One-off script: draws the Simple-IPScanner app icon and exports every
size/format the platform installers need. Not part of the app itself and
not run automatically — re-run manually if the icon design ever changes.

Usage: venv/bin/python packaging/icons/generate_icon.py
"""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).parent
APP_RESOURCES = OUT_DIR.parent.parent / "src" / "simple_ipscanner" / "gui" / "resources"
SIZE = 1024

# A radar: rings spreading out from a centre point, a sweep, and a few
# devices it has found (one red — gone offline), on a blue tile.
TILE_TOP = (52, 120, 230, 255)
TILE_BOTTOM = (24, 62, 150, 255)
RING = (255, 255, 255, 90)
SWEEP = (255, 255, 255, 70)
WHITE = (255, 255, 255, 255)
GREEN = (80, 220, 140, 255)
RED = (255, 95, 80, 255)


def draw_icon() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE))
    d = ImageDraw.Draw(img)
    for y in range(SIZE):
        t = y / SIZE
        d.line([(0, y), (SIZE, y)], fill=tuple(int(TILE_TOP[i] + (TILE_BOTTOM[i] - TILE_TOP[i]) * t) for i in range(3)) + (255,))
    mask = Image.new("L", (SIZE, SIZE), 0)
    margin = SIZE * 0.06
    ImageDraw.Draw(mask).rounded_rectangle([margin, margin, SIZE - margin, SIZE - margin], radius=SIZE * 0.22, fill=255)

    k = SIZE * 2 / 100  # drawn at double size, then shrunk, for smooth edges
    layer = Image.new("RGBA", (SIZE * 2, SIZE * 2), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    cx, cy = 50 * k, 50 * k
    ld.pieslice([cx - 34 * k, cy - 34 * k, cx + 34 * k, cy + 34 * k], -90, -30, fill=SWEEP)
    for r in (12, 23, 34):
        ld.ellipse([cx - r * k, cy - r * k, cx + r * k, cy + r * k], outline=RING, width=int(2.2 * k))
    ld.line([cx, cy, cx + math.cos(math.radians(-30)) * 34 * k, cy + math.sin(math.radians(-30)) * 34 * k],
            fill=WHITE, width=int(2.6 * k))
    for x, y, r, colour in ((50, 50, 4.2, WHITE), (66, 34, 4.6, GREEN), (30, 62, 4.6, GREEN), (68, 66, 4.6, RED)):
        ld.ellipse([(x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k], fill=colour)
    layer = layer.resize((SIZE, SIZE), Image.LANCZOS)
    img.alpha_composite(layer)

    out = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def main() -> None:
    icon = draw_icon()
    master_png = OUT_DIR / "icon.png"
    icon.save(master_png)
    print(f"wrote {master_png}")

    APP_RESOURCES.mkdir(parents=True, exist_ok=True)
    icon.resize((256, 256), Image.LANCZOS).save(APP_RESOURCES / "icon.png")
    print(f"wrote {APP_RESOURCES / 'icon.png'}")

    # Windows .ico (multi-resolution)
    ico_sizes = [16, 24, 32, 48, 64, 128, 256]
    ico_path = OUT_DIR / "icon.ico"
    icon.save(ico_path, sizes=[(s, s) for s in ico_sizes])
    print(f"wrote {ico_path}")

    # Linux: a few common hicolor sizes as plain PNGs.
    for s in (16, 32, 48, 64, 128, 256, 512):
        icon.resize((s, s), Image.LANCZOS).save(OUT_DIR / f"icon_{s}.png")
    print("wrote icon_16..512.png")

    # macOS .icns: iconutil on a Mac; elsewhere Pillow's own ICNS writer is
    # good enough to commit, so CI on macOS always has a file to use.
    if sys.platform == "darwin" and shutil.which("iconutil"):
        iconset = OUT_DIR / "icon.iconset"
        iconset.mkdir(exist_ok=True)
        for s in (16, 32, 128, 256, 512):
            icon.resize((s, s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
            icon.resize((s * 2, s * 2), Image.LANCZOS).save(iconset / f"icon_{s}x{s}@2x.png")
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(OUT_DIR / "icon.icns")],
            check=True,
        )
        for f in iconset.iterdir():
            f.unlink()
        iconset.rmdir()
    else:
        icon.save(OUT_DIR / "icon.icns")
    print(f"wrote {OUT_DIR / 'icon.icns'}")


if __name__ == "__main__":
    main()
