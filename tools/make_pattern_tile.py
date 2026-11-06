"""Derive the wall-paper tile used behind the Kirby Clicker window.

The source artwork is a 1080 px wide phone wallpaper of pastel Kirby stickers.
A small square crop cannot be tiled: the stickers are cut by the crop border,
so neighbouring tiles would butt sliced Kirby squares against each other.

The tile is therefore taken at the page's own width (1080 px), which is wider
than any size the clicker window is used at (min 440x250, default 560x437).
`drawTiledPixmap` still repeats it at its natural scale, but for every size the
window actually reaches the repeat sits outside the visible area, so there is
no seam in practice.

Usage:  py -3.13 tools\\make_pattern_tile.py <source.png> [--top 600]
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "assets" / "pattern.png"
SIZE = 1080


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    source = Path(sys.argv[1])
    top = 600
    if "--top" in sys.argv:
        top = int(sys.argv[sys.argv.index("--top") + 1])
    page = Image.open(source).convert("RGB")
    if page.width != SIZE:
        page = page.resize((SIZE, round(page.height * SIZE / page.width)))
    tile = page.crop((0, top, SIZE, top + SIZE))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tile.save(OUT, optimize=True)
    print(f"saved {OUT} ({tile.width}x{tile.height})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
