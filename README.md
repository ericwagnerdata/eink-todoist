# eink-todoist

A small, always-on e-ink dashboard that renders my Todoist tasks on a Waveshare 7.5" display driven by a Raspberry Pi Zero 2 W.

![Dashboard preview](docs/images/dashboard.png)

## Inspiration

I live in Todoist — it's where my work, errands, and side projects all land. But pulling out my phone or opening a tab to check what's next adds just enough friction that I'd sometimes lose track of what I'd planned for the day.

I also have a 3D printer and a soft spot for hobby electronics. An e-ink panel felt like the right medium: paper-like, glanceable, no glow, and happy to sit on a shelf and update itself a few times an hour. Putting it together meant designing a printed enclosure, wiring up the Pi, and writing the code to tie my Todoist data to a layout that actually reads well on a 7.5" screen.

This repo is the code half of that project — a portfolio piece more than a product, but copy-friendly if you want to build your own.

## Hardware

- Raspberry Pi Zero 2 W
- Waveshare 7.5" e-Paper HAT (V2, 800×480)
- 3D-printed enclosure (designed for desk/shelf placement) — message me if you'd like the STLs

## How it works

- A Python script pulls tasks from the Todoist API
- Pillow renders a dashboard layout (overdue pills, today's list, what's next, quiet-hour-aware "Next refresh" timestamp)
- The image is pushed to the e-ink display on a 30-minute cadence with quiet hours overnight
- Runs as a service on the Pi

## Layout

The dashboard is tuned for an e-ink panel: high contrast, no anti-aliased gray, and a fixed grid so partial refreshes don't smear. Lists are capped at 10 items to keep the page calm.

## Setup

```bash
git clone https://github.com/ericwagnergithub/eink-todoist.git
cd eink-todoist
pip install -r requirements.txt
```

Create a `.env` with your Todoist API token:

```bash
TODOIST_API_TOKEN=your_token_here
```

Then run the dashboard script on the Pi:

```bash
python scripts/dashboard.py
```

`scripts/mock_dashboard.py` and `scripts/layout_mock.py` render the layout to a PNG without needing the display attached — handy for iterating on design from a regular computer.

## Contact

If you want the enclosure STLs, have questions, or want to chat about the build, feel free to reach out.
