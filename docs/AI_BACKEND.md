# Wearable AI backend

The API implements [the integration specification](Fitbit_AI_API_Documentation.md) as an independent, read-only FastAPI service. The existing collector continues to write data unchanged. No frontend is included.

## Configuration and startup

Set these values in the ignored `.env` file:

```dotenv
GEMINI_API_KEY=your-private-Gemini-key
MODEL_NAME=your-selected-model
AI_API_TOKEN=your-separate-random-token-at-least-32-characters
AI_DEFAULT_ANALYSIS_DAYS=7
AI_MAX_ANALYSIS_DAYS=90
GEMINI_RETRY_ATTEMPTS=3
GEMINI_RETRY_MAX_ELAPSED_MS=55000
# Optional fallback:
GEMINI_FALLBACK_MODEL=
```

`MODEL_NAME` takes precedence over `GEMINI_MODEL`. Model availability, quota, and structured-output support must match your Gemini account. The API uses Google's `google-genai` SDK and Generate Content structured JSON output, validated with Pydantic. See [Google's documentation](https://ai.google.dev/gemini-api/docs/generate-content/structured-output).

Generate a personal token once, if one has not already been configured, by running this Python snippet from the project root. It writes directly to `.env` without printing the token:

```python
from pathlib import Path
import secrets
from dotenv import dotenv_values
path = Path('.env')
if not dotenv_values(path).get('AI_API_TOKEN'):
    with path.open('a') as stream:
        stream.write('\nAI_API_TOKEN=' + secrets.token_urlsafe(48) + '\n')
```

Use the collector's `USER_ID` (default `user_001`), `HEALTH_API_PROVIDER`, and `DEVICE_ID` (default `fitbit_air_001`). Every query filters all three; changing these settings selects different series. Untagged legacy data is excluded. There is no client-supplied user identity or multiuser login.

`LOCAL_TIMEZONE` selects the calendar timezone. `Automatic` uses `TZ`, defaulting to `America/Los_Angeles`. The API targets the existing InfluxDB 1.x database via the existing `INFLUXDB_*` connection settings. It does not support the collector's 2.x/3.x targets.

```powershell
docker compose build ai-api
# Existing database already running: start only the API.
docker compose up -d --no-deps ai-api
docker compose ps ai-api
```

For a new stack, use `docker compose up -d ai-api` to start the database dependency too. The API runs as a non-root user with a read-only filesystem, no host data mounts, one worker, and port `127.0.0.1:8000`. It has `unless-stopped` restart behavior. Keep it localhost-bound unless you add an appropriate authenticated HTTPS deployment layer.

Local development:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

Stop the Docker API first if running locally on the same port. Local database access normally uses `INFLUXDB_HOST=localhost`; Compose sets it to `influxdb` inside the container. Missing API credentials or invalid timezone/day settings fail startup. `.env` is excluded from Git and Docker build context. Upstream failures are returned without credentials, raw payloads, or provider error text.

## API usage

Interactive OpenAPI documentation: `http://127.0.0.1:8000/docs`. Use its Authorize control with the personal API token. No CORS origins are enabled by default.

All AI routes require `Authorization: Bearer <AI_API_TOKEN>`. The bearer token is **not** the Gemini key.

| Method/path | Request | Purpose |
|---|---|---|
| `GET /health` | None; no authentication | Process/configuration liveness; does not call Gemini or InfluxDB |
| `POST /api/ai/test` | No body | Authenticated live Gemini connection check; consumes a small model call |
| `POST /api/ai/analyze` | `{"period":"7d","focus":["sleep","activity","recovery","workouts"]}` | Combined analysis |
| `POST /api/ai/sleep` | `{"period":"7d"}` | Sleep and supporting recovery measurements |
| `POST /api/ai/activity` | `{"period":"7d"}` | Steps, activity minutes, calories, distance, zones |
| `POST /api/ai/workouts` | `{"period":"7d"}` | Recorded workouts and supporting recovery data |
| `POST /api/ai/recovery` | `{"period":"7d"}` | Personal recovery baselines |
| `POST /api/ai/calendar` | `{"period":"30d"}` | Meeting load against heart rate, sleep and HRV (see docs/CALENDAR_SYNC.md) |
| `POST /api/ai/ask` | `{"period":"14d","question":"Am I walking more than last week?"}` | Locally classified natural-language questions |

All analysis routes require a JSON object; `{}` uses the configured default period. `/ask` requires a nonblank question of at most 2,000 characters. Periods use `Nd`, from `1d` through `90d`; the configured maximum may be smaller. Focus categories are `sleep`, `activity`, `workouts`, `recovery`, `cardiovascular`, `body`, and `calendar`. Specialized routes select their own focus; `/ask` classifies the question rather than using a supplied focus. The explicit/default period controls date selection; natural-language dates do not override it. Unknown request fields, including user identifiers, are rejected.

Example without printing either key:

```python
import requests
from dotenv import dotenv_values
cfg = dotenv_values('.env')
response = requests.post(
    'http://127.0.0.1:8000/api/ai/analyze',
    headers={'Authorization': 'Bearer ' + cfg['AI_API_TOKEN']},
    json={'period': '7d', 'focus': ['activity', 'recovery']},
    timeout=180,
)
response.raise_for_status()
print(response.json())
```

Responses contain `summary`, `score`, `insights`, `suggestions`, `warnings`, and `data_gaps`. Each insight/suggestion includes `based_on` entries referencing exact metric keys supplied to Gemini. Scores are nullable 0–100 model-generated wellness estimates, not clinical scores. The backend adds deterministic missing/partial-coverage notices even when the model omits them.

| HTTP status | Error code | Meaning |
|---|---|---|
| 401 | `UNAUTHORIZED` | Missing/incorrect token or unauthorized user |
| 422 | `INVALID_ANALYSIS_PERIOD` | Invalid period syntax or bounds |
| 422 | `INSUFFICIENT_DATA` | No relevant usable evidence in the requested period; Gemini is skipped |
| 422 | FastAPI `detail` validation errors | Invalid request fields or blank question |
| 429 | `AI_BUSY` | Another analysis/check is running; retry shortly |
| 503 | `DATA_SERVICE_UNAVAILABLE` | Database unavailable or query exceeds safe bounds |
| 503 | `AI_PROVIDER_TIMEOUT` | Gemini timed out before completing analysis |
| 503 | `AI_PROVIDER_OVERLOADED` | Gemini rate-limited or temporarily overloaded |
| 500 | `AI_PROVIDER_CONFIGURATION_ERROR` | Gemini credentials/model configuration is invalid |
| 503 | `AI_SERVICE_UNAVAILABLE` | Other Gemini availability failures |
| 502 | `INVALID_AI_OUTPUT` | Model output still invalid after one corrective retry |

Controlled service errors use `{"error":"CODE","message":"Explanation"}`. Failed responses are not cached.

## Analytics and limits

- Calendar ranges include today; today is explicitly partial. Seven/thirty-day baselines use preceding completed days. Missing dates are excluded, and coverage counts are supplied. Previous-period means cover the preceding equal-length period; the current mean excludes today.
- Daily snapshots use the latest observed value per local day. Intraday steps fill missing daily step totals; they are never added to an existing total. Heart-rate/oxygen hourly sums and sample counts produce weighted daily averages and min/max values.
- Sleep sessions are deduplicated and assigned to their local wake date. Stage durations supplement missing summary fields by session ID. Bed/wake consistency uses the longest main sleep per day and circular time differences around midnight. Missing or ambiguous timestamps are not fabricated.
- Workouts are deduplicated by activity ID. Durations remain seconds, distances kilometers, and weight kilograms. Heart-rate trends provide relative intensity context; no universal intensity thresholds are imposed. Missing workout days are described as days without records, not confirmed rest days. The collector fetches only the most recent 50 exercises, so historical workout coverage can be incomplete.
- Older classic Fitbit sleep labels may map restless sleep to REM in stored data. The API reports this limitation and does not rewrite those records. Sleep/other unavailable provider measurements remain gaps.
- Calendar analysis (`POST /api/ai/calendar`, or `calendar` in a `/analyze` focus) sends only the aggregates of the deterministic insights: meeting load averaged over the days that had events, correlations backed by at least 10 paired days, the top 5 recurring series, time-of-day elevation and the caveats. Event IDs, per-event rows and attendee identities are never sent; series titles are truncated to 80 characters, treated as untrusted text, and replaced by `series-N` when `CALENDAR_AI_INCLUDE_TITLES=false`. A period without a readable event answers `INSUFFICIENT_DATA`. An unreadable calendar drops the section instead of failing the analysis, so a calendar problem never breaks a health request. Calendar heart-rate figures are a movement-confounded proxy for stress, not a diagnosis.
- Optional GPS and device metadata are not queried. The model receives no account/device/session IDs or raw high-frequency records. Questions and activity labels are treated as untrusted text. Avoid including identifying details in questions: the question itself is sent to Gemini.
- Queries use at most 190 days and 20,000 returned rows per measurement, failing rather than silently truncating. Intraday series are aggregated hourly in InfluxDB first. Each database request has a 10-second timeout. Gemini calls use bounded transient retries (timeouts, 429, and 5xx) with exponential backoff + jitter, optional `Retry-After` support, and a max elapsed budget; invalid model output is still retried once with stricter instructions. An optional fallback Gemini model can be configured for transient primary-model failures. Daily details sent to Gemini are capped at the latest 14 observed days per metric while period statistics retain the full requested range. Prepared model payloads are limited to 120 KB and outputs to 50,000 characters.
- A single in-flight analysis/check per process bounds provider load. Successful analyses are cached in memory for five minutes, up to 128 entries. Cache identity includes user, provider/device, model, question/focus/period and prepared context. The database is queried before checking the model-response cache so new data invalidates it. Restarting clears cached health summaries.
- Validation checks JSON/schema, evidence references, score support/ranges, common unavailable-metric claims, and common diagnostic/treatment wording. These are conservative guardrails, not a guarantee that all generated statements are correct. This is wellness analytics, not diagnosis.

## Tests and operational checks

```powershell
.venv\Scripts\python.exe -m pytest -q
docker compose config --quiet
docker compose build ai-api
docker compose ps ai-api
```

Automated tests mock InfluxDB and Gemini: no credentials or paid calls are required. The existing collector tests remain part of the suite. `/health` verifies liveness; `/api/ai/test` verifies Gemini; an authenticated analysis verifies the full database-to-model path. A sleep-only request may correctly return `INSUFFICIENT_DATA` when the account lacks sleep records.

No frontend, schema migration, database writes, OAuth changes, or external deployment is part of this feature.
