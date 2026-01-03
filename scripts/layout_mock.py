#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from PIL import Image, ImageDraw, ImageFont

import calendar
from datetime import datetime

import sys
import argparse


# ---------- Config ----------
# If you already have display working, you can set these to your panel size.
# Waveshare 7.5" v2 is typically 800x480 (landscape).
W, H = 800, 480

PADDING = 18
GAP = 14  # space between columns content and divider
DIVIDER_W = 3

HEADER_H = 40
ROW_H = 34
DATE_PILL_PAD_X = 10
DATE_PILL_PAD_Y = 5
DATE_RADIUS = 8

# Column widths: Recurring = Upcoming, Info narrower.
# Total = W - 2*PADDING - 2*DIVIDER_W - 2*GAP*2 (content/divider breathing)
# We'll compute based on ratios.
REC_RATIO = 1.0
UP_RATIO = 1.0
INFO_RATIO = 0.78

# ---------- Data ----------
@dataclass
class TaskRow:
    title: str
    due: date
    overdue: bool = False

def fmt_due(d: date) -> str:
    # "Jan 2"
    return d.strftime("%b ").replace(" 0", " ") + str(d.day)

# ---------- Fonts ----------
def load_font(paths, size):
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()

FONT_REG = load_font(
    [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ],
    20,
)
FONT_BOLD = load_font(
    [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ],
    22,
)
FONT_SMALL = load_font(
    ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"], 16
)

# ---------- Layout helpers ----------
def col_widths(total_w: int):
    ratio_sum = REC_RATIO + UP_RATIO + INFO_RATIO
    rec_w = int(total_w * (REC_RATIO / ratio_sum))
    up_w = int(total_w * (UP_RATIO / ratio_sum))
    info_w = total_w - rec_w - up_w
    return rec_w, up_w, info_w

def draw_v_divider(draw: ImageDraw.ImageDraw, x: int, y0: int, y1: int):
    draw.rectangle([x, y0, x + DIVIDER_W - 1, y1], fill=0)

def draw_header(draw, x0, y0, x1, text):
    draw.text((x0, y0), text, font=FONT_BOLD, fill=0)
    # subtle underline (optional): comment out if you want even calmer
    underline_y = y0 + 30
    draw.line([x0, underline_y, x1, underline_y], fill=0, width=2)

def draw_task_row(draw, x0, y, x1, row: TaskRow):
    # Right side: due date (pill if overdue)
    due_text = fmt_due(row.due)

    # Measure text
    due_bbox = draw.textbbox((0, 0), due_text, font=FONT_REG)
    due_w = due_bbox[2] - due_bbox[0]
    due_h = due_bbox[3] - due_bbox[1]

    # Pill box
    pill_w = due_w + 2 * DATE_PILL_PAD_X
    pill_h = due_h + 2 * DATE_PILL_PAD_Y

    pill_x1 = x1
    pill_x0 = pill_x1 - pill_w
    pill_y0 = y + (ROW_H - pill_h) // 2
    pill_y1 = pill_y0 + pill_h

    # Title area ends before pill with a gap
    title_x0 = x0
    title_x1 = pill_x0 - 12

    # Truncate title to fit
    title = row.title
    while title and draw.textlength(title, font=FONT_REG) > (title_x1 - title_x0):
        title = title[:-1]
    if title != row.title:
        title = title[:-3] + "..." if len(title) > 3 else "..."

    draw.text((title_x0, y + 6), title, font=FONT_REG, fill=0)

    if row.overdue:
        # Dark pill with white text
        draw.rounded_rectangle([pill_x0, pill_y0, pill_x1, pill_y1], radius=DATE_RADIUS, fill=0)
        draw.text((pill_x0 + DATE_PILL_PAD_X, pill_y0 + DATE_PILL_PAD_Y), due_text, font=FONT_REG, fill=255)
    else:
        # Just normal text (no pill)
        draw.text((pill_x0 + DATE_PILL_PAD_X, pill_y0 + DATE_PILL_PAD_Y), due_text, font=FONT_REG, fill=0)

def draw_month_calendar(draw, x0, y0, col_w, year, month, today_d: date, marked_days: set[int]):
    cal = calendar.Calendar(firstweekday=6)  # Sunday first
    month_name = date(year, month, 1).strftime("%b %Y").upper()

    # Title
    draw.text((x0, y0), month_name, font=FONT_BOLD, fill=0)
    y = y0 + 30

    # Weekday header
    dow = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]
    cell_w = col_w // 7
    for i, d in enumerate(dow):
        draw.text((x0 + i * cell_w, y), d, font=FONT_SMALL, fill=0)
    y += 22

    # Weeks
    weeks = cal.monthdayscalendar(year, month)  # 0 means "not in this month"
    for week in weeks:
        for i, daynum in enumerate(week):
            if daynum == 0:
                continue
            cx = x0 + i * cell_w
            cy = y

            # Highlight today (inverse)
            is_today = (today_d.year == year and today_d.month == month and today_d.day == daynum)
            txt = str(daynum)

            if is_today:
                # simple inverse highlight box
                box = [cx - 2, cy - 2, cx + cell_w - 6, cy + 18]
                draw.rectangle(box, fill=0)
                draw.text((cx, cy), txt, font=FONT_SMALL, fill=255)
            else:
                draw.text((cx, cy), txt, font=FONT_SMALL, fill=0)

        y += 22

    return y


def fmt_updated(dt: datetime) -> str:
    # Example: "Jan 2, 2026  9:42 AM"
    mon = dt.strftime("%b")
    day = dt.day
    year = dt.year
    time_str = dt.strftime("%I:%M %p").lstrip("0")
    return f"{mon} {day}, {year}  {time_str}"


def render_mock(recurring: list[TaskRow], upcoming: list[TaskRow]):
    img = Image.new("1", (W, H), 1)  # 1-bit, white background
    draw = ImageDraw.Draw(img)

    inner_w = W - 2 * PADDING
    rec_w, up_w, info_w = col_widths(inner_w - 2 * DIVIDER_W - 2 * GAP * 2)

    # Column x positions
    x = PADDING
    rec_x0, rec_x1 = x, x + rec_w
    x = rec_x1 + GAP
    div1_x = x
    x = div1_x + DIVIDER_W + GAP
    up_x0, up_x1 = x, x + up_w
    x = up_x1 + GAP
    div2_x = x
    x = div2_x + DIVIDER_W + GAP
    info_x0, info_x1 = x, x + info_w

    y0 = PADDING
    y1 = H - PADDING

    # Dividers only
    draw_v_divider(draw, div1_x, y0, y1)
    draw_v_divider(draw, div2_x, y0, y1)

    # Headers
    draw_header(draw, rec_x0, y0, rec_x1, "RECURRING")
    draw_header(draw, up_x0, y0, up_x1, "TODOs")
    draw_header(draw, info_x0, y0, info_x1, "INFO")

    # Rows start after header
    cur_y_rec = y0 + HEADER_H
    for r in recurring:
        if cur_y_rec + ROW_H > y1:
            break
        draw_task_row(draw, rec_x0, cur_y_rec, rec_x1, r)
        cur_y_rec += ROW_H

    cur_y_up = y0 + HEADER_H
    for r in upcoming:
        if cur_y_up + ROW_H > y1:
            break
        draw_task_row(draw, up_x0, cur_y_up, up_x1, r)
        cur_y_up += ROW_H

    # Info mock
    iy = y0 + HEADER_H
    draw.text((info_x0, iy), "42°F  Snow", font=FONT_REG, fill=0); iy += 34
    draw.text((info_x0, iy), "↑ 47°   ↓ 31°", font=FONT_REG, fill=0); iy += 18
    iy += 18

    # Build "marked days" from task due dates in current month (mock behavior but useful)
    today_d = date.today()
    marked = set()
    for t in (recurring + upcoming):
        if t.due.year == today_d.year and t.due.month == today_d.month:
            marked.add(t.due.day)

    # Full month calendar
    iy = draw_month_calendar(draw, info_x0, iy, info_x1 - info_x0, today_d.year, today_d.month, today_d, marked)
    iy += 16

    # Status timestamps (with date + AM/PM)
    now = datetime.now()
    updated = fmt_updated(now)
    next_dt = now.replace(minute=(now.minute // 15 + 1) * 15 % 60)  # simple “next quarter hour” mock
    if next_dt <= now:
        next_dt = now  # fallback
    next_s = fmt_updated(next_dt)

    draw.text((info_x0, iy), f"Updated:", font=FONT_SMALL, fill=0)
    iy += 18
    draw.text((info_x0, iy), updated, font=FONT_SMALL, fill=0)

    iy += 26  # visual breathing room

    draw.text((info_x0, iy), f"Next:", font=FONT_SMALL, fill=0)
    iy += 18
    draw.text((info_x0, iy), next_s, font=FONT_SMALL, fill=0)



    return img

def display_on_epd(img: Image.Image):
    # Point to your Waveshare Python lib (adjust if your path differs)
    sys.path.append("/home/eric/projects/e-Paper/RaspberryPi_JetsonNano/python/lib")
    from waveshare_epd import epd7in5_V2

    epd = epd7in5_V2.EPD()
    epd.init()
    epd.display(epd.getbuffer(img))
    epd.sleep()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--display", action="store_true", help="Render to Waveshare e-ink display")
    ap.add_argument("--png", type=str, default="layout_mock.png", help="Output PNG filename")
    args = ap.parse_args()

    today = date.today()

    recurring = [
        TaskRow("Take out trash", today - timedelta(days=1), overdue=True),
        TaskRow("Water plants", today + timedelta(days=2)),
        TaskRow("Replace filter", today + timedelta(days=7)),
        TaskRow("Pay credit card", today + timedelta(days=12)),
    ]

    upcoming = [
        TaskRow("Ship Etsy orders", today),
        TaskRow("Warranty email", today + timedelta(days=1)),
        TaskRow("Filament order", today + timedelta(days=3)),
        TaskRow("Fidelity bill", today + timedelta(days=5)),
    ]

    img = render_mock(recurring, upcoming)

    # Save PNG (nice for iteration)
    img.save(args.png)
    print(f"Wrote {args.png}")

    # Display if requested
    if args.display:
        display_on_epd(img)
        print("Displayed on e-ink.")


if __name__ == "__main__":
    main()
