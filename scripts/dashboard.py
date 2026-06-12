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
- --force      : force display push even if content is unchanged

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
- Updated shows full date + 12h time AM/PM
- Stale notice shown in INFO column when running from cached data
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import sys
import requests
from dataclasses import dataclass
from datetime import datetime, date, timedelta
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

GUTTER = 16  # space between a divider and the text on either side
COL1_TEXT_X = COL1_X0
COL1_DATE_X = COL1_X1 - GUTTER
COL2_TEXT_X = COL2_X0 + GUTTER
COL2_DATE_X = COL2_X1 - GUTTER
TITLE_DATE_GAP = 14  # minimum space between a title and its date label

HEADER_Y = PAD_Y
HEADER_H = 34
HEADER_LINE_Y_OFFSET = 28

LIST_START_Y = HEADER_Y + HEADER_H + 10
ROW_H = 32

INFO_PAD_LEFT = 16
BODY_LINE_HEIGHT = 28

WMO_WEATHER = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Cloudy",
    45: "Fog",
    48: "Rime fog",
    51: "Drizzle",
    53: "Drizzle",
    55: "Drizzle",
    61: "Rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Showers",
    81: "Showers",
    82: "Heavy showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "T-storm hail",
    99: "T-storm hail",
}


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


# Pi paths first; Windows paths let `--mock --png` previews render with real fonts on a PC.
_SANS_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
_SANS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
]
_MONO = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "C:/Windows/Fonts/consola.ttf",
]

FONT_HEADER = _load_font(_SANS_BOLD, 22)
FONT_BODY = _load_font(_SANS, 20)
FONT_DATE = _load_font(_SANS, 18)
FONT_SMALL = _load_font(_SANS, 14)
FONT_SMALL_BOLD = _load_font(_SANS_BOLD, 14)
FONT_MONO = _load_font(_MONO, 14)


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
# State: cache + skip-if-unchanged
# ----------------------------
def _state_dir() -> str:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(repo_root, "state")


def save_fetch_cache(recurring: List[Row], todos: List[Row]) -> None:
    state_dir = _state_dir()
    os.makedirs(state_dir, exist_ok=True)
    payload = {
        "fetched_at": datetime.now().isoformat(),
        "recurring": [
            {"title": r.title, "due": r.due.isoformat() if r.due else None}
            for r in recurring
        ],
        "todos": [
            {"title": r.title, "due": r.due.isoformat() if r.due else None}
            for r in todos
        ],
    }
    with open(os.path.join(state_dir, "last_fetch.json"), "w") as f:
        json.dump(payload, f, indent=2)


def load_fetch_cache() -> Tuple[List[Row], List[Row], datetime]:
    """Load cached rows and the fetch timestamp. Raises if cache missing or corrupt."""
    cache_path = os.path.join(_state_dir(), "last_fetch.json")
    with open(cache_path) as f:
        data = json.load(f)
    fetched_at = datetime.fromisoformat(data["fetched_at"])
    today_d = date.today()

    def _rows(items):
        rows = []
        for item in items:
            d = date.fromisoformat(item["due"]) if item.get("due") else None
            rows.append(Row(
                title=item["title"],
                due=d,
                overdue=(d < today_d) if d else False,
            ))
        return rows

    recurring = _rows(data.get("recurring", []))
    todos = _rows(data.get("todos", []))
    return recurring, todos, fetched_at


def compute_content_signature(
    recurring: List[Row],
    todos: List[Row],
    weather_lines: Tuple[str, str],
    stale: bool,
) -> str:
    payload = {
        "date": date.today().isoformat(),
        "stale": stale,
        "weather": list(weather_lines),
        "recurring": [
            {"title": r.title, "due": r.due.isoformat() if r.due else None, "overdue": r.overdue}
            for r in recurring
        ],
        "todos": [
            {"title": r.title, "due": r.due.isoformat() if r.due else None, "overdue": r.overdue}
            for r in todos
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def load_last_push() -> Optional[str]:
    """Return the stored content signature from the last push, or None."""
    push_path = os.path.join(_state_dir(), "last_push.json")
    try:
        with open(push_path) as f:
            return json.load(f).get("signature")
    except Exception:
        return None


def save_last_push(signature: str) -> None:
    state_dir = _state_dir()
    os.makedirs(state_dir, exist_ok=True)
    with open(os.path.join(state_dir, "last_push.json"), "w") as f:
        json.dump({"signature": signature, "pushed_at": datetime.now().isoformat()}, f, indent=2)


# ----------------------------
# Formatting / drawing
# ----------------------------
def fmt_due(d: date) -> str:
    return d.strftime("%b") + " " + str(d.day)


def fmt_ts(dt: datetime) -> str:
    mon = dt.strftime("%b")
    return f"{mon} {dt.day}, {dt.year} {dt.strftime('%I:%M %p').lstrip('0')}"


def fmt_ts_short(dt: datetime) -> str:
    """Short timestamp for stale notice: 'Jun 11 8:55 AM'"""
    return f"{dt.strftime('%b')} {dt.day} {dt.strftime('%I:%M %p').lstrip('0')}"


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
    draw.line(
        (x0, HEADER_Y + HEADER_LINE_Y_OFFSET, x1 - GUTTER, HEADER_Y + HEADER_LINE_Y_OFFSET),
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


def draw_task_row(
    draw: ImageDraw.ImageDraw, x_text: int, x_date_right: int, y: int, row: Row, today_d: date
) -> None:
    if not row.due:
        return
    due_label = "Today" if row.due == today_d else fmt_due(row.due)

    # Reserve the date label's actual footprint (pills are wider) so titles never overlap it.
    date_w = text_w(draw, due_label, FONT_DATE)
    if row.overdue:
        date_w += 14  # pill horizontal padding
    max_title_w = max(10, x_date_right - date_w - TITLE_DATE_GAP - x_text)
    title = ellipsize_to_width(draw, row.title, FONT_BODY, max_title_w)

    draw.text((x_text, y), title, font=FONT_BODY, fill=0)
    if row.overdue:
        draw_overdue_pill(draw, x_date_right, y + 1, due_label)
    else:
        draw_right_aligned_date(draw, x_date_right, y + 3, due_label)


def draw_overflow_indicator(
    draw: ImageDraw.ImageDraw, x_text: int, y: int, extra_count: int
) -> None:
    draw.text((x_text, y), f"+{extra_count} more", font=FONT_SMALL, fill=0)


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
        Row("Take out trash and recycling bins", t.replace(day=max(1, min(28, t.day - 1))), overdue=True),
        Row("Water plants", t.replace(day=min(28, t.day + 2)), overdue=False),
        Row("Replace furnace air filter (20x25x1)", t.replace(day=min(28, t.day + 7)), overdue=False),
        Row("Pay credit card statement balance", t.replace(day=min(28, t.day + 12)), overdue=False),
    ]
    todos = [
        Row("Ship Etsy orders before pickup window", t, overdue=False),
        Row("Reply to warranty email from Bambu", t.replace(day=min(28, t.day + 2)), overdue=False),
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


def fetch_weather_lines() -> Tuple[str, str]:
    """
    Returns (line1, line2) for the INFO column.
    Uses Open-Meteo: no key required.
    Falls back to placeholder on any error.
    """
    try:
        lat = float(os.getenv("WEATHER_LAT", "").strip())
        lon = float(os.getenv("WEATHER_LON", "").strip())
    except Exception:
        return ("--°F  Weather n/a", "↑ --°   ↓ --°")  # honest fallback, never fake data

    tz = os.getenv("WEATHER_TZ", "auto").strip() or "auto"

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min",
        "temperature_unit": "fahrenheit",
        "timezone": tz if tz != "auto" else "auto",
    }

    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
        data = r.json()

        cur = data.get("current", {})
        temp = cur.get("temperature_2m")
        code = cur.get("weather_code")
        cond = WMO_WEATHER.get(code, "Weather")

        daily = data.get("daily", {})
        hi = (daily.get("temperature_2m_max") or [None])[0]
        lo = (daily.get("temperature_2m_min") or [None])[0]

        # Build display lines (keep calm + short)
        line1 = f"{round(temp)}°F  {cond}" if temp is not None else f"--°F  {cond}"
        if hi is not None and lo is not None:
            line2 = f"↑ {round(hi)}°   ↓ {round(lo)}°"
        else:
            line2 = "↑ --°   ↓ --°"

        return (line1, line2)

    except Exception:
        return ("--°F  Weather n/a", "↑ --°   ↓ --°")  # honest fallback, never fake data


# ----------------------------
# Render
# ----------------------------
def render_dashboard(
    recurring: List[Row],
    todos: List[Row],
    weather_lines: Tuple[str, str],
    stale_since: Optional[datetime] = None,
) -> Image.Image:
    img = Image.new("L", (W, H), 255)
    draw = ImageDraw.Draw(img)

    now = datetime.now()
    today_d = now.date()

    draw_dividers(draw)
    draw_header(draw, COL1_TEXT_X, COL1_X1, "Recurring")
    draw_header(draw, COL2_TEXT_X, COL2_X1, "To-Dos")
    # Third column header doubles as the at-a-glance date, e.g. "WED · JUN 11"
    today_label = f"{now.strftime('%a')} · {now.strftime('%b')} {now.day}"
    draw_header(draw, COL3_X0 + INFO_PAD_LEFT, COL3_X1, today_label)

    # Recurring list (cap at 10, show overflow indicator if more)
    y = LIST_START_Y
    visible_recurring = recurring[:10]
    for r in visible_recurring:
        draw_task_row(draw, COL1_TEXT_X, COL1_DATE_X, y, r, today_d)
        y += ROW_H
    if len(recurring) > 10:
        draw_overflow_indicator(draw, COL1_TEXT_X, y, len(recurring) - 10)

    # Todos list (cap at 10, show overflow indicator if more)
    y = LIST_START_Y
    visible_todos = todos[:10]
    for r in visible_todos:
        draw_task_row(draw, COL2_TEXT_X, COL2_DATE_X, y, r, today_d)
        y += ROW_H
    if len(todos) > 10:
        draw_overflow_indicator(draw, COL2_TEXT_X, y, len(todos) - 10)

    # Info column
    ix = COL3_X0 + INFO_PAD_LEFT
    iy = LIST_START_Y

    weather_line1, weather_line2 = weather_lines
    draw.text((ix, iy), weather_line1, font=FONT_BODY, fill=0)
    iy += BODY_LINE_HEIGHT
    draw.text((ix, iy), weather_line2, font=FONT_BODY, fill=0)
    iy += BODY_LINE_HEIGHT * 2

    # Calendar
    iy = draw_month_calendar(draw, ix, iy, now.year, now.month, today_d=today_d)
    iy += 18

    # Updated footer (single line; no Next prediction)
    updated = now.replace(second=0, microsecond=0)
    draw.text((ix, iy), "Updated:", font=FONT_SMALL, fill=0)
    iy += 16
    draw.text((ix, iy), fmt_ts(updated), font=FONT_SMALL, fill=0)
    iy += 26

    # Stale notice (inverted pill style)
    if stale_since is not None:
        stale_label = f"STALE · {fmt_ts_short(stale_since)}"
        pad_x = 5
        pad_y = 3
        sw = text_w(draw, stale_label, FONT_SMALL_BOLD)
        sbbox = draw.textbbox((0, 0), stale_label, font=FONT_SMALL_BOLD)
        sh = int(sbbox[3] - sbbox[1])
        draw.rounded_rectangle(
            (ix - pad_x, iy - pad_y, ix + sw + pad_x, iy + sh + pad_y),
            radius=4,
            fill=0,
        )
        draw.text((ix, iy), stale_label, font=FONT_SMALL_BOLD, fill=255)

    return img


def render_error_frame(message: str) -> Image.Image:
    """Minimal frame for when no data at all is available."""
    img = Image.new("L", (W, H), 255)
    draw = ImageDraw.Draw(img)

    now = datetime.now()

    draw_dividers(draw)
    draw_header(draw, COL1_TEXT_X, COL1_X1, "Recurring")
    draw_header(draw, COL2_TEXT_X, COL2_X1, "To-Dos")
    today_label = f"{now.strftime('%a')} · {now.strftime('%b')} {now.day}"
    draw_header(draw, COL3_X0 + INFO_PAD_LEFT, COL3_X1, today_label)

    # Centered message in the task area, on a white box so dividers don't strike through
    msg_w = text_w(draw, message, FONT_BODY)
    msg_x = max(COL1_TEXT_X, (W - msg_w) // 2)
    msg_y = LIST_START_Y + (H - LIST_START_Y) // 2 - 10
    draw.rectangle((msg_x - 12, msg_y - 8, msg_x + msg_w + 12, msg_y + 30), fill=255)
    draw.text((msg_x, msg_y), message, font=FONT_BODY, fill=0)

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
    lib_path = os.getenv(
        "WAVESHARE_LIB_PATH",
        "/home/eric/projects/e-Paper/RaspberryPi_JetsonNano/python/lib",
    )
    sys.path.append(lib_path)
    try:
        from waveshare_epd import epd7in5_V2
    except ImportError as exc:
        raise RuntimeError(
            f"Could not import waveshare_epd from '{lib_path}'. "
            f"Clone the Waveshare e-Paper repo and set WAVESHARE_LIB_PATH to its "
            f"RaspberryPi_JetsonNano/python/lib directory."
        ) from exc

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
    parser.add_argument("--force", action="store_true", help="Force display push even if content unchanged")
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

    # Load .env BEFORE reading environment variables
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    load_dotenv(dotenv_path=os.path.join(repo_root, ".env"), override=True)

    recurring_project_id = (args.recurring_project_id or "").strip() or os.getenv("RECURRING_PROJECT_ID", "").strip()

    # Fetch weather first (needed for content signature)
    weather_lines = fetch_weather_lines()

    stale_since: Optional[datetime] = None

    if args.mock:
        recurring, todos = get_mock_rows()
    else:
        try:
            recurring, todos = fetch_todoist_rows(recurring_project_id=recurring_project_id)
            save_fetch_cache(recurring, todos)
        except Exception as exc:
            print(f"Todoist fetch failed: {exc}", file=sys.stderr)
            # Try the cache
            try:
                recurring, todos, stale_since = load_fetch_cache()
                print(f"Using cached data from {stale_since.isoformat()}", file=sys.stderr)
            except Exception:
                # No cache available: render the error frame so the panel shows the
                # outage instead of silently staying stale, then exit cleanly.
                print("No cached data available. Rendering error frame.", file=sys.stderr)
                img = render_error_frame("Todoist unavailable, no cached data")
                if do_png:
                    out_path = save_png(img, args.out)
                    print(f"Wrote {out_path}")
                if do_display:
                    push_to_waveshare(to_epd_image(img))
                    # Invalidate the stored signature so the next good fetch always
                    # repaints over the error frame, even if the data didn't change.
                    save_last_push("error-frame")
                    print("Pushed error frame to Waveshare display")
                sys.exit(0)

    # Compute content signature (weather already fetched)
    is_stale = stale_since is not None
    signature = compute_content_signature(recurring, todos, weather_lines, is_stale)

    # Skip only the panel push when content is unchanged (PNG output still happens)
    if do_display and not args.force and load_last_push() == signature:
        print("Content unchanged; skipped display refresh.")
        do_display = False
        if not do_png:
            sys.exit(0)

    img = render_dashboard(
        recurring=recurring,
        todos=todos,
        weather_lines=weather_lines,
        stale_since=stale_since,
    )

    if do_png:
        out_path = save_png(img, args.out)
        print(f"Wrote {out_path}")

    if do_display:
        img1 = to_epd_image(img)
        push_to_waveshare(img1)
        save_last_push(signature)
        print("Pushed to Waveshare display")


if __name__ == "__main__":
    main()
