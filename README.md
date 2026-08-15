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

- Python 3.14+ (matching the project configuration)
- Access to a Fitbit app or Google Cloud OAuth client
- A running InfluxDB instance or compatible endpoint
- A valid `.env` file with your credentials and database settings

## Setup

1. Copy the sample configuration:

   ```bash
   cp .env.example .env
   ```

2. Update the values in `.env` with your real credentials and server details.
3. Make sure `FITBIT_LOG_FILE_PATH` and `TOKEN_FILE_PATH` point to writable files.
4. Set `HEALTH_API_PROVIDER` to either `fitbit` or `google`.
5. Configure the correct InfluxDB version and connection settings.

## Required environment variables

The project expects values similar to these:

```env
HEALTH_API_PROVIDER=fitbit
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

For InfluxDB 2.x or 3.x, configure the matching bucket, org, token, and URL values instead of the 1.x variables.

## Running the script

```bash
python main.py
```

If you are using `uv` in this project, you can also run:

```bash
uv run python main.py
```

## Notes

- The script writes logs to the configured log file and stdout.
- `DRY_RUN_MODE=true` skips database writes while still allowing the code to run.
- If you want to restrict the fetch window, set `MANUAL_START_DATE` and `MANUAL_END_DATE` explicitly.
- For Fitbit, make sure the app type is set to personal to access intraday data correctly.

## License

This repository does not currently declare a license in the project metadata. Check the repository root and upstream project documentation for any licensing terms before redistribution or commercial use.
