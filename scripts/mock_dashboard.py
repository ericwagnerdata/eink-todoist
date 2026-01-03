#!/usr/bin/env python3
"""
Mock dashboard renderer for Waveshare 7.5" V2 (800x480, B/W).

Usage:
  source .venv/bin/activate
  python3 scripts/mock_dashboard.py --png /tmp/mock.png
  python3 scripts/mock_dashboard.py --display
"""

from __future__ import annotations

import argparse
import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont


# ---------- Layout constants ----------
W, H = 800, 480

MARGIN = 16
GAP = 12

# Inner width = 800 - 2*MARGIN = 768
# Minus 2 gaps between 3 columns => 768 - 24 = 744
# Make col1 and col2 equal, remaining goes to col3
COL1_W = 270
COL2_W = 270
COL3_W = 744 - COL1_W - COL2_W  # 204

OUTER_BORDER = 0  # unused now
DIVIDER = 3

PAD_X = 14
PAD_Y = 14

HEADER_H = 42
RULE = 2


# ---------- Fonts ----------
def load_font(path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


FONT_BOLD = load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
FONT_BODY = load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
FONT_SMALL = load_font("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
FONT_MONO = load_font("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 16)
FONT_MONO_BOLD = load_font("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 16)


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    def inset(self, dx: int, dy: int) -> "Rect":
        return Rect(self.x + dx, self.y + dy, self.w - 2 * dx, self.h - 2 * dy)


def text_size(draw: ImageDraw.ImageDraw, text: str, font) -> Tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def draw_header(draw: ImageDraw.ImageDraw, r: Rect, title: str) -> int:
    # returns y after header + rule
    draw.text((r.x, r.y), title, font=FONT_BOLD, fill=0)
    y = r.y + HEADER_H - 10
    draw.line((r.x, y, r.x2, y), fill=0, width=RULE)
    return y + 10


def clip_text(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> str:
    """Single-line clip with ellipsis."""
    if text_size(draw, text, font)[0] <= max_w:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi) // 2
        candidate = text[:mid].rstrip() + ell
        if text_size(draw, candidate, font)[0] <= max_w:
            lo = mid + 1
        else:
            hi = mid
    candidate = text[: max(0, lo - 1)].rstrip() + ell
    return candidate

def draw_inverse_tag(draw, x: int, y: int, text: str, font) -> Tuple[int, int]:
    """Draw black rectangle with white text. Returns (w,h)."""
    tw, th = text_size(draw, text, font)
    pad_x, pad_y = 6, 3
    w = tw + pad_x * 2
    h = th + pad_y * 2
    draw.rectangle((x, y, x + w, y + h), fill=0, outline=0)
    draw.text((x + pad_x, y + pad_y), text, font=font, fill=255)
    return w, h


# ---------- Mock data ----------
def mock_recurring():
    # (task, date_label, overdue)
    return [
        ("Water plants", "Jan 2", True),
        ("Take trash out", "Jan 5", False),
        ("Replace filter", "Jan 7", False),
        ("Pay Fidelity bill", "Jan 14", False),
    ]


def mock_upcoming():
    # (task, date_label, overdue)
    return [
        ("Ship Etsy orders", "Jan 2", True),
        ("Warranty email", "Jan 2", False),
        ("Filament order", "Jan 5", False),
        ("Fidelity bill", "Jan 7", False),
    ]



def mock_weather() -> Tuple[str, str]:
    # summary line, highs/lows line
    return ("42°F  Snow", "↑ 47°   ↓ 31°")


# ---------- Calendar drawing ----------
def month_grid(today: date) -> Tuple[str, List[List[Optional[int]]]]:
    cal = calendar.Calendar(firstweekday=6)  # Sunday
    weeks = cal.monthdayscalendar(today.year, today.month)
    # Convert 0s to None
    grid: List[List[Optional[int]]] = []
    for wk in weeks:
        grid.append([d if d != 0 else None for d in wk])
    title = today.strftime("%b %Y").upper()
    return title, grid


def draw_month(
    draw: ImageDraw.ImageDraw,
    r: Rect,
    today: date,
    days_with_tasks: Sequence[int],
) -> None:
    title, grid = month_grid(today)

    # Title
    draw.text((r.x, r.y), title, font=FONT_BOLD, fill=0)
    y = r.y + 28

    # Weekday header
    weekdays = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]
    cell_w = (r.w) // 7
    cell_h = 22

    for i, wd in enumerate(weekdays):
        x = r.x + i * cell_w
        draw.text((x + 2, y), wd, font=FONT_MONO_BOLD, fill=0)
    y += 22

    # Days
    for row in grid:
        for i, d in enumerate(row):
            x = r.x + i * cell_w
            if d is None:
                continue

            # Highlight today with an outline box
            if d == today.day:
                draw.rectangle((x + 1, y + 1, x + cell_w - 2, y + cell_h - 2), outline=0, width=2)

            # Day number
            s = f"{d:>2}"
            draw.text((x + 2, y + 2), s, font=FONT_MONO, fill=0)

            # Task marker: small filled dot in bottom-right
            if d in days_with_tasks:
                dot_x = x + cell_w - 8
                dot_y = y + cell_h - 7
                draw.ellipse((dot_x, dot_y, dot_x + 5, dot_y + 5), fill=0, outline=0)

        y += cell_h


# ---------- Render ----------
def render_mock(now: datetime) -> Image.Image:
    img = Image.new("1", (W, H), 255)
    draw = ImageDraw.Draw(img)

    # Column rects (no frame, no borders)
    top = MARGIN
    left = MARGIN
    height = H - 2 * MARGIN

    col1 = Rect(left, top, COL1_W, height)
    col2 = Rect(col1.x2 + GAP, top, COL2_W, height)
    col3 = Rect(col2.x2 + GAP, top, COL3_W, height)

    # Vertical dividers only
    div1_x = col1.x2 + GAP // 2
    div2_x = col2.x2 + GAP // 2
    draw.line((div1_x, top, div1_x, top + height), fill=0, width=DIVIDER)
    draw.line((div2_x, top, div2_x, top + height), fill=0, width=DIVIDER)

    # Inner content rects
    c1 = col1.inset(PAD_X, PAD_Y)
    c2 = col2.inset(PAD_X, PAD_Y)
    c3 = col3.inset(PAD_X, PAD_Y)

    # --- Column 1: Recurring ---
    y = draw_header(draw, c1, "RECURRING")

    for task, dlabel, overdue in mock_recurring():
        if y > c1.y2 - 28:
            break

        date_txt = f"({dlabel})"
        date_w, _ = text_size(draw, date_txt, FONT_SMALL)
        max_task_w = c1.w - date_w - 14
        left_txt = clip_text(draw, f"- {task}", FONT_BODY, max_task_w)

        draw.text((c1.x, y), left_txt, font=FONT_BODY, fill=0)

        dx = c1.x2 - date_w
        if overdue:
            draw_inverse_tag(draw, dx - 6, y + 2, date_txt, FONT_SMALL)
        else:
            draw.text((dx, y + 4), date_txt, font=FONT_SMALL, fill=0)

        y += 30

    # --- Column 2: Upcoming (single chronological list) ---
    y = draw_header(draw, c2, "TO DOs")

    for task, dlabel, overdue in mock_upcoming():
        if y > c2.y2 - 28:
            break

        date_txt = f"({dlabel})"
        date_w, _ = text_size(draw, date_txt, FONT_SMALL)
        max_task_w = c2.w - date_w - 14
        left_txt = clip_text(draw, f"- {task}", FONT_BODY, max_task_w)

        draw.text((c2.x, y), left_txt, font=FONT_BODY, fill=0)

        dx = c2.x2 - date_w
        if overdue:
            draw_inverse_tag(draw, dx - 6, y + 2, date_txt, FONT_SMALL)
        else:
            draw.text((dx, y + 4), date_txt, font=FONT_SMALL, fill=0)

        y += 30

    # --- Column 3: Info ---
    y = draw_header(draw, c3, "INFO")

    w1, w2 = mock_weather()
    draw.text((c3.x, y), w1, font=FONT_BODY, fill=0)
    y += 26
    draw.text((c3.x, y), w2, font=FONT_SMALL, fill=0)
    y += 26

    y += 6
    draw.line((c3.x, y, c3.x2, y), fill=0, width=RULE)
    y += 14

    today = now.date()
    days_with_tasks = sorted({today.day, min(today.day + 2, 28), min(today.day + 5, 28)})
    cal_rect = Rect(c3.x, y, c3.w, 160)
    draw_month(draw, cal_rect, today=today, days_with_tasks=days_with_tasks)

    y = cal_rect.y2 + 10
    draw.line((c3.x, y, c3.x2, y), fill=0, width=RULE)
    y += 14

    updated = now.strftime("%H:%M")
    nxt = (now + timedelta(minutes=18)).strftime("%H:%M")
    draw.text((c3.x, y), f"Updated: {updated}", font=FONT_SMALL, fill=0)
    y += 22
    draw.text((c3.x, y), f"Next:    {nxt}", font=FONT_SMALL, fill=0)

    return img



# ---------- Display ----------
def display_image(img: Image.Image) -> None:
    # Uses the Waveshare repo you already cloned.
    # If your path differs, update this.
    import sys
    sys.path.append("/home/eric/projects/e-Paper/RaspberryPi_JetsonNano/python/lib")

    from waveshare_epd import epd7in5_V2

    epd = epd7in5_V2.EPD()
    epd.init()
    epd.display(epd.getbuffer(img))
    epd.sleep()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", type=str, default=None, help="Save rendered mock to PNG path")
    ap.add_argument("--display", action="store_true", help="Send rendered mock to e-ink display")
    args = ap.parse_args()

    img = render_mock(datetime.now())

    if args.png:
        out = Path(args.png)
        out.parent.mkdir(parents=True, exist_ok=True)
        # Convert to 8-bit for easier viewing in viewers
        img.convert("L").save(out)
        print(f"Saved: {out}")

    if args.display:
        display_image(img)
        print("Displayed.")

    if not args.png and not args.display:
        # default: save to /tmp for quick preview
        out = Path("/tmp/eink_mock.png")
        img.convert("L").save(out)
        print(f"No output option provided. Saved: {out}")


if __name__ == "__main__":
    main()
