# Google Calendar sync backlog

Single source of truth for the Google Calendar ↔ wearable correlation feature.
One item = one routine run = one commit. Tick items only after `python -m pytest -q` is green.

## Goal

Pull the user's Google Calendar events into the existing stack, line them up with
Fitbit/Google Health data already in InfluxDB, and answer: *which events, series and
days raise my heart rate, hurt my sleep or lower my HRV?*

Non-goals: more than one person per stack, writing back to Google Calendar, push
notifications, a frontend. Calendar access is read-only.

## Design decisions

- **D1 Calendar is not a `HealthProvider`.** New `GoogleCalendarProvider` with one job:
  `fetch_events(start_date, end_date)`. Runs beside the health provider in the worker, only
  when `CALENDAR_SYNC_ENABLED=true`. Health collection never depends on it.
- **D2 Auth reuses `FileTokenManager`.** Separate token file `tokens/google_calendar.token`
  with `"provider": "google_calendar"`. `CALENDAR_CLIENT_ID/SECRET` fall back to
  `GOOGLE_CLIENT_ID/SECRET`. Scope: read-only
  `https://www.googleapis.com/auth/calendar.events.readonly`. The worker re-reads the file
  when its mtime changes, so connecting or reconnecting needs no restart. A missing file
  means *not connected*: the calendar job skips quietly, the worker never fails because of it.
- **D3 Transport reuses `ProviderHTTPClient`** (401 refresh, 429 backoff, 5xx skip).
- **D4 Storage = one new InfluxDB measurement `Calendar Events`, keyed by person, not
  device.** Written through a second `InfluxHealthRepository` instance whose common tags are
  `UserId=<USER_ID>`, `Provider=google_calendar`, `Device=Google Calendar`,
  `DeviceId=google_calendar`, plus tags `CalendarId`, `EventId`. Timestamp = event start
  (UTC). Re-sync overwrites the same point. Reads filter by `UserId` + `Provider=google_calendar`
  only, so calendar history survives switching `HEALTH_API_PROVIDER` or `DEVICE_ID`.
  Ceiling: one person per stack (`USER_ID`); several persons need per-user tokens and
  identity, out of scope.
- **D5 Sync policy = full rolling-window re-sync every 15 minutes:** local days
  `[today - CALENDAR_SYNC_DAYS_BACK, today + CALENDAR_SYNC_DAYS_AHEAD]`, request params
  `singleEvents=true&showDeleted=true&orderBy=startTime`, paginated (≤ 50 pages).
  No `syncToken` (Google rejects it together with `timeMin/timeMax`). Cancelled events are
  stored with `status=cancelled`. A moved event leaves its old point behind; reads dedupe by
  `EventId` keeping the row with the newest `updated`.
- **D6 Correlation runs in the API, not the worker.** Worker stays write-only and
  Influx-version agnostic; the API is already InfluxDB 1.x only. Intraday heart rate and
  steps are fetched as N-minute buckets, `N = max(1, ceil(days * 1440 / 20000))`
  (7d → 1m, 30d → 3m, 90d → 7m), so every period stays under the 20 000-row cap.
- **D7 "Stress" is a proxy, stated as such.** Fitbit Web API exposes no stress score.
  Per event: mean/max HR, % above that day's `RestingHR`, steps during the event
  (movement-confound flag), 30-minute pre/post HR, recovery delta. Per day: meeting load vs
  same-day and next-day HRV, resting HR, sleep. If Google Health exposes a stress data type
  (C0.2), it becomes a daily `Stress Score` measurement (C6.1).
- **D8 Pure analytics in `app/calendar/`** (no I/O, no `requests`), same rule as provider
  mappers. API services do the I/O.
- **D9 Privacy.** Attendee emails and descriptions are never stored (attendee count only).
  Gemini receives aggregates and series titles (≤ 80 chars, untrusted text, off with
  `CALENDAR_AI_INCLUDE_TITLES=false`), never event IDs or per-event rows.
- **D10 No new dependencies.** OAuth loopback via stdlib `http.server` + `requests`;
  Pearson via `statistics.correlation` (Python ≥ 3.10, matches the worker image).
- **D11 Existing contracts untouched** (`docs/refactor_contracts.md`): measurement names,
  fields, job cadence, routes, error envelope.
- **D12 User docs live in `docs/CALENDAR_SYNC.md`;** schema row in `docs/influxdb_schema.md`.
- **D13 Connecting a calendar is an API capability.** `GET /api/calendar/connect` (bearer)
  returns a Google authorization URL bound to a single-use `state` nonce (10-minute
  in-memory TTL; the API runs one uvicorn worker). `GET /api/calendar/callback?state&code`
  (no bearer — Google redirects the browser here) validates the nonce, exchanges the code and
  writes the token file. `GET /api/calendar/status` reports the connection;
  `DELETE /api/calendar/connection` revokes the token and deletes the file. The API therefore
  gets a read-write `./tokens` mount and runs as the worker's uid so both containers read the
  `0600` token file. OAuth helpers live in `app/providers/google_calendar/connect.py`; a thin
  stdlib CLI script wraps the same helpers for worker-only stacks.

## Data contract: `Calendar Events`

| Kind | Name | Type | Source / rule |
| --- | --- | --- | --- |
| tag | `UserId`, `Provider`, `Device`, `DeviceId` | str | `USER_ID`, `google_calendar`, `Google Calendar`, `google_calendar` (D4) |
| tag | `CalendarId` | str | configured calendar id (`primary` or address) |
| tag | `EventId` | str | `id` |
| time | — | UTC | `start.dateTime`; all-day: local midnight of `start.date` |
| field | `summary` | str | `summary`, control chars stripped, ≤ 200 chars |
| field | `startTime`, `endTime` | str | ISO 8601 UTC |
| field | `duration_seconds` | int | end − start |
| field | `status` | str | `confirmed` / `tentative` / `cancelled` |
| field | `eventType` | str | `default` / `outOfOffice` / `focusTime` / `workingLocation` / … |
| field | `transparency` | str | `opaque` (busy) / `transparent` (free) |
| field | `attendees` | int | attendees without `self: true` |
| field | `isOrganizer` | bool | `organizer.self` |
| field | `responseStatus` | str | own attendee `responseStatus`, else empty |
| field | `recurringEventId` | str | `recurringEventId`, else empty |
| field | `updated` | str | `updated` (ISO 8601) |
| field | `isAllDay` | bool | `start.date` present |

## Backlog

Format: `- [ ] **ID Title** — blocked by: …` then Files / Do / Done when / Notes.
`[manual]` items need the user's machine, browser or Docker; the routine skips them.

### C0 Prerequisites `[manual]`

- [ ] **C0.1 Google Cloud setup** `[manual]` — blocked by: none
  - Do: enable *Google Calendar API* in the project of the OAuth client you will use.
    Consent screen: if publishing status is *Testing*, refresh tokens expire after 7 days —
    switch to *In production* (personal use needs no verification; accept the one-time
    "unverified app" screen). *Web application* client: add redirect URIs
    `http://localhost:8000/api/calendar/callback` (API connect, D13) and
    `http://localhost:8765/` (CLI script). *Desktop app* client: only the first one.
  - Done when: client id/secret known; API enabled; publishing status noted here.
  - Notes:
- [ ] **C0.2 Verify stress data availability** `[manual]` — blocked by: none
  - Do: with the existing Google Health token, list data types
    (`GET $GOOGLE_HEALTH_BASE_URL/v4/dataTypes` or the API reference) and look for
    stress / electrodermal / body-response types. Fitbit Web API: none (Stress Management
    Score is app-only). Record the exact data type name and one sample payload here.
  - Done when: Notes says `available: <data-type>` or `unavailable`. Gates C6.1.
  - Notes:
- [ ] **C0.3 Choose calendars** `[manual]` — blocked by: none
  - Do: `CALENDAR_IDS=primary` or a comma list of calendar ids
    (Google Calendar → Settings → *Integrate calendar* → Calendar ID).
  - Done when: value written to `.env`.
  - Notes:

### C1 Worker ingestion

- [x] **C1.1 Worker settings for calendar sync** — blocked by: none
  - Files: `app/core/config.py` (`WorkerSettings`), `app/worker/main.py` (secret filter),
    `.env.example`, `compose.yml` (`fitbit-fetch-data` env), `tests/test_worker_config.py`.
  - Do: add frozen fields `calendar_sync_enabled` (bool, default false, same truthy parsing
    as `DRY_RUN_MODE`), `calendar_token_file_path` (default
    `<dirname(TOKEN_FILE_PATH)>/google_calendar.token`), `calendar_ids` (tuple from comma
    list, empties stripped, default `("primary",)`), `calendar_client_id` /
    `calendar_client_secret` (fallback `google_client_id` / `google_client_secret`; secret
    `repr=False`), `calendar_sync_days_back` (7), `calendar_sync_days_ahead` (1),
    `calendar_api_base_url` (`https://www.googleapis.com/calendar/v3`). Negative day
    counts → `ConfigurationError`. Compose: `CALENDAR_SYNC_ENABLED`, `CALENDAR_IDS`,
    `CALENDAR_CLIENT_ID`, `CALENDAR_CLIENT_SECRET`, `CALENDAR_SYNC_DAYS_BACK`,
    `CALENDAR_SYNC_DAYS_AHEAD`, `CALENDAR_TOKEN_FILE_PATH: /app/tokens/google_calendar.token`.
    Add `calendar_client_secret` to the `configure_logging` secrets tuple.
  - Done when: tests cover defaults, comma parsing, fallback credentials, invalid days.
  - Notes: done: 8 frozen `WorkerSettings` fields + `CALENDAR_API_BASE_URL` override,
    negative day counts raise `ConfigurationError`, secret is `repr=False` and in the worker
    secret filter; `.env.example` and `compose.yml` (`fitbit-fetch-data`) carry the vars.
    141 → 158 tests. Note: the cloud image needs `pip install cffi` on top of
    `requirements-dev.txt` or 5 API test modules fail to collect (`_cffi_backend`).
- [x] **C1.2 Calendar token manager** — blocked by: C1.1
  - Files: `app/providers/google_calendar/__init__.py`, `app/providers/google_calendar/auth.py`,
    `tests/test_token_managers.py`.
  - Do: `GoogleCalendarTokenManager(GoogleTokenManager)` with `provider = "google_calendar"`.
    `__init__` calls the parent with `dataclasses.replace(settings,
    token_file_path=settings.calendar_token_file_path,
    google_client_id=settings.calendar_client_id,
    google_client_secret=settings.calendar_client_secret)` so the inherited refresh works
    unchanged. `load()` remembers the file mtime; `get_access_token()` reloads when the mtime
    changed (reconnect through the API is picked up without a restart). Missing file →
    `AuthenticationError` as today; callers treat it as *not connected*.
  - Done when: tests: refresh writes the calendar token path, keeps `refresh_token` when
    Google omits it, provider mismatch raises `AuthenticationError`, health token file untouched,
    error text never contains the secret, mtime change triggers a reload.
  - Notes: done: `app/providers/google_calendar/auth.py` adds
    `GoogleCalendarTokenManager(GoogleTokenManager)` (`provider = "google_calendar"`), which
    re-points the inherited refresh at the calendar token path and `CALENDAR_CLIENT_ID/SECRET`
    via `dataclasses.replace`, remembers the token file `st_mtime_ns` on `load()`/`_save()` and
    drops the cached tokens in `get_access_token()` when the file changed underneath it.
    158 → 162 tests. The cloud image still needs `pip install cffi` on top of
    `requirements-dev.txt` (see C1.1).
- [x] **C1.3 OAuth connect helpers + CLI authorize script** — blocked by: C1.2
  - Files: `app/providers/google_calendar/connect.py` (new), `scripts/google_calendar_authorize.py`
    (new), `tests/test_calendar_connect.py`, `docs/CALENDAR_SYNC.md` (new: Setup section).
  - Do: helpers, no I/O beyond the injected session: `authorization_url(client_id,
    redirect_uri, state)` →
    `https://accounts.google.com/o/oauth2/v2/auth?client_id&redirect_uri&response_type=code&scope=<D2 scope>&access_type=offline&prompt=consent&state`;
    `exchange_code(session, client_id, client_secret, redirect_uri, code, timeout) -> dict`
    posting `grant_type=authorization_code` to `https://oauth2.googleapis.com/token`, raising
    `AuthenticationError` without echoing the response body; `token_record(payload)` →
    `{"provider": "google_calendar", "refresh_token", "access_token", "saved_at_utc",
    "expires_in"}`; `revoke(session, token, timeout)` (POST
    `https://oauth2.googleapis.com/revoke`, best effort). Script: stdlib loopback — print the
    URL and `webbrowser.open`, one-shot `http.server` handler on `--port` (default 8765)
    captures `code`, checks `state`, saves through `GoogleCalendarTokenManager._save`
    (atomic). Reads `.env` via `dotenv` (`CALENDAR_*` with `GOOGLE_*` fallback). Never prints
    tokens. No `input()`.
  - Done when: helper tests (URL contents, exchange payload, sanitized failure, record
    shape); script test drives the handler with a fake request path and a mocked exchange →
    token file content; wrong `state` → rejected, nothing written. Docs: run on the host,
    token lands in `./tokens/`, which Compose bind-mounts into the worker.
  - Notes: done: `app/providers/google_calendar/connect.py` holds `authorization_url`,
    `exchange_code`, `token_record` and best-effort `revoke` (session injected, no other I/O,
    failures never echo the response body); `scripts/google_calendar_authorize.py` prints the
    URL, opens a browser and serves one loopback request whose `state` is compared with
    `secrets.compare_digest` before the exchange, saving through
    `GoogleCalendarTokenManager._save` (atomic, `0600` from `NamedTemporaryFile`). No stdin, no
    token ever printed. `docs/CALENDAR_SYNC.md` adds Setup, Environment and Privacy sections.
    162 → 175 tests. The script is run as `python -m scripts.google_calendar_authorize` from
    the repository root (`scripts/` is a namespace package; running the file directly leaves
    `app` off `sys.path`). The cloud image still needs `pip install cffi` on top of
    `requirements-dev.txt` (see C1.1).
- [x] **C1.4 Calendar HTTP client** — blocked by: C1.1
  - Files: `app/providers/google_calendar/client.py`, `tests/test_google_calendar_client.py`.
  - Do: `GoogleCalendarClient(settings, transport)`;
    `list_events(calendar_id, time_min, time_max) -> list[dict]`: GET
    `{calendar_api_base_url}/calendars/{urllib.parse.quote(calendar_id, safe="")}/events` with
    `singleEvents=true, showDeleted=true, orderBy=startTime, maxResults=250, timeMin, timeMax,
    pageToken`; follow `nextPageToken` ≤ 50 pages; `transport.request` returning `None`
    (5xx skip) → stop and log, keep collected items.
  - Done when: Mock-transport tests: params, id encoding (`user@example.com`), 3-page
    pagination, `None` page handling. No network at import (architecture test).
  - Notes: done: `app/providers/google_calendar/client.py` adds `GoogleCalendarClient`
    (`list_events(calendar_id, time_min, time_max)`) building the events URL from
    `calendar_api_base_url` with `quote(calendar_id, safe="")`, sending the D5 params
    (`singleEvents`/`showDeleted` as the strings `"true"`, `orderBy=startTime`,
    `maxResults=250`) and following `nextPageToken` up to `MAX_PAGES=50`; a non-dict page
    (the transport's 5xx skip returns `None`) logs and returns the events collected so far.
    Endpoint definitions only, no parsing — same shape as `FitbitClient`. 175 → 180 tests.
    The cloud image still needs `pip install cffi` on top of `requirements-dev.txt` (see C1.1).
- [x] **C1.5 Pure event mapper + schema contract** — blocked by: none
  - Files: `app/providers/google_calendar/mapper.py`, `app/domain/measurements.py`
    (`FIELD_TYPES["Calendar Events"]`), `docs/influxdb_schema.md`,
    `tests/fixtures/google_calendar_contract.json`, `tests/test_google_calendar_mapper.py`,
    `tests/test_architecture.py` (add `google_calendar/mapper.py` to the pure-mapper check).
  - Do: `map_events(items, calendar_id, local_timezone) -> list[HealthPoint]` per the data
    contract table. Timed events: `start.dateTime` (offset-aware) → UTC via `utc_timestamp`.
    All-day: `local_date_boundary_utc(start.date)`, `isAllDay=true`, duration from the date
    difference. Cancelled instances may lack `start` → use `originalStartTime`; skip items
    without `id` or any start. Fixture: timed meeting with 3 attendees, all-day, cancelled
    instance, recurring instance, `focusTime`, `transparent` event, event without summary —
    plus expected normalized points (same style as `tests/fixtures/google_mapping_contract.json`).
  - Done when: fixture parity test passes; `FIELD_TYPES` entry; schema doc row; architecture
    test extended; `tests/test_health_schema.py` still green.
  - Notes: done: `app/providers/google_calendar/mapper.py` adds `map_events(items,
    calendar_id, local_timezone)` (pytz zone, like the Fitbit mapper) returning `Calendar
    Events` `HealthPoint`s per the data contract: timed starts through `utc_timestamp`,
    all-day through `local_date_boundary_utc` (duration from the date difference, so a DST day
    is 25 h), `originalStartTime` fallback for cancelled instances, items without an `id` or
    any start skipped, `summary` reduced to ≤ 200 printable characters with whitespace
    collapsed, attendee count excluding `self` (no addresses stored, D9), and Google's omitted
    defaults restored (`status=confirmed`, `eventType=default`, `transparency=opaque`).
    Empty strings and absent ends drop out through `sanitize_fields`/`coerce_fields`.
    `FIELD_TYPES["Calendar Events"]` + a schema doc row (person-keyed tags) added;
    `tests/fixtures/google_calendar_contract.json` holds 9 items → 7 reviewed expected rows;
    `tests/test_architecture.py` now covers `google_calendar/mapper.py` (missing per-provider
    mapper filenames are skipped). 180 → 191 tests. The cloud image still needs
    `pip install cffi` on top of `requirements-dev.txt` (see C1.1).
- [x] **C1.6 Calendar provider + ingestion service + jobs** — blocked by: C1.2, C1.4, C1.5
  - Files: `app/providers/google_calendar/provider.py`, `app/providers/factory.py`
    (`create_calendar_provider(settings, timezone) -> provider | None`),
    `app/ingestion/service.py` (`calendar=None, calendar_repository=None` params,
    `sync_calendar(start, end) -> bool`), `app/ingestion/jobs.py` (`sync_calendar()`,
    `initial_sync`, `bulk_sync` once over the manual range),
    `tests/test_google_calendar_provider.py`, `tests/test_ingestion_service.py`,
    `tests/test_ingestion_schedule.py`, `tests/test_provider_factory.py`.
  - Do: provider `fetch_events(start_date, end_date)`: local midnight of `start_date` to local
    midnight of `end_date + 1` as RFC3339 UTC; loop `calendar_ids`; per calendar use the
    `_available` pattern (403/404 → warn, skip that calendar); `AuthenticationError`
    (missing, revoked or invalid token) → log *calendar not connected* once per state change,
    return `[]` — health collection never stops because of the calendar; return mapped
    points. `refresh_credentials()`, `close()`. Factory: `None` when disabled; otherwise build
    transport + client + provider using the health provider's timezone **without** refreshing
    at startup (the token may not exist yet; D2/D13). `sync_calendar` writes through
    `calendar_repository` (person-keyed tags, D4) and returns `False` when no calendar
    provider. Jobs window: `[today − days_back, today + days_ahead]` in the provider timezone.
  - Done when: tests: window math across midnight, disabled → no calls, one calendar 403 does
    not block the next, missing/revoked token returns `[]` and logs once, points written
    through the calendar repository, never through the health repository.
  - Notes: done: `app/providers/google_calendar/provider.py` adds `GoogleCalendarProvider`
    (`fetch_events(start_date, end_date)`) turning whole local days into the half-open UTC
    window Google expects (`local_date_boundary_utc(start)` → `local_date_boundary_utc(end + 1
    day)`), looping `calendar_ids` through the `_available` pattern (403/404 or an exhausted
    retry budget warns and skips that calendar only) and mapping each page with `map_events`;
    an `AuthenticationError` anywhere in the loop returns `[]` and logs *not connected* once
    per state change, so health collection is never affected. `create_calendar_provider(
    settings, timezone)` returns `None` while `CALENDAR_SYNC_ENABLED` is false and otherwise
    builds token manager + transport + client **without** refreshing at startup (the token file
    may not exist yet). `IngestionService` takes optional `calendar` / `calendar_repository` and
    `sync_calendar(start, end)` writes only through the calendar repository (`False` when either
    is absent); `IngestionJobs.calendar_dates()` / `sync_calendar()` roll the
    `[today − back, today + ahead]` window in the provider timezone, `initial_sync` runs it once
    and `bulk_sync` covers the manual range once. Scheduler registration stays with C1.7.
    191 → 204 tests. The cloud image still needs `pip install cffi` on top of
    `requirements-dev.txt` (see C1.1).
- [x] **C1.7 Scheduler + worker wiring + setup docs** — blocked by: C1.6
  - Files: `app/ingestion/scheduler.py`, `app/worker/main.py`, `tests/test_ingestion_schedule.py`,
    `tests/test_worker_entrypoint.py`, `docs/CALENDAR_SYNC.md`, `README.md`.
  - Do: `register()` adds `every(15).minutes.do(_run_job, jobs.sync_calendar)` only when the
    ingestion service has a calendar provider (job count 10 → 11). `run()`: build the calendar
    provider after the health provider, `resources.callback(calendar.close)`; build
    `calendar_repository = InfluxHealthRepository(settings, build_common_tags(settings.user_id,
    "google_calendar", "Google Calendar", "google_calendar"), zone)` with its own client,
    `resources.callback(calendar_repository.close)`; pass both to `IngestionService`. Docs:
    Docker steps (connect via API or CLI, set env, `docker compose up -d fitbit-fetch-data`),
    expected log lines, troubleshooting (*not connected* → connect; 403 → API not enabled or
    wrong scope; token dies weekly → publishing status, see C0.1). README: measurement list
    22 → 23 (`Calendar Events`), pointer to the doc.
  - Done when: cadence test asserts 10 jobs without calendar and 11 with; entrypoint test shows
    both calendar `close` callbacks on exit; `docker compose config --quiet` passes (skip with
    a note if Docker is unavailable in the run environment).
  - Notes: done: `IngestionScheduler.register()` adds
    `every(15).minutes.do(_run_job, jobs.sync_calendar)` only when the ingestion service holds a
    calendar provider (10 jobs without, 11 with), registered beside the other periodic jobs so a
    manual/bulk stack does not poll. `app/worker/main.py` builds the calendar provider after the
    health provider (`create_calendar_provider(settings, provider.timezone)`, `None` while
    disabled) and then a second `InfluxHealthRepository` with its own client and person-keyed
    common tags (`Provider=google_calendar`, `Device=Google Calendar`, `DeviceId=google_calendar`,
    D4); both `close` callbacks join the health resources on the same `ExitStack`, so a scheduling
    failure still closes all four. `docs/CALENDAR_SYNC.md` gains "Running it with Docker" (connect,
    enable, `docker compose up -d fitbit-fetch-data`, expected log lines, the `Calendar Events`
    query) and a Troubleshooting section; README lists 23 measurements and points at the doc.
    `docker compose config --quiet` passes in the cloud image (the Docker CLI is present; config
    validation needs no daemon). 204 → 207 tests. The cloud image still needs `pip install cffi`
    on top of `requirements-dev.txt` (see C1.1).
- [x] **C1.8 Connect and callback API** — blocked by: C1.3
  - Files: `app/core/config.py` (API `Settings`), `app/api/routes/calendar.py` (new),
    `app/api/calendar_connect.py` (new: nonce store + orchestration), `app/api/main.py`
    (router, `app.state.calendar_connect`), `compose.yml` (`ai-api`), `Dockerfile.api`,
    `.env.example`, `docs/CALENDAR_SYNC.md` (Connect section), `tests/test_calendar_connect_routes.py`.
  - Do: `Settings` gains `calendar_client_id` / `calendar_client_secret` (fallback `GOOGLE_*`,
    secret `repr=False`, added to the logging secrets tuple), `calendar_token_file_path`,
    `calendar_redirect_uri` (default `http://localhost:8000/api/calendar/callback`),
    `calendar_ids`; all optional — the API starts without them and `connect` answers 503
    `CALENDAR_NOT_CONFIGURED`. `GET /api/calendar/connect` (bearer): create `state =
    secrets.token_urlsafe(32)`, store `{state: expires_at}` (10 min, max 10 pending, oldest
    evicted), return `{"authorization_url": ..., "expires_in": 600}`. `GET
    /api/calendar/callback?state&code` (no bearer): unknown/expired `state` or Google `error`
    param → 400 `CALENDAR_CONNECT_REJECTED` with a generic message; otherwise pop the nonce,
    `exchange_code` with a `requests.Session` owned by the app, save through
    `GoogleCalendarTokenManager._save` (atomic, `0600`), respond 200 with a tiny plain-text
    "Google Calendar connected. You can close this tab." — never tokens, never the code.
    Compose: `ai-api` gets `./tokens:/app/tokens` (read-write), env `CALENDAR_CLIENT_ID`,
    `CALENDAR_CLIENT_SECRET`, `CALENDAR_TOKEN_FILE_PATH: /app/tokens/google_calendar.token`,
    `CALENDAR_REDIRECT_URI`, `CALENDAR_IDS`; `user:` (or the `Dockerfile.api` uid) aligned with
    the worker's `appuser` uid — document `docker compose exec fitbit-fetch-data id -u` and
    the `API_UID` env default. `read_only: true` stays; the mount is the only writable path.
  - Done when: tests: `connect` 401 without bearer, URL contains `state`, read-only scope and
    the redirect URI; `callback` bad/expired/replayed state → 400 without details; success
    writes the token file via a mocked exchange and the response contains no token text;
    503 when unconfigured; secret never appears in any response. Docs: connect walkthrough
    (`curl -H "Authorization: Bearer $AI_API_TOKEN" http://127.0.0.1:8000/api/calendar/connect`,
    open the URL, land on the callback). `[manual-verify]` uid alignment in C5.3.
  - Notes: done: API `Settings` gains `calendar_client_id` / `calendar_client_secret`
    (`GOOGLE_*` fallback, `repr=False`, in the `configure_logging` secrets tuple),
    `calendar_token_file_path`, `calendar_redirect_uri` and `calendar_ids`, all optional.
    `app/api/calendar_connect.py` holds `CalendarConnectService`: `begin()` mints a
    `secrets.token_urlsafe(32)` nonce (10-minute TTL, at most 10 pending, oldest evicted) and
    returns the D2 read-only authorization URL; `complete(state, code, error)` rejects an
    unknown, expired, replayed or Google-denied response with `400 CALENDAR_CONNECT_REJECTED`
    before any exchange, then exchanges the code and saves through
    `GoogleCalendarTokenManager._save` (atomic, `0600`) via a small `CalendarTokenSettings`
    adapter — the API `Settings` stays free of collector fields. Unconfigured → `503
    CALENDAR_NOT_CONFIGURED` on both endpoints. `app/api/routes/calendar.py` adds `GET
    /api/calendar/connect` (bearer) and the bearer-less `GET /api/calendar/callback` (plain
    text, no token, code or secret in any response); `app/api/main.py` builds the service in
    the lifespan with its session closed on the same `ExitStack`. Compose gives `ai-api` the
    read-write `./tokens` mount, the calendar env vars and `user: "${API_UID:-10001}"`, with
    `Dockerfile.api` taking a matching `ARG API_UID`; `docker compose config --quiet` passes.
    207 → 213 tests. The cloud image still needs `pip install cffi` on top of
    `requirements-dev.txt` (see C1.1).

### C2 Read API: events with vitals

- [x] **C2.1 Read layer: buckets + calendar tags + raw route** — blocked by: C1.5
  - Files: `app/storage/influx/queries.py`, `app/api/health_service.py`, `docs/HEALTH_API.md`,
    `tests/test_health_routes.py`, `tests/test_ai_influx.py`.
  - Do: `InfluxService.query(measurement, start, end, bucket="1h")`; intraday `GROUP BY
    time(<bucket>)`; validate bucket against `^([1-9][0-9]{0,2}m|1h)$`. For `Calendar Events`
    the identity `WHERE` is `UserId = <user_id> AND Provider = 'google_calendar'` (no
    `DeviceId`, D4) and the select list appends tag columns `CalendarId`, `EventId` (same as
    `ActivityName`). `latest_calendar_event()` → newest stored event row for the person
    (mirrors `latest_device_observation`). `HEALTH_MEASUREMENTS["calendar"] =
    ("Calendar Events",)` → `GET /api/health/calendar` exists through the existing route factory.
  - Done when: SQL assertions for bucket, calendar identity and tag columns; route test
    parametrization includes `calendar`; docs table row.
  - Notes: done: `InfluxService.query` takes `bucket="1h"`, validated against
    `[1-9][0-9]{0,2}m|1h` before anything is sent, and drives `GROUP BY time(<bucket>)` for the
    intraday measurements (unchanged hourly default, so existing callers keep their SQL). A new
    `_identity(measurement)` helper builds the `WHERE` identity once: `Calendar Events` filters on
    `UserId` + `Provider = 'google_calendar'` only (no `DeviceId`, D4) and appends the tag columns
    `CalendarId`, `EventId` to the stored field list, exactly as `Activity Records` appends
    `ActivityName`. `latest_calendar_event()` and `latest_device_observation()` now share a
    `_latest()` helper (`ORDER BY time DESC LIMIT 1`, newest row across tag sets, redacted
    `DataUnavailable` on failure). `HEALTH_MEASUREMENTS["calendar"] = ("Calendar Events",)` gives
    `GET /api/health/calendar` through the existing route factory; `docs/HEALTH_API.md` gains the
    route row plus the person-keyed identity note. 213 → 223 tests. The cloud image still needs
    `pip install cffi` on top of `requirements-dev.txt` (see C1.1).
- [x] **C2.2 Pure per-event vitals** — blocked by: none
  - Files: `app/calendar/__init__.py`, `app/calendar/vitals.py`, `tests/test_calendar_vitals.py`.
  - Do: `bucket_minutes(days)` (D6). `usable_events(rows)`: dedupe by `EventId` keeping max
    `updated`; drop `cancelled`, `isAllDay`, `transparent`, duration < `MIN_EVENT_MINUTES`.
    `event_vitals(event, hr_buckets, step_buckets, workouts, resting_hr)`: a bucket belongs
    to a window when its midpoint is inside it; `mean_hr` = count-weighted mean, `max_hr`,
    `sample_count`, `coverage_pct` (buckets with samples ÷ expected), `hr_vs_resting_pct`,
    `steps`, `steps_per_minute`, `movement_confounded` (`steps_per_minute >
    MOVEMENT_STEPS_PER_MINUTE` or overlaps an `Activity Records` row), `pre30_mean_hr`,
    `post30_mean_hr`, `recovery_delta = post30 − mean`. Coverage < `MIN_COVERAGE_PCT` →
    `None` plus a note string. Knobs as module constants with `# ponytail:` comments:
    `MIN_EVENT_MINUTES=10`, `MOVEMENT_STEPS_PER_MINUTE=20`, `MIN_COVERAGE_PCT=50`,
    `CONTEXT_MINUTES=30`.
  - Done when: tests on synthetic buckets: exact weighted mean, boundary buckets, confound
    flag both ways, low coverage → `None`, dedupe keeps the newest row and drops cancelled.
  - Notes: done: `app/calendar/vitals.py` (new pure package, no I/O — it reuses `number` and
    `percent` from `app.ai.analytics` and nothing else from the app) adds `bucket_minutes(days)`
    (7d → 1m, 30d → 3m, 90d → 7m, every period ≤ 190 d under the 20 000-row cap),
    `usable_events(rows)` (dedupe by `EventId` keeping the newest `updated` **before** filtering,
    so a newer cancellation removes the event instead of resurrecting its stale row; then drops
    cancelled, all-day, `transparent` and sub-`MIN_EVENT_MINUTES` events, ordered by start) and
    `event_vitals(event, hr_buckets, step_buckets, workouts, resting_hr, bucket_minutes=1)`
    returning `(vitals | None, notes)`. A bucket counts for the window holding its midpoint —
    hence the extra `bucket_minutes` argument, which the read layer's `GROUP BY time()` width
    supplies and cannot be inferred from a row. `coverage_pct` = covered ÷ expected buckets
    (capped at 100); below `MIN_COVERAGE_PCT` the vitals are `None` plus the coverage note.
    `steps` stays `None` when no step bucket overlaps (no data ≠ zero steps), so
    `movement_confounded` then rests on an overlapping `Activity Records` row alone. Event and
    workout spans share one `startTime`/`endTime`-then-duration helper. Knob constants carry the
    `# ponytail:` comments the item asked for. 223 → 237 tests. The cloud image still needs
    `pip install cffi` on top of `requirements-dev.txt` (see C1.1).
- [x] **C2.3 `GET /api/calendar/events`** — blocked by: C2.1, C2.2
  - Files: `app/api/schemas/calendar.py`, `app/api/calendar_service.py`,
    `app/api/routes/calendar.py`, `app/api/main.py` (router + `app.state.calendar`),
    `app/api/dependencies.py`, `docs/CALENDAR_SYNC.md` (API section), `tests/test_calendar_routes.py`.
  - Do: bearer auth, `HealthQuery` reuse, period rules identical to health routes
    (`_interval` logic — extract to a shared helper rather than copying). Service fetches
    `Calendar Events`, `HeartRate_Intraday` + `Steps_Intraday` with `bucket_minutes(days)`,
    `RestingHR`, `Activity Records`; baseline = `RestingHR` of the event's local day, else
    nearest within 7 days, else `None`. Strict response: `start`, `end`, `timezone`,
    `bucket_minutes`, `events[]` {`event_id`, `calendar_id`, `summary`, `start`, `end`,
    `duration_minutes`, `attendees`, `is_organizer`, `response_status`, `event_type`,
    `recurring_event_id`, `vitals | null`, `notes[]`}. Errors reuse health codes
    (`INVALID_HEALTH_PERIOD` 422, `HEALTH_QUERY_TOO_LARGE` 422, `DATA_SERVICE_UNAVAILABLE` 503).
  - Done when: TestClient tests: 401, empty period, vitals computed from mocked rows, unknown
    query param → 422, no secret text in errors.
  - Notes: done: the period rules moved out of `HealthReadService._interval` into
    `app.api.health_service.resolve_interval(settings, clock, period)`, which now also returns
    the day count the calendar route needs for `bucket_minutes(days)`; the health service calls
    it and is otherwise untouched. `app/api/calendar_service.py` adds `CalendarReadService`
    (`app.state.calendar`, `get_calendar` dependency): it reads `Calendar Events` for the period,
    keeps `usable_events` only and — just for those — reads `HeartRate_Intraday` and
    `Steps_Intraday` at `bucket=<bucket_minutes(days)>m`, `Activity Records` and `RestingHR`,
    padding the vitals reads by `CONTEXT_MINUTES` at both ends (worst case 83 d → 19 930 of the
    20 000 rows, so the cap still holds) and the `RestingHR` read by
    `BASELINE_MAX_AGE_DAYS = 7` days back. The baseline is the resting rate of the event's local
    day, else the nearest within seven days, else `None` (which `event_vitals` reports as a
    note). A period with no readable event issues no vitals reads at all. `GET
    /api/calendar/events` reuses `HealthQuery` (so an unknown parameter is still 422) and the
    health error codes; `app/api/schemas/calendar.py` holds the strict (`extra=forbid`,
    `strict=True`) `CalendarEventsResponse` / `CalendarEvent` / `EventVitals`, so a drift between
    `event_vitals` and the contract fails loudly instead of leaking a field.
    `docs/CALENDAR_SYNC.md` gains an Endpoints section. 237 → 244 tests. The cloud image still
    needs `pip install cffi` on top of `requirements-dev.txt` (see C1.1).
- [x] **C2.4 Connection status + disconnect** — blocked by: C1.8, C2.1
  - Files: `app/api/routes/calendar.py`, `app/api/calendar_connect.py`,
    `app/api/schemas/calendar.py`, `docs/CALENDAR_SYNC.md`, `tests/test_calendar_connect_routes.py`.
  - Do: `GET /api/calendar/status` (bearer) → `{connected: bool (token file exists with a
    refresh token), configured: bool, calendar_ids, token_saved_at | null, last_event_start |
    null (from latest_calendar_event), redirect_uri}`. `DELETE /api/calendar/connection`
    (bearer) → best-effort `revoke` of the refresh token, delete the file, 204; 404
    `CALENDAR_NOT_CONNECTED` when no file. Worker notices the deletion on its next cycle (D2).
  - Done when: tests: status reflects file presence and Influx row; disconnect deletes the
    file, calls revoke once, is idempotent-safe (second call 404); no secrets in responses.
  - Notes: done: `CalendarConnectService` gains `status(repository)` and `disconnect()`.
    `status` reads the token file itself (`connected` = a non-empty `refresh_token` in it,
    `token_saved_at` = its `saved_at_utc`) and never raises: it answers `configured: false`
    on an unconfigured server instead of `503`, and reports `last_event_start: null` — from
    `latest_calendar_event()`'s point time, the event start per the data contract — when
    nothing is synced yet or InfluxDB is unreadable, so the connection state never depends on
    the store. `disconnect()` is `404 CALENDAR_NOT_CONNECTED` without a token file, otherwise
    revokes the refresh token best effort (a refusal still disconnects) and unlinks the file;
    the worker notices on its next cycle (D2). `GET /api/calendar/status` (bearer, strict
    `CalendarStatusResponse`) takes the repository through the existing `get_influx`
    dependency, so `app/api/main.py` is untouched, and `DELETE /api/calendar/connection`
    (bearer) answers `204` with no body. Neither response can carry a token or the client
    secret. `docs/CALENDAR_SYNC.md` documents both in the connect table. 244 → 247 tests.
    The cloud image still needs `pip install cffi` on top of `requirements-dev.txt` (see C1.1).

### C3 Deterministic insights

- [x] **C3.1 Daily load + correlations** — blocked by: C2.2
  - Files: `app/calendar/insights.py`, `tests/test_calendar_insights.py`.
  - Do: `daily_load(events, zone)` per local date: `event_count`, `meeting_count`
    (attendees ≥ 1), `meeting_minutes`, `event_minutes`, `back_to_back_count` (gap ≤ 5 min),
    `first_event_hour`, `last_event_hour`. `correlate(daily_load, daily_metrics)` for
    `resting_hr`, `hrv_rmssd`, `sleep_hours`, `sleep_efficiency`, `steps`, `active_minutes`,
    `breathing_rate`, `skin_temperature_deviation`: Pearson `r` of `meeting_minutes` vs the
    same-day value and vs the next-day value (sleep, HRV, resting HR are next-morning
    measurements) via `statistics.correlation`; `n < 10` → `insufficient_data`. Tercile
    comparison: metric mean on top-third vs bottom-third meeting days (each ≥ 4 days) →
    `difference`, `percent`. Daily metric series come from
    `app.ai.analytics.analyze()["metrics"][name]["daily"]` — reuse, never re-derive.
  - Done when: tests with 30 synthetic days: known `r`, next-day shift, insufficient-data
    path, tercile math.
  - Notes: done: `app/calendar/insights.py` (pure, same rule as `vitals.py` — it reuses
    `average`/`number`/`percent` from `app.ai.analytics` and `event_window` from
    `app.calendar.vitals`, nothing else) adds `daily_load(events, zone)` keyed by ISO local
    date like an `analyze()` series: `event_count`, `meeting_count` /
    `meeting_minutes` (`attendees >= MIN_MEETING_ATTENDEES`, an absent count is a personal
    block), `event_minutes`, `back_to_back_count` (gap `<= BACK_TO_BACK_GAP_MINUTES`, so
    overlaps count too) and `first_event_hour` / `last_event_hour` as fractional local hours
    of the first and last **start**. A day is the local date of the event's start, so a
    23:30 UTC event belongs to the next Berlin day. `daily_series(metrics)` lifts
    `analyze()["metrics"][name]["daily"]` for the eight correlated metrics (never
    re-derived), and `correlate` / `tercile_comparison` share one pairing helper, both
    reporting `same_day` and `next_day` per metric — sleep, HRV and resting heart rate are
    next-morning measurements (D7), and a tercile on same-day sleep would compare a busy day
    against the night before it. `correlate` → `{r, n, insufficient_data}` with
    `n < MIN_CORRELATION_DAYS` short-circuited and a metric that never moves reported as
    `r: null` (`statistics.correlation` refuses a constant series). `tercile_comparison`
    sorts the pairs by meeting minutes, takes `len // 3` from each end (both thirds' metric
    and meeting-minute means, `difference`, `percent`) and reports `insufficient_data` below
    `MIN_TERCILE_DAYS`; both branches carry the same keys, so the C3.3 schema cannot drift.
    Knob constants carry `# ponytail:` comments. 247 → 261 tests. The cloud image still needs
    `pip install cffi` on top of `requirements-dev.txt` (see C1.1).
- [x] **C3.2 Series, time-of-day and top events** — blocked by: C2.2
  - Files: `app/calendar/insights.py`, `tests/test_calendar_insights.py`.
  - Do: `series_summary(events_with_vitals)`: group by `recurring_event_id`, else normalized
    summary (lowercase, whitespace collapsed); per group `title`, `occurrences`, `with_vitals`,
    `mean_hr_vs_resting_pct`, `mean_recovery_delta`, `confounded_count`; rank by elevation
    among groups with ≥ 3 usable occurrences. `time_of_day(...)`: morning < 12, afternoon
    12–17, evening ≥ 17 → mean elevation + `n`. `top_events(...)`: 5 highest non-confounded.
  - Done when: tests: grouping fallback, rank threshold, buckets, confounded excluded.
  - Notes: done: `app/calendar/insights.py` (still pure) adds `series_summary(events)`,
    `time_of_day(events, zone)` and `top_events(events, limit=TOP_EVENT_COUNT)`. All three take
    the same input: stored `Calendar Events` rows, each carrying the `event_vitals` dict its
    reader computed under a `"vitals"` key (`None` when the buckets did not cover the event) —
    the shape `CalendarReadService._events` already holds per event, so C3.3 passes rows
    straight through without a second vitals pass. Rows without a usable window are skipped
    exactly as in `daily_load`. Grouping is `recurringEventId`, else the whitespace-collapsed
    lowercase summary, else the event id alone, so untitled one-offs never clump together;
    a group reports `title` (the first occurrence's summary, whitespace collapsed),
    `occurrences`, `with_vitals`, `mean_hr_vs_resting_pct`, `mean_recovery_delta` and
    `confounded_count`. Groups with `with_vitals >= MIN_SERIES_OCCURRENCES = 3` and a numeric
    mean rank first by elevation (descending); the rest trail by how often they recur, so the
    C3.3 "top 10" slice is always the ranked ones first — confounded occurrences stay in the
    mean and are counted beside it, since one walking instance should not silently reshape a
    series. `time_of_day` buckets on the **local** start hour (`morning < 12`, `afternoon`
    12–17, `evening >= 17`) and reports `mean_hr_vs_resting_pct` plus the `n` backing it, so a
    bucket without a single elevation reads `{null, 0}` rather than disappearing. `top_events`
    drops events without vitals, without an elevation or flagged `movement_confounded`, then
    returns the five steepest (ties by start) as `event_id`, `title`, `start` (aware UTC
    datetime, ready for the strict `AwareDatetime` schema), `duration_minutes`, `attendees`,
    `mean_hr`, `hr_vs_resting_pct`, `recovery_delta`. Knob constants carry `# ponytail:`
    comments. 261 → 272 tests. The cloud image still needs `pip install cffi` on top of
    `requirements-dev.txt` (see C1.1).
- [x] **C3.3 `GET /api/calendar/insights`** — blocked by: C2.3, C3.1, C3.2
  - Files: `app/api/routes/calendar.py`, `app/api/calendar_service.py`,
    `app/api/schemas/calendar.py`, `docs/CALENDAR_SYNC.md`, `tests/test_calendar_routes.py`.
  - Do: `?period=30d` (default `AI_DEFAULT_ANALYSIS_DAYS`, max `AI_MAX_ANALYSIS_DAYS`).
    Response: `period`, `days_with_events`, `daily_load[]` (last 14 days), `correlations{}`,
    `tercile_comparison{}`, `series[]` (top 10), `time_of_day{}`, `top_events[]`, `caveats[]`
    (fixed strings: HR elevation is a stress proxy, not a measurement; correlation is not
    causation; movement, caffeine, illness confound HR; coverage gaps listed).
  - Done when: TestClient tests incl. empty data → 200 with empty sections; docs section.
  - Notes: done: `CalendarReadService._events` split into `_readings` (stored rows carrying the
    `event_vitals` dict and notes its reader computed) and the response mapping, so
    `GET /api/calendar/insights` runs `daily_load`, `series_summary`, `time_of_day` and
    `top_events` over exactly the rows `/api/calendar/events` already builds — one vitals pass,
    no second read. `CalendarReadService.insights(period)` reuses `resolve_interval` (same period
    rules, same health error codes) and takes the correlated daily series from
    `analyze(fetch(INSIGHT_MEASUREMENTS, window.query_start, window.now), Window(days, ...))`,
    never re-deriving them (C3.1); a period without a readable event issues no metric read at all
    and answers `200` with empty sections. The response is the strict
    `CalendarInsightsResponse`: `period` (`start`, `end`, `timezone`, `days`, `bucket_minutes`),
    `days_with_events`, `daily_load[]` (the last `DAILY_LOAD_DAYS = 14` days with events),
    `correlations{}` and `tercile_comparison{}` (both `same_day` + `next_day` per metric, in
    separate `ShiftedCorrelation` / `ShiftedTerciles` models so the two cannot drift into each
    other), `series[]` (top 10), `time_of_day{}`, `top_events[]` and `caveats[]` — three fixed
    strings plus a count of the events heart rate could not cover. `docs/CALENDAR_SYNC.md` gains
    the endpoint row and a field table. 272 → 277 tests. The cloud image still needs
    `pip install cffi` on top of `requirements-dev.txt` (see C1.1).

### C4 Gemini

- [ ] **C4.1 Calendar focus category and context** — blocked by: C3.3
  - Files: `app/api/schemas/ai.py` (`Category` + `"calendar"`), `app/ai/context.py`
    (`GROUPS`, `KEYWORDS`, `PRIMARY`, calendar section), `app/ai/service.py` (when
    `"calendar"` in focus: compute insights through the calendar service and inject
    `context["calendar"]`), `app/ai/validator.py` (`METRIC_TERMS`
    `\b(?:meeting|calendar|event)s?\b` → `{"calendar_load", "calendar_series"}`),
    `app/ai/prompts/health_analysis.txt` (+1 line: calendar HR figures are a proxy,
    confounded by movement, never a stress diagnosis), `app/core/config.py` (`Settings.
    calendar_ai_include_titles` from `CALENDAR_AI_INCLUDE_TITLES`, default true),
    `tests/test_ai_context.py`, `tests/test_ai_gemini.py`.
  - Do: `GROUPS["calendar"] = {"Calendar Events", "HeartRate_Intraday", "Steps_Intraday",
    "RestingHR", "HRV", "Sleep Summary"}`; `KEYWORDS["calendar"] =
    r"meeting|calendar|event|appointment|busy day|schedule"`; `PRIMARY["calendar"] =
    {"Calendar Events"}` (no events → `INSUFFICIENT_DATA`). Context: load summary (mean
    meeting minutes/day, busiest weekday), correlations with `n ≥ 10` only, top 5 series
    (titles ≤ 80 chars or `series-N` when titles are off), `time_of_day`, caveats. Evidence
    keys `calendar_load`, `calendar_series` appended when present. Cache key already covers
    context.
  - Done when: tests: focus `calendar` builds the section; `classify("how do meetings affect
    my sleep")` → `calendar` + `sleep`; titles toggle; validator accepts a supported claim and
    rejects an unsupported "meetings" claim.
  - Notes:
- [ ] **C4.2 `POST /api/ai/calendar` + docs** — blocked by: C4.1
  - Files: `app/api/routes/ai.py` (add `"calendar"` to the specialized loop),
    `tests/test_api_structure.py`, `tests/test_ai_routes.py`, `docs/AI_BACKEND.md`
    (table row + limits bullet), `docs/CALENDAR_SYNC.md`.
  - Done when: path in OpenAPI; route test with mocked Gemini; docs updated.
  - Notes:

### C5 Ops and docs

- [ ] **C5.1 Grafana annotations** — blocked by: C1.7
  - Files: `docs/CALENDAR_SYNC.md` (Grafana section).
  - Do: document an InfluxQL annotation query overlaying events on the heart-rate panel:
    `SELECT "summary" AS text, "EventId" AS tags FROM "Calendar Events" WHERE $timeFilter AND
    "status" = 'confirmed' AND "isAllDay" = false`, with the datasource field mapping steps.
    Dashboard JSON export only if a live Grafana is available (`[manual]` otherwise).
  - Done when: section present; query verified on the local stack or marked unverified.
  - Notes:
- [ ] **C5.2 Docs consistency pass** — blocked by: C2.4, C4.2
  - Files: `README.md`, `docs/CALENDAR_SYNC.md`, `docs/influxdb_schema.md`, `docs/HEALTH_API.md`,
    `docs/AI_BACKEND.md`, `.env.example`, `compose.yml`.
  - Do: every calendar env var in code appears in `.env.example`, `compose.yml` and the doc's
    env table; every new route appears in a docs table; `docs/CALENDAR_SYNC.md` has Setup,
    Env, Sync policy, Schema, Endpoints, Privacy, Limits, Troubleshooting. `docs/refactor_contracts.md`
    untouched.
  - Done when: grep of `CALENDAR_` across code and docs matches; no contradictions.
  - Notes:
- [ ] **C5.3 Live verification on the Docker stack** `[manual]` — blocked by: C5.2
  - Do: `docker compose build fitbit-fetch-data ai-api`; set `CALENDAR_SYNC_ENABLED=true`;
    `docker compose up -d`; verify uid alignment (`docker compose exec fitbit-fetch-data id -u`
    equals the `ai-api` user); connect through `GET /api/calendar/connect` in a browser
    session; `GET /api/calendar/status` shows `connected: true`; within 15 minutes the worker
    logs a calendar sync and `SHOW MEASUREMENTS` lists `Calendar Events`; call
    `/api/health/calendar?period=2d`, `/api/calendar/events?period=7d`,
    `/api/calendar/insights?period=30d`, `/api/ai/calendar`; then `DELETE
    /api/calendar/connection` and confirm the worker logs *not connected* without exiting.
  - Done when: all calls return the expected status with real data; findings recorded in Notes.
  - Notes:

### C6 Optional real stress score

- [ ] **C6.1 Google Health `Stress Score` measurement** — blocked by: C0.2 (`available`), C3.1
  - Files: `app/providers/google_health/vitals.py`, `app/providers/google_health/provider.py`
    (`_vitals` group), `app/domain/measurements.py`, `docs/influxdb_schema.md`,
    `app/ai/analytics.py` (`FIELDS["stress_score"]`, category `recovery`),
    `app/calendar/insights.py` (add `stress_score` to the correlation list),
    `app/ai/validator.py` (`\bstress\b` → `{"stress_score"}`), tests + fixture.
  - Do: daily measurement `Stress Score` with the fields the data type exposes (`value` float
    at minimum), local-day boundary timestamp, provider-only (Fitbit provider returns nothing;
    documented gap). Pure mapper, parity fixture, provider test.
  - Done when: tests green; docs list the measurement; insights correlate meeting load vs stress.
    If C0.2 says `unavailable`: tick with Notes `unavailable`, keep D7 wording in docs.
  - Notes:

## Dependency order

```text
C1.1 → C1.2 → C1.3 → C1.8 ┐
C1.1 → C1.4 ┐             ├→ C2.4 ┐
C1.5 ───────┼→ C1.6 → C1.7 → C5.1 │
C1.2 ───────┘             │       │
C1.5 → C2.1 ──────────────┘       │
C2.2 ───────┼→ C2.3 ┐             │
C2.2 → C3.1 ┐       ├→ C3.3 → C4.1 → C4.2 → C5.2 → C5.3 [manual]
C2.2 → C3.2 ┴───────┘
C0.2 [manual] + C3.1 → C6.1
```

Parallel-safe starts: C1.1, C1.5, C2.2.

## Routine protocol

Paste this as the routine prompt (`/schedule`, repo
`https://github.com/IlyasBaratov/Fitbit-superset-backend`, suggested cron `0 */2 * * *`,
model `claude-sonnet-5` or stronger). Cloud runs have no Docker, no `.env`, no tokens; tests
mock everything.

```text
Run ONE iteration of the Google Calendar sync backlog for Fitbit-superset-backend.

Steps:
1. git fetch origin. Check out branch feature/calendar-sync (create from origin/main if it
   does not exist). pip install -r requirements-dev.txt.
2. Read docs/CALENDAR_SYNC_BACKLOG.md — the single source of truth. Read "Design decisions"
   and the data contract every run. Find the FIRST unchecked item that is not marked [manual]
   and whose "blocked by" items are all checked. If none: run `python -m pytest -q` twice,
   report, stop.
3. Read every file the item lists plus its tests, and the neighbouring modules it mirrors
   (providers/google_health, ingestion, api/health_service, ai/context). Follow existing
   patterns: pure mappers without infrastructure imports, frozen typed settings, strict
   pydantic models, no input(), no network or logging setup at import time, secrets never in
   error text. Python 3.10-compatible syntax (worker image).
4. Implement ONLY that item, test-first where a seam exists. Smallest diff that satisfies
   "Done when". No new dependencies. Do not change existing measurement contracts
   (docs/refactor_contracts.md) or existing routes.
5. Verify: `python -m pytest -q` must be fully green. If it cannot be made green, revert
   (`git checkout -- . && git clean -fd`), write the blocker under the item's Notes, commit
   only the backlog note, and stop. Never commit red.
6. Green: tick the checkbox, add `Notes: done <short summary>`, commit
   `feat(calendar): <item title>` with a short body and the trailer
   `Co-Authored-By: Claude <noreply@anthropic.com>`, push the branch. If no open PR exists
   for feature/calendar-sync, open a draft PR titled "Google Calendar sync" (gh pr create
   --draft --base main); otherwise leave the existing PR alone.

Rules: one item per run; never commit secrets, .env or token files; do not touch unrelated
code; do not tick [manual] items; if a design decision in the backlog is wrong, add a
"Design note" under the item and stop instead of improvising.
```

## Confirmed decisions (2026-09-07)

- Claude Code cloud routines consume this file one item per run (routine protocol above).
- Calendar access is read-only. Writing HR summaries back into events is out of scope.
- A person connects their own Google Calendar through the API (D13); calendar data is keyed
  by the person (`UserId`), not by the wearable device (D4). One person per stack.
- "Stress" = HR-elevation proxy plus next-day HRV/sleep effects until C0.2 proves a real
  stress data type exists.

## Later / not planned unless asked

- Write-back annotations to Google Calendar (needs `calendar.events` write scope).
- `events.watch` push notifications (needs a public HTTPS endpoint; polling suffices).
- `syncToken` incremental sync (incompatible with time windows; quota is not a concern at
  ~100 requests/day).
- InfluxDB 2.x/3.x read support in the worker.
- Working-hours / focus-block analysis, meeting-free day detection.

## Test baseline

`python -m pytest -q` on `main` before this feature: 141 passed. Every tick must keep
the count monotonic.
