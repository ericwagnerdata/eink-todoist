# Deploy

Systemd units for running the dashboard on the Raspberry Pi.

Adjust paths in the `.service` file if the repo lives somewhere other than
`/home/eric/projects/eink-todoist`.

## Install

```bash
sudo cp deploy/eink-todoist.service /etc/systemd/system/
sudo cp deploy/eink-todoist.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now eink-todoist.timer
```

The timer fires every 30 minutes between 08:00 and 21:30. The service exits
immediately after each run (Type=oneshot), so there is no persistent process.

## Check logs

```bash
journalctl -u eink-todoist
```

## Run manually

```bash
sudo systemctl start eink-todoist.service
```

## Notes

- The `.env` file must exist at the repo root with `TODOIST_API_TOKEN` and
  `RECURRING_PROJECT_ID` set. See the main README for all variables.
- If the Waveshare library lives at a non-default path, set `WAVESHARE_LIB_PATH`
  in the `[Service]` block or in the `.env` file.
