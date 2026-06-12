#!/usr/bin/env python3
"""
compose_enclosure.py

Paste a dashboard screenshot onto the enclosure illustration's screen area,
recolored to match the illustration palette. Used to regenerate the README
hero image after layout changes:

    python scripts/dashboard.py --mock --png --out docs/images/dashboard.png
    python scripts/compose_enclosure.py

The previous composite works as the base because the paste fully covers the
screen region.
"""

import os

from PIL import Image, ImageDraw, ImageOps

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE = os.path.join(REPO_ROOT, "docs", "images", "enclosure.png")
SCREENSHOT = os.path.join(REPO_ROOT, "docs", "images", "dashboard.png")
OUT = BASE

# Screen interior in the illustration (1264x847); aspect matches 800x480
SCREEN_BOX = (246, 137, 1004, 590)
INK = (58, 54, 48)
PAPER = (237, 233, 220)
CORNER_RADIUS = 10


def main() -> None:
    base = Image.open(BASE).convert("RGB")
    shot = Image.open(SCREENSHOT).convert("L")

    tinted = ImageOps.colorize(shot, black=INK, white=PAPER)
    size = (SCREEN_BOX[2] - SCREEN_BOX[0], SCREEN_BOX[3] - SCREEN_BOX[1])
    tinted = tinted.resize(size, Image.LANCZOS)

    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size[0] - 1, size[1] - 1), radius=CORNER_RADIUS, fill=255
    )

    base.paste(tinted, SCREEN_BOX[:2], mask)
    base.save(OUT)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
