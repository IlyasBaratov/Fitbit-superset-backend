# HealthAPI

A Python utility for collecting health and fitness data from Fitbit or Google Health and exporting it to InfluxDB.

## Overview

This project reads OAuth credentials, refreshes tokens as needed, fetches daily or intraday health metrics, and writes the results to an InfluxDB database. It supports:

- Fitbit data ingestion
- Google Health API ingestion
- InfluxDB 1.x, 2.x, and 3.x targets
- configurable date ranges and timezone handling
- dry-run mode for safe testing
- structured logging to a file and stdout

## Features

- Automatic token refresh for Fitbit and Google providers
- Support for provider selection via `HEALTH_API_PROVIDER`
- Device detection and timezone awareness
- Flexible start/end date configuration
- Optional automatic update range handling
- CSV/JSON-like downstream processing for health data points before database writes

## Prerequisites

- Docker Desktop with Docker Compose for the containerized stack
- Python 3.14+ for local development (matching `pyproject.toml`)
- Access to a Fitbit app or Google Cloud OAuth client
- A running InfluxDB instance or compatible endpoint
- A valid `.env` file with your credentials and database settings

The Docker image uses Python 3.10 from the published upstream Fitbit image. The
application is also syntax-checked against that runtime during Docker validation.

## Setup

1. Copy the sample configuration:

   ```bash
   cp .env.example .env
   ```

2. Update the values in `.env` with your real credentials and server details.
3. Make sure `FITBIT_LOG_FILE_PATH` and `TOKEN_FILE_PATH` point to writable files.
4. Set `HEALTH_API_PROVIDER` to either `fitbit` or `google`.
5. Set stable `USER_ID` and `DEVICE_ID` values. Do not change them between runs.
6. Configure the correct InfluxDB version and connection settings.

## Docker stack

The included `compose.yml` runs this repository's data collector, InfluxDB 1.11,
and Grafana:

| Service | Local endpoint |
| --- | --- |
| InfluxDB | `http://localhost:8086` |
| Grafana | `http://localhost:3000` |

Provider OAuth values are read from the project `.env`. Runtime logs, OAuth tokens, InfluxDB data, and Grafana data are persisted in ignored project folders.

The Compose collector uses `AUTO_DATE_RANGE=true` so its detached process does
not pause for manual date input. For a one-off manual backfill, override
`AUTO_DATE_RANGE=false` and provide both manual dates on the command line.

The collector image is built locally as `fitbit-superset-backend:latest`. Its
Dockerfile inherits from `thisisarpanghosh/fitbit-fetch-data:latest`, preserving
the upstream Fitbit packages and functionality while replacing the startup
command with this repository's `/app/main.py`.

Build the derived collector image:

```bash
docker compose build fitbit-fetch-data
```

Start the database and dashboard first:

```bash
docker compose up -d influxdb grafana
docker compose ps
```

On the first authorization, run the collector interactively and enter a valid
refresh token for the configured `HEALTH_API_PROVIDER` when prompted. The token
is saved under `./tokens` for later container runs:

```bash
docker compose run --rm fitbit-fetch-data
```

For a manual date range instead, run:

```bash
docker compose run --rm -e AUTO_DATE_RANGE=false -e MANUAL_START_DATE=2024-01-01 -e MANUAL_END_DATE=2024-01-31 fitbit-fetch-data
```

For a small recent Google Health synchronization, first set
`HEALTH_API_PROVIDER=google` in `.env`, then substitute a recent date:

```bash
docker compose run --rm -e AUTO_DATE_RANGE=false -e MANUAL_START_DATE=2026-08-20 -e MANUAL_END_DATE=2026-08-20 fitbit-fetch-data
```

After authorization succeeds, press Ctrl+C if the interactive run remains
scheduled, then start the complete stack:

```bash
docker compose up -d
```

Verify service state and follow individual logs:

```bash
docker compose ps
docker compose logs -f fitbit-fetch-data
docker compose logs -f influxdb
docker compose logs -f grafana
```

Verify that the derived image and running collector use this repository's
`/app/main.py`, rather than the upstream `/app/Fitbit_Fetch.py`:

```bash
docker image inspect fitbit-superset-backend:latest --format '{{json .Config.Cmd}} {{.Config.WorkingDir}} {{.Config.User}}'
docker inspect fitbit-fetch-data --format '{{json .Config.Cmd}} {{.Config.WorkingDir}} {{.Config.User}}'
docker compose exec fitbit-fetch-data sh -c 'tr "\0" " " </proc/1/cmdline; echo; readlink -f /proc/1/cwd'
docker compose exec fitbit-fetch-data sha256sum /app/main.py
```

The expected command is `["python","main.py"]`, the working directory is
`/app`, and the user is `appuser`. Compare the container checksum with
`sha256sum main.py` on Linux/macOS or `Get-FileHash .\main.py -Algorithm SHA256`
in PowerShell.

Useful lifecycle commands:

```bash
docker compose stop
docker compose down
```

`docker compose down` preserves the bind-mounted data folders. The supplied stack is configured for local development with unauthenticated InfluxDB access and default Grafana credentials; configure authentication before exposing either service outside the local machine.

## Required environment variables

The project expects values similar to these:

```env
HEALTH_API_PROVIDER=fitbit
USER_ID=user_001
DEVICE_ID=device_001
DEVICENAME=Charge5
CLIENT_ID=your_application_client_ID
CLIENT_SECRET=your_application_client_secret
FITBIT_LOG_FILE_PATH=/path/to/fitbit.log
TOKEN_FILE_PATH=/path/to/token_store.json
INFLUXDB_VERSION=1
INFLUXDB_HOST=localhost
INFLUXDB_PORT=8086
INFLUXDB_USERNAME=your_influxdb_username
INFLUXDB_PASSWORD=your_influxdb_password
INFLUXDB_DATABASE=your_influxdb_database_name
DRY_RUN_MODE=false
LOG_LEVEL=DEBUG
```

For Google Health support, also set the Google OAuth and API values:

```env
GOOGLE_CLIENT_ID=your_application_client_ID
GOOGLE_CLIENT_SECRET=your_application_client_secret
GOOGLE_HEALTH_BASE_URL=https://health.googleapis.com
GOOGLE_HEALTH_API_VERSION=v4
GOOGLE_OAUTH_TOKEN_URL=https://oauth2.googleapis.com/token
```

`USER_ID` and `DEVICE_ID` become InfluxDB tags and must remain stable. The
collector never generates random identifiers. OAuth tokens and the device
metadata deduplication state remain in the ignored `tokens/` bind mount.

For InfluxDB 2.x or 3.x, configure the matching bucket, org, token, and URL values instead of the 1.x variables.

## Running the script

```bash
python main.py
```

If you are using `uv` in this project, you can also run:

```bash
uv run python main.py
```

## InfluxDB measurements

Every point includes the `UserId`, `Provider`, `Device`, and `DeviceId` tags.
The collector writes these 22 measurements when the active provider and device
return the corresponding data:

`HeartRate_Intraday`, `RestingHR`, `HRV`, `HR zones`, `Steps_Intraday`,
`Total Steps`, `Activity Minutes`, `Activity Records`, `calories`, `distance`,
`GPS`, `Sleep Summary`, `Sleep Levels`, `SPO2`, `SPO2_Intraday`,
`BreathingRate`, `Skin Temperature Variation`, `weight`, `height`, `bmi`,
`DeviceBatteryLevel`, and `Device Metadata`.

Canonical units are BPM, seconds for exercise durations, kilometers for
distance, kilograms for weight, centimeters for `height.value`, percent for
SpO2/battery, and Celsius for temperature. Battery and GPS are optional and are
currently Fitbit-only. See [docs/influxdb_schema.md](docs/influxdb_schema.md)
for every field, type, unit, tag, timestamp rule, and compatibility decision.

Inspect stored data:

```bash
docker compose exec influxdb influx -database FitbitHealthStats -execute 'SHOW MEASUREMENTS'
docker compose exec influxdb influx -database FitbitHealthStats -execute 'SELECT * FROM "HeartRate_Intraday" ORDER BY time DESC LIMIT 5'
docker compose exec influxdb influx -database FitbitHealthStats -execute 'SELECT * FROM "height" ORDER BY time DESC LIMIT 5'
docker compose exec influxdb influx -database FitbitHealthStats -execute 'SELECT * FROM "Device Metadata" ORDER BY time DESC LIMIT 5'
docker compose exec influxdb influx -database FitbitHealthStats -execute 'SHOW FIELD KEYS FROM "RestingHR"'
```

## Tests

Unit tests use mocked provider payloads and do not require OAuth credentials:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

## Troubleshooting

- **No API data:** confirm the requested dates contain synced device data and
  inspect collector warnings for an empty dataset.
- **Invalid OAuth token:** run the collector interactively and provide a valid
  refresh token; the token file must match `HEALTH_API_PROVIDER`.
- **HTTP 403:** the account is missing permission for that metric. Other
  measurements continue; enable the required Google/Fitbit scope before retrying.
- **HTTP 404 or unsupported metric:** the provider/device does not expose that
  data type. The collector skips it without creating zeros.
- **InfluxDB connection failure:** confirm `influxdb` is healthy, the collector
  uses host `influxdb` and port `8086`, and database credentials match.
- **Field-type conflict:** inspect `SHOW FIELD KEYS FROM "measurement"`.
  `RestingHR.value` and `Total Steps.value` deliberately remain floats to match
  this repository's existing InfluxDB history; rewriting history requires a
  separate, explicit migration.

## Notes

- The script writes logs to the configured log file and stdout.
- `DRY_RUN_MODE=true` skips database writes while still allowing the code to run.
- If you want to restrict the fetch window, set `MANUAL_START_DATE` and `MANUAL_END_DATE` explicitly.
- For Fitbit, make sure the app type is set to personal to access intraday data correctly.

## License

This repository does not currently declare a license in the project metadata. Check the repository root and upstream project documentation for any licensing terms before redistribution or commercial use.
