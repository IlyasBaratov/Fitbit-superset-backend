# Google Calendar sync

Read-only Google Calendar ingestion, so calendar events can be correlated with the
Fitbit/Google Health data already in InfluxDB. Calendar access is never written back to
Google. Full design and progress: `docs/CALENDAR_SYNC_BACKLOG.md`.

## Setup

1. **Google Cloud.** Enable the *Google Calendar API* in the project owning the OAuth client
   you intend to use. If the consent screen is still in *Testing*, refresh tokens expire after
   seven days — switch it to *In production* (personal use needs no verification). Add the
   redirect URI `http://localhost:8765/` to the client for the CLI flow below.
2. **Credentials.** Put them in `.env` as `CALENDAR_CLIENT_ID` and `CALENDAR_CLIENT_SECRET`;
   both fall back to `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` when left empty.
   `CALENDAR_IDS` is a comma-separated list of calendar ids (default `primary`), each taken
   from Google Calendar → Settings → *Integrate calendar* → *Calendar ID*.
3. **Authorize.** Run the loopback flow on the host — it needs a browser, so it does not run
   inside the container:

   ```bash
   python -m scripts.google_calendar_authorize            # --port 8765 by default
   ```

   Run it from the repository root so that `app` is importable.

   The script prints an authorization URL and opens it in a browser. Grant the read-only
   `calendar.events.readonly` scope; Google redirects back to `http://localhost:8765/`, the
   one-shot local server checks the `state` nonce, exchanges the code and writes the token.
   Nothing is read from stdin and no token value is ever printed. A rejected or mismatched
   `state` writes no file.
4. **Check the token.** It lands at `CALENDAR_TOKEN_FILE_PATH` (default
   `./tokens/google_calendar.token`, mode `0600`), separate from the health token, with
   `"provider": "google_calendar"`. Compose bind-mounts `./tokens` into the worker at
   `/app/tokens`, so the file is picked up without rebuilding; the worker re-reads it when its
   mtime changes, so reconnecting needs no restart. A missing file simply means *not
   connected*: calendar sync is skipped and health collection is unaffected.
5. **Enable sync.** Set `CALENDAR_SYNC_ENABLED=true` and restart the collector.

Re-running the script re-authorizes and overwrites the token file. To disconnect, delete the
token file; the worker notices on its next cycle.

## Running it with Docker

```bash
python -m scripts.google_calendar_authorize      # on the host, writes ./tokens/google_calendar.token
echo 'CALENDAR_SYNC_ENABLED=true' >> .env        # plus CALENDAR_IDS / CALENDAR_CLIENT_* if needed
docker compose up -d fitbit-fetch-data
docker compose logs -f fitbit-fetch-data
```

`./tokens` is bind-mounted into the collector, so the token file needs no rebuild and no
restart: the worker re-reads it whenever its mtime changes.

Once `CALENDAR_SYNC_ENABLED=true`, the collector syncs the calendar once at startup and then
every 15 minutes, re-reading the whole
`[today − CALENDAR_SYNC_DAYS_BACK, today + CALENDAR_SYNC_DAYS_AHEAD]` window so that moved and
cancelled events are corrected. Health collection runs independently and never waits for it.

Expected log lines:

| Line | Meaning |
| --- | --- |
| `Google Calendar connected` | A token was found and the first sync succeeded |
| `Google Calendar is not connected; skipping calendar sync until it is` | No token file, or it was revoked or deleted — logged once per state change, not every cycle |
| `Successfully wrote N points to InfluxDB` | The sync reached InfluxDB (shared with health writes) |
| `calendar <id> unavailable: permission or device capability (HTTP 403)` | That one calendar was skipped; the others still sync |

Check the stored data:

```bash
docker compose exec influxdb influx -database FitbitHealthStats \
  -execute 'SELECT * FROM "Calendar Events" ORDER BY time DESC LIMIT 5'
```

## Troubleshooting

- **`Google Calendar is not connected`** — the token file is missing at
  `CALENDAR_TOKEN_FILE_PATH` or no longer valid. Re-run the authorize script on the host and
  confirm the file exists in `./tokens/`; the worker picks it up within one cycle.
- **No calendar job at all** — `CALENDAR_SYNC_ENABLED` is not truthy, or
  `SCHEDULE_AUTO_UPDATE` is off. The calendar job is registered beside the other periodic jobs.
- **HTTP 403 for a calendar** — the *Google Calendar API* is not enabled in the client's
  project, or the token was granted without the `calendar.events.readonly` scope. Only that
  calendar is skipped; fix the scope and re-authorize.
- **The token stops working every seven days** — the OAuth consent screen is still in
  *Testing*. Switch it to *In production* (see step 1 of Setup).
- **HTTP 404 for a calendar id** — the id in `CALENDAR_IDS` is wrong or not shared with the
  authorized account.

## Environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `CALENDAR_SYNC_ENABLED` | `false` | Run the calendar job beside health collection |
| `CALENDAR_IDS` | `primary` | Comma-separated calendar ids to sync |
| `CALENDAR_CLIENT_ID` / `CALENDAR_CLIENT_SECRET` | `GOOGLE_*` | OAuth client for the calendar scope |
| `CALENDAR_TOKEN_FILE_PATH` | `<token dir>/google_calendar.token` | Calendar token file |
| `CALENDAR_SYNC_DAYS_BACK` | `7` | Days before today in the rolling re-sync window |
| `CALENDAR_SYNC_DAYS_AHEAD` | `1` | Days after today in the rolling re-sync window |
| `CALENDAR_API_BASE_URL` | `https://www.googleapis.com/calendar/v3` | Calendar API root |

## Privacy

The connected scope is read-only and limited to events. Attendee email addresses and event
descriptions are never stored — only the attendee count. Tokens never appear in logs, in error
messages or in API responses.
