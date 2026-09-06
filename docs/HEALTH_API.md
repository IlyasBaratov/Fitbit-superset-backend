# Health read API

All routes require the existing `Authorization: Bearer <AI_API_TOKEN>` header. Identity always comes from USER_ID, HEALTH_API_PROVIDER and DEVICE_ID; clients cannot override it. These reads do not call Gemini.

| GET route | Measurements |
| --- | --- |
| /api/health/heart-rate | HeartRate_Intraday, RestingHR, HRV, HR zones |
| /api/health/sleep | Sleep Summary, Sleep Levels |
| /api/health/activity | Steps_Intraday, Total Steps, calories, distance, Activity Minutes |
| /api/health/workouts | Activity Records |
| /api/health/spo2 | SPO2, SPO2_Intraday |
| /api/health/body | height, weight, bmi |
| /api/devices | Latest Device Metadata and DeviceBatteryLevel observations |

Health routes accept `?period=7d`; omitted periods use AI_DEFAULT_ANALYSIS_DAYS. Maximum is AI_MAX_ANALYSIS_DAYS (at most 90). The interval runs from midnight in the configured timezone on the first included day through now, with an inclusive start and exclusive end. Unknown query parameters are rejected. Devices accepts no query parameters and returns the latest stored observations regardless of age, including their timestamps.

Health responses contain `start`, `end` (UTC timestamps), `timezone`, and `series`. Each series has `measurement`, `resolution` (`hourly` or `stored`), and `rows`; each row contains a UTC `timestamp` and `fields`. Intraday fields are sum, count, min and max. Other measurements retain the selected stored fields and identity-related activity/sleep fields. Absent measurements have empty row lists; no synthetic data is returned.

Device responses contain `device_id`, `provider`, and `observations`. Each observation contains `measurement`, `timestamp`, and available `fields`. Missing battery telemetry produces no battery observation.

Errors: 401 for missing/invalid bearer token, 422 for invalid parameters or more than 20,000 rows per measurement, and 503 for unavailable/invalid stored data. Error bodies use the existing error/message envelope for application errors; FastAPI parameter validation retains its standard detail response. Use a shorter period when results exceed the limit. Existing AI endpoints and their comparison windows are unchanged.
