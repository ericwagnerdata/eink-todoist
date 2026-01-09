#!/usr/bin/env python3
"""
dashboard.py

Single entrypoint for the E-Ink Todoist Desk Dashboard.

Modes:
- --mock       : use mock data (no Todoist required)
- --png        : write a PNG preview (fast iteration)
- --display    : push to Waveshare 7.5" V2 e-paper (SPI)
- --both       : do both PNG + display
- --out PATH   : output PNG path (default: out/dashboard.png)

Todoist config (recommended, stable):
- Set RECURRING_PROJECT_ID in .env to avoid name lookup issues.
  Example: RECURRING_PROJECT_ID=1234567890123456

Optional fallback:
- --recurring-project-id can override env

Design (v1):
| RECURRING | TO-DOS | INFO |
- no outer border; only vertical dividers
- dates right-aligned
- overdue dates use inverted pill
- no bullets/checkboxes/times
- calm month calendar: no dots; today highlighted
- Updated/Next show full date + 12h time AM/PM
"""

from __future__ import annotations

import argparse
import calendar
import os
import sys
from dataclasses import dataclass
from datetime import datetime, date
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv


# ----------------------------
# Layout (v1)
# ----------------------------
W, H = 800, 480

PAD_X = 28
PAD_Y = 20

COL_W = 280  # Recurring + Todos equal width
COL1_X0 = PAD_X
COL1_X1 = COL1_X0 + COL_W

COL2_X0 = COL1_X1
COL2_X1 = COL2_X0 + COL_W

COL3_X0 = COL2_X1
COL3_X1 = W - PAD_X

DIVIDER_W = 3

DATE_PAD_RIGHT = 16
COL1_DATE_X = COL1_X1 - DATE_PAD_RIGHT
COL2_DATE_X = COL2_X1 - DATE_PAD_RIGHT

HEADER_Y = PAD_Y
HEADER_H = 34
HEADER_LINE_Y_OFFSET = 28

LIST_START_Y = HEADER_Y + HEADER_H + 8
ROW_H = 30

INFO_PAD_LEFT = 14
BODY_LINE_HEIGHT = 28


# ----------------------------
# Fonts
# ----------------------------
def _load_font(preferred: List[str], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for p in preferred:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


FONT_HEADER = _load_font(
    [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ],
    22,
)
FONT_BODY = _load_font(
    [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
    20,
)
FONT_DATE = _load_font(
    [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
    18,
)
FONT_SMALL = _load_font(
    [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
    14,
)
FONT_SMALL_BOLD = _load_font(
    [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ],
    14,
)
FONT_MONO = _load_font(
    [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ],
    14,
)


# ----------------------------
# Data model
# ----------------------------
@dataclass(frozen=True)
class Row:
    title: str
    due: Optional[date]
    overdue: bool


# ----------------------------
# Generic helpers (SDK-safe)
# ----------------------------
def _get(obj, key: str, default=None):
    """Support both dict-style and object-style SDK outputs."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _flatten_results(results) -> list:
    """
    Normalize Todoist SDK results to a flat list.
    Some SDK/paginator versions yield pages (lists/tuples of items).
    """
    flat: list = []
    for item in list(results):
        if item is None:
            continue
        if isinstance(item, (list, tuple)):
            for sub in item:
                if sub is not None:
                    flat.append(sub)
        else:
            flat.append(item)
    return flat



# ----------------------------
# Formatting / drawing
# ----------------------------
def fmt_due(d: date) -> str:
    return d.strftime("%b") + " " + str(d.day)


def fmt_ts(dt: datetime) -> str:
    mon = dt.strftime("%b")
    return f"{mon} {dt.day}, {dt.year} {dt.strftime('%I:%M %p').lstrip('0')}"


def parse_due_to_date(due_str: str) -> Optional[date]:
    if not due_str:
        return None
    try:
        if len(due_str) == 10 and due_str[4] == "-" and due_str[7] == "-":
            return date.fromisoformat(due_str)
        s = due_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.date()
    except Exception:
        return None


def text_w(draw: ImageDraw.ImageDraw, s: str, font: ImageFont.ImageFont) -> int:
    bbox = draw.textbbox((0, 0), s, font=font)
    return int(bbox[2] - bbox[0])


def ellipsize_to_width(draw: ImageDraw.ImageDraw, s: str, font: ImageFont.ImageFont, max_w: int) -> str:
    if text_w(draw, s, font) <= max_w:
        return s
    if text_w(draw, "…", font) >= max_w:
        return "…"

    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi) // 2
        cand = s[:mid] + "…"
        if text_w(draw, cand, font) <= max_w:
            lo = mid + 1
        else:
            hi = mid
    cut = max(0, lo - 1)
    return s[:cut] + "…"


def draw_header(draw: ImageDraw.ImageDraw, x0: int, x1: int, label: str) -> None:
    draw.text((x0, HEADER_Y), label.upper(), font=FONT_HEADER, fill=0)
    underline_end = min(x0 + 190, x1 - 10)
    draw.line(
        (x0, HEADER_Y + HEADER_LINE_Y_OFFSET, underline_end, HEADER_Y + HEADER_LINE_Y_OFFSET),
        fill=0,
        width=2,
    )


def draw_dividers(draw: ImageDraw.ImageDraw) -> None:
    y0 = PAD_Y
    y1 = H - PAD_Y
    draw.line((COL2_X0, y0, COL2_X0, y1), fill=0, width=DIVIDER_W)
    draw.line((COL3_X0, y0, COL3_X0, y1), fill=0, width=DIVIDER_W)


def draw_overdue_pill(draw: ImageDraw.ImageDraw, right_x: int, y: int, label: str) -> None:
    pad_x = 7
    pad_y = 3
    w = text_w(draw, label, FONT_DATE)
    bbox = draw.textbbox((0, 0), label, font=FONT_DATE)
    h = int(bbox[3] - bbox[1])

    x0 = right_x - (w + pad_x * 2)
    y0 = y - pad_y
    x1 = right_x
    y1 = y + h + pad_y

    draw.rounded_rectangle((x0, y0, x1, y1), radius=6, fill=0)
    draw.text((x0 + pad_x, y), label, font=FONT_DATE, fill=255)


def draw_right_aligned_date(draw: ImageDraw.ImageDraw, right_x: int, y: int, label: str) -> None:
    w = text_w(draw, label, FONT_DATE)
    draw.text((right_x - w, y), label, font=FONT_DATE, fill=0)


def draw_task_row(draw: ImageDraw.ImageDraw, x_text: int, x_date_right: int, y: int, row: Row) -> None:
    if not row.due:
        return
    due_label = fmt_due(row.due)

    max_title_w = max(10, (x_date_right - 12) - x_text)
    title = ellipsize_to_width(draw, row.title, FONT_BODY, max_title_w)

    draw.text((x_text, y), title, font=FONT_BODY, fill=0)
    if row.overdue:
        draw_overdue_pill(draw, x_date_right, y + 1, due_label)
    else:
        draw_right_aligned_date(draw, x_date_right, y + 3, due_label)


def draw_month_calendar(draw: ImageDraw.ImageDraw, x: int, y: int, year: int, month: int, today_d: date) -> int:
    title = f"{calendar.month_name[month]} {year}".upper()
    draw.text((x, y), title, font=FONT_SMALL_BOLD, fill=0)
    y += 22

    draw.text((x, y), "Su Mo Tu We Th Fr Sa", font=FONT_MONO, fill=0)
    y += 18

    cal = calendar.Calendar(firstweekday=6)  # Sunday
    weeks = cal.monthdayscalendar(year, month)

    cell_w = text_w(draw, "00 ", FONT_MONO)
    cell_h = 18

    for week in weeks:
        for i, day_num in enumerate(week):
            if day_num == 0:
                continue
            cx = x + i * cell_w
            label = f"{day_num:>2}"

            is_today = (today_d.year == year and today_d.month == month and today_d.day == day_num)
            if is_today:
                box_w = text_w(draw, label, FONT_MONO) + 6
                draw.rounded_rectangle((cx - 2, y - 1, cx - 2 + box_w, y + cell_h - 3), radius=3, fill=0)
                draw.text((cx + 1, y), label, font=FONT_MONO, fill=255)
            else:
                draw.text((cx + 1, y), label, font=FONT_MONO, fill=0)

        y += cell_h

    return y


# ----------------------------
# Data sources: Mock + Todoist
# ----------------------------
def get_mock_rows() -> Tuple[List[Row], List[Row]]:
    t = date.today()
    recurring = [
        Row("Take out trash", t.replace(day=max(1, min(28, t.day - 1))), overdue=True),
        Row("Water plants", t.replace(day=min(28, t.day + 2)), overdue=False),
        Row("Replace filter", t.replace(day=min(28, t.day + 7)), overdue=False),
        Row("Pay credit card", t.replace(day=min(28, t.day + 12)), overdue=False),
    ]
    todos = [
        Row("Ship Etsy orders", t.replace(day=min(28, t.day + 1)), overdue=False),
        Row("Warranty email", t.replace(day=min(28, t.day + 2)), overdue=False),
        Row("Filament order", t.replace(day=min(28, t.day + 4)), overdue=False),
        Row("Fidelity bill", t.replace(day=min(28, t.day + 6)), overdue=False),
    ]
    return recurring, todos


def fetch_todoist_rows(recurring_project_id: str) -> Tuple[List[Row], List[Row]]:
    # Load token from repo .env (explicit path avoids python-dotenv frame issues)
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    load_dotenv(dotenv_path=os.path.join(repo_root, ".env"), override=True)

    token = os.getenv("TODOIST_API_TOKEN")
    if not token:
        raise RuntimeError("TODOIST_API_TOKEN not set. Put it in .env at repo root or export it.")

    if not recurring_project_id:
        raise RuntimeError(
            "Recurring project ID not set. Set RECURRING_PROJECT_ID in .env or pass --recurring-project-id."
        )

    from todoist_api_python.api import TodoistAPI

    api = TodoistAPI(token)
    today_d = date.today()

    # Recurring column: tasks in recurring project
    rec_tasks = _flatten_results(api.get_tasks(project_id=recurring_project_id))
    recurring_rows: List[Row] = []
    for t in rec_tasks:
        due_obj = _get(t, "due")
        if not due_obj:
            continue

        d = parse_due_to_date(str(_get(due_obj, "date", "") or ""))
        if not d:
            continue

        recurring_rows.append(
            Row(
                title=str(_get(t, "content", "") or "").strip(),
                due=d,
                overdue=(d < today_d),
            )
        )

    # To-Dos column: all dated tasks NOT in recurring project, and NOT recurring
    all_tasks = _flatten_results(api.get_tasks())
    todo_rows: List[Row] = []
    for t in all_tasks:
        if str(_get(t, "project_id", "") or "") == str(recurring_project_id):
            continue

        due_obj = _get(t, "due")
        if not due_obj:
            continue

        if bool(_get(due_obj, "is_recurring", False)):
            continue

        d = parse_due_to_date(str(_get(due_obj, "date", "") or ""))
        if not d:
            continue

        todo_rows.append(
            Row(
                title=str(_get(t, "content", "") or "").strip(),
                due=d,
                overdue=(d < today_d),
            )
        )

    recurring_rows.sort(key=lambda r: (r.due or date.max, r.title.lower()))
    todo_rows.sort(key=lambda r: (r.due or date.max, r.title.lower()))
    return recurring_rows, todo_rows


# ----------------------------
# Render
# ----------------------------
def render_dashboard(recurring: List[Row], todos: List[Row]) -> Image.Image:
    img = Image.new("L", (W, H), 255)
    draw = ImageDraw.Draw(img)

    now = datetime.now()
    today_d = now.date()

    draw_dividers(draw)
    draw_header(draw, COL1_X0, COL1_X1, "Recurring")
    draw_header(draw, COL2_X0 + 10, COL2_X1, "To-Dos")
    draw_header(draw, COL3_X0 + INFO_PAD_LEFT, COL3_X1, "Info")

    # Recurring list
    y = LIST_START_Y
    for r in recurring[:10]:
        draw_task_row(draw, COL1_X0, COL1_DATE_X, y, r)
        y += ROW_H

    # Todos list
    y = LIST_START_Y
    for r in todos[:10]:
        draw_task_row(draw, COL2_X0 + 10, COL2_DATE_X, y, r)
        y += ROW_H

    # Info column
    ix = COL3_X0 + INFO_PAD_LEFT
    iy = LIST_START_Y

    # Weather placeholder (wire later)
    draw.text((ix, iy), "42°F  Snow", font=FONT_BODY, fill=0)
    iy += BODY_LINE_HEIGHT
    draw.text((ix, iy), "↑ 47°   ↓ 31°", font=FONT_BODY, fill=0)
    iy += BODY_LINE_HEIGHT * 2

    # Calendar
    iy = draw_month_calendar(draw, ix, iy, now.year, now.month, today_d=today_d)
    iy += 18

    # System status
    updated = now
    next_dt = updated  # placeholder until scheduler exists

    draw.text((ix, iy), "Updated:", font=FONT_SMALL, fill=0)
    iy += 16
    draw.text((ix, iy), fmt_ts(updated), font=FONT_SMALL, fill=0)
    iy += 26

    draw.text((ix, iy), "Next:", font=FONT_SMALL, fill=0)
    iy += 16
    draw.text((ix, iy), fmt_ts(next_dt), font=FONT_SMALL, fill=0)

    return img


# ----------------------------
# Output: PNG + Waveshare
# ----------------------------
def save_png(img: Image.Image, out_path: str) -> str:
    out_path = out_path.strip() if out_path else "out/dashboard.png"
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    img.save(out_path)
    return out_path


def to_epd_image(img: Image.Image) -> Image.Image:
    # Waveshare expects 1-bit image
    if img.mode != "1":
        img = img.convert("1")  # keep text crisp
    return img


def push_to_waveshare(img: Image.Image) -> None:
    # Import locally so PNG-only runs don't require Waveshare libs installed
    sys.path.append("/home/eric/projects/e-Paper/RaspberryPi_JetsonNano/python/lib")
    from waveshare_epd import epd7in5_V2

    epd = epd7in5_V2.EPD()
    try:
        epd.init()
        epd.display(epd.getbuffer(img))
    finally:
        try:
            epd.sleep()
        except Exception:
            pass


# ----------------------------
# CLI
# ----------------------------
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="Use mock data")
    parser.add_argument("--png", action="store_true", help="Write PNG preview")
    parser.add_argument("--display", action="store_true", help="Push to e-ink display")
    parser.add_argument("--both", action="store_true", help="Write PNG AND push to display")
    parser.add_argument("--out", default="out/dashboard.png", help="PNG output path")
    parser.add_argument(
        "--recurring-project-id",
        default="",
        help="Todoist project ID for recurring tasks (overrides RECURRING_PROJECT_ID env)",
    )
    args = parser.parse_args()

    do_png = args.png or args.both
    do_display = args.display or args.both
    if not do_png and not do_display:
        do_png = True

    # ✅ Load .env BEFORE reading environment variables
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    load_dotenv(dotenv_path=os.path.join(repo_root, ".env"), override=True)

    recurring_project_id = (args.recurring_project_id or "").strip() or os.getenv("RECURRING_PROJECT_ID", "").strip()

    if args.mock:
        recurring, todos = get_mock_rows()
    else:
        # fetch_todoist_rows no longer needs to load dotenv, but it's okay if it still does
        recurring, todos = fetch_todoist_rows(recurring_project_id=recurring_project_id)

    img = render_dashboard(recurring=recurring, todos=todos)

    if do_png:
        out_path = save_png(img, args.out)
        print(f"Wrote {out_path}")

    if do_display:
        img1 = to_epd_image(img)
        push_to_waveshare(img1)
        print("Pushed to Waveshare display")


if __name__ == "__main__":
    main()
