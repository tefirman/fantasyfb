"""Regenerate docs / favicon image variants from the master logo.

The master lives at ``assets/fantasyfb_logo.png`` and is kept at its
full resolution so we have headroom for future variants. This script
produces the web-optimized copies that the docs site actually serves.

Run from the repo root:

    python scripts/build-assets.py

Outputs:
    docs/assets/fantasyfb_logo.png   web hero, ~600px wide, RGBA
    docs/assets/favicon.png          32x32, palette-quantized

Re-run after editing the master to refresh.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "assets" / "fantasyfb_logo.png"
OUT_DIR = ROOT / "docs" / "assets"

HERO_WIDTH = 600   # rendered at ~120-200px in the header; 600 covers 2x retina
FAVICON_SIZE = 32  # browsers serve the @2x at 64 via the same file just fine


def build_hero(master: Image.Image, dest: Path) -> None:
    w, h = master.size
    new_h = round(h * HERO_WIDTH / w)
    hero = master.resize((HERO_WIDTH, new_h), Image.LANCZOS)
    # Palette-quantize: the logo has a small color palette (navy,
    # gold, white, a few gradients) so 255 colors are plenty and
    # the file shrinks ~10x vs. full RGBA PNG.
    hero = hero.quantize(colors=255, method=Image.Quantize.FASTOCTREE)
    hero.save(dest, format="PNG", optimize=True)
    print(f"  {dest.relative_to(ROOT)}: {hero.size} -> {dest.stat().st_size:,} bytes")


def build_favicon(master: Image.Image, dest: Path) -> None:
    fav = master.resize((FAVICON_SIZE, FAVICON_SIZE), Image.LANCZOS)
    # Palette mode with an alpha-aware quantizer keeps the rounded
    # shield edge readable at 32px.
    fav = fav.quantize(colors=255, method=Image.Quantize.FASTOCTREE)
    fav.save(dest, format="PNG", optimize=True)
    print(f"  {dest.relative_to(ROOT)}: {fav.size} -> {dest.stat().st_size:,} bytes")


def main() -> None:
    if not MASTER.exists():
        raise SystemExit(f"Missing master logo: {MASTER}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Master: {MASTER.relative_to(ROOT)} "
          f"({MASTER.stat().st_size:,} bytes)")

    master = Image.open(MASTER).convert("RGBA")
    build_hero(master, OUT_DIR / "fantasyfb_logo.png")
    build_favicon(master, OUT_DIR / "favicon.png")


if __name__ == "__main__":
    main()
