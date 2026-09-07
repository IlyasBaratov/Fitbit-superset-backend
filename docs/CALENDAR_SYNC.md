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
