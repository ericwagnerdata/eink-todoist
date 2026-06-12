# Deploy

Systemd units for running the dashboard on the Raspberry Pi. These mirror the
units installed on the Pi (`eink-dashboard.service` / `eink-dashboard.timer`).
The repo copy is the source of truth. If you edit the units, re-copy them to
`/etc/systemd/system/` and run `daemon-reload`.

Adjust paths in the `.service` file if the repo lives somewhere other than
`/home/eric/projects/eink-todoist`. The service runs the script with the
repo's `.venv` Python, so dependencies must be installed there
(`.venv/bin/pip install -r requirements.txt`).

## Install

```bash
sudo cp deploy/eink-dashboard.service /etc/systemd/system/
sudo cp deploy/eink-dashboard.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now eink-dashboard.timer
```

The timer fires every 30 minutes between 08:00 and 21:30. The service exits
immediately after each run (Type=oneshot), so there is no persistent process.

## Check logs

```bash
tail -50 /var/log/eink-dashboard.log
```

## Run manually

```bash
sudo systemctl start eink-dashboard.service
```

Or without sudo, bypassing the unchanged-content skip:

```bash
.venv/bin/python scripts/dashboard.py --display --force
```

## Notes

- The `.env` file must exist at the repo root with `TODOIST_API_TOKEN` and
  `RECURRING_PROJECT_ID` set. See the main README for all variables.
- If the Waveshare library lives at a non-default path, set `WAVESHARE_LIB_PATH`
  in the `[Service]` block or in the `.env` file.
