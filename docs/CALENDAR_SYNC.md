# Google Calendar sync

Read-only Google Calendar ingestion, so calendar events can be correlated with the
Fitbit/Google Health data already in InfluxDB. Calendar access is never written back to
Google. Full design and progress: `docs/CALENDAR_SYNC_BACKLOG.md`.

## Setup

1. **Google Cloud.** Enable the *Google Calendar API* in the project owning the OAuth client
   you intend to use. If the consent screen is still in *Testing*, refresh tokens expire after
   seven days — switch it to *In production* (personal use needs no verification). Add the
   redirect URI `http://localhost:8765/` to the client for the CLI flow below, and
   `http://localhost:8000/api/calendar/callback` for the API flow.
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

## Connecting through the API

The API can run the same flow without a shell on the host, which is the usual route when the
stack runs under Compose (D13). Register `http://localhost:8000/api/calendar/callback` as a
redirect URI on the OAuth client, set `CALENDAR_CLIENT_ID` / `CALENDAR_CLIENT_SECRET` (both
fall back to `GOOGLE_*`) and, if the API is not reached at `localhost:8000`,
`CALENDAR_REDIRECT_URI`.

```bash
curl -H "Authorization: Bearer $AI_API_TOKEN" http://127.0.0.1:8000/api/calendar/connect
# {"authorization_url":"https://accounts.google.com/o/oauth2/v2/auth?...","expires_in":600}
```

Open the returned URL in a browser and grant the read-only scope. Google redirects back to
`/api/calendar/callback`, which answers with the plain text *Google Calendar connected. You can
close this tab.* and writes `CALENDAR_TOKEN_FILE_PATH` (mode `0600`). The collector picks the
new file up on its next cycle; no restart is needed.

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `GET /api/calendar/connect` | bearer | Returns an authorization URL bound to a single-use `state` nonce (10 minutes, at most 10 pending, oldest evicted) |
| `GET /api/calendar/callback?state=&code=` | none — Google redirects the browser here | Validates the nonce, exchanges the code, writes the token file |

Errors: `503 CALENDAR_NOT_CONFIGURED` when the client credentials are missing;
`400 CALENDAR_CONNECT_REJECTED` for an unknown, expired, replayed or denied authorization.
Neither the authorization code nor any token or client secret appears in a response or a log
line.

Both containers must be able to read the `0600` token file, so the API runs as the collector's
uid:

```bash
docker compose exec fitbit-fetch-data id -u     # e.g. 1000
echo 'API_UID=1000' >> .env                     # default 10001
docker compose up -d --build ai-api
```

`ai-api` stays `read_only: true`; the bind-mounted `./tokens` is its only writable path.

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

## Endpoints

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `GET /api/health/calendar?period=7d` | bearer | Stored `Calendar Events` rows, unprocessed (see docs/HEALTH_API.md) |
| `GET /api/calendar/events?period=7d` | bearer | Readable events with the heart-rate response measured around each one |

`/api/calendar/events` follows the health period rules: `?period=7d`, default
`AI_DEFAULT_ANALYSIS_DAYS`, maximum `AI_MAX_ANALYSIS_DAYS`, whole local days up to now, and no
other query parameter. It reuses the health error codes — `422 INVALID_HEALTH_PERIOD`,
`422 HEALTH_QUERY_TOO_LARGE`, `503 DATA_SERVICE_UNAVAILABLE`.

The response carries `start`, `end`, `timezone`, `bucket_minutes` (the intraday resolution the
period was read at, 7 d → 1 min, 30 d → 3 min, 90 d → 7 min, so no read exceeds the 20 000-row
cap) and `events[]`. Each event has `event_id`, `calendar_id`, `summary`, `start`, `end`,
`duration_minutes`, `attendees`, `is_organizer`, `response_status`, `event_type`,
`recurring_event_id`, `notes[]` and `vitals`:

```jsonc
{
  "mean_hr": 92.5, "max_hr": 108, "sample_count": 30, "coverage_pct": 100,
  "hr_vs_resting_pct": 54.1667,        // against the resting HR of the event's local day
  "steps": 120, "steps_per_minute": 4, "movement_confounded": false,
  "pre30_mean_hr": 78.2, "post30_mean_hr": 80.1, "recovery_delta": -12.4
}
```

Only events whose heart-rate response can mean something are listed: cancelled, all-day, *free*
(`transparent`) and shorter-than-10-minute events are left out, and a moved event appears once,
with its newest stored row. `vitals` is `null` when heart-rate buckets cover less than half of
the event; `notes[]` then says so, and also flags movement during the event or a missing resting
baseline (the baseline falls back to the nearest resting heart rate within seven days). Elevated
heart rate is a stress *proxy*, never a diagnosis: movement, caffeine and illness confound it.

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
- **`redirect_uri_mismatch` from Google, or `400 CALENDAR_CONNECT_REJECTED`** — the OAuth
  client has no redirect URI matching `CALENDAR_REDIRECT_URI`, or the browser was sent an
  authorization URL older than ten minutes. Call `GET /api/calendar/connect` again.
- **The API cannot read or write the token file** — its uid does not match the collector's.
  Compare `docker compose exec fitbit-fetch-data id -u` with `API_UID` and rebuild `ai-api`.

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
| `CALENDAR_REDIRECT_URI` | `http://localhost:8000/api/calendar/callback` | Redirect target of the API connect flow |
| `API_UID` | `10001` | uid the API container builds and runs as; align it with the collector |

## Privacy

The connected scope is read-only and limited to events. Attendee email addresses and event
descriptions are never stored — only the attendee count. Tokens never appear in logs, in error
messages or in API responses.
