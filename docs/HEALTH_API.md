# Health read API

All routes require the existing `Authorization: Bearer <AI_API_TOKEN>` header. Identity always comes from USER_ID, HEALTH_API_PROVIDER and DEVICE_ID; clients cannot override it. These reads do not call Gemini.

| GET route | Measurements |
| --- | --- |
| /api/health/heart-rate | HeartRate_Intraday, RestingHR, HRV, HR zones |
| /api/health/sleep | Sleep Summary, Sleep Levels, Sleep Respiratory Rate |
| /api/health/sleep-score | Derived main-sleep features and experimental score v0.1 |
| /api/health/activity | Steps_Intraday, Total Steps, calories, distance, Activity Minutes |
| /api/health/workouts | Activity Records |
| /api/health/spo2 | SPO2, SPO2_Intraday |
| /api/health/body | height, weight, bmi |
| /api/health/ecg | Electrocardiogram |
| /api/health/irn | Irregular Rhythm Notifications |
| /api/health/calendar | Calendar Events |
| /api/devices | Latest Device Metadata and DeviceBatteryLevel observations |

Google Health currently exposes sleep duration, stages, efficiency, short awakenings,
sleep respiratory statistics, and related nightly HRV, SpO2, breathing rate, and
temperature signals. It does not expose a Fitbit Sleep Score or Daily Readiness
Score data type. `efficiency` is the percentage of time in bed spent asleep; it
must not be labeled as Sleep Score. `/api/ai/recovery` analyzes available signals
but does not return an official Fitbit recovery or readiness score. The separate
`/api/health/sleep-score` route returns this backend's experimental emulator,
not an official Google/Fitbit score.

## Experimental Sleep Score emulator

`GET /api/health/sleep-score?period=7d` shares bearer authentication, server-side
identity, local-day period bounds and strict query validation with the other
health routes. Each requested local wake date has a `days` entry. The response
includes `model_version: sleep-score-emulator-v0.1`, `score` (nearest integer),
`raw_score` (before rounding), `insufficient_data`, `confidence`, raw components,
their calculation methods, flags and caveats. Raw second-level HR stays internal.

The configured `SLEEP_GOAL_MINUTES` defaults to **420** for the current owner's
calibration. `SLEEP_PROFILE_AGE` and `SLEEP_PROFILE_GENDER` are optional profile
inputs and have **no effect** on v0.1. Changing the goal changes the duration
shortfall; the fixed coefficients are not automatically refitted.

The deterministic v0.1 calculation is:

```text
D = max(0, SLEEP_GOAL_MINUTES - minutesAsleep)
T = minutes from session start to first Deep, REM, or qualified Stable Light start
R = shortAwakeningSeconds / 60, or sum of available short-awakening durations / 60
I = minutes in internal AWAKE stages strictly longer than 5 minutes
raw_score = clamp(100 - 0.163*D - 0.606*T - 0.123*R - 0.124*I, 0, 100)
score = nearest integer to raw_score
```

`sleep_efficiency = 100 * minutesAsleep / minutesInBed`, or null when the
denominator is unavailable or nonpositive. `full_awakenings_count` counts the
same qualifying internal AWAKE bouts used by interruptions; leading and trailing
awake stages are excluded. Efficiency, Sound Sleep and full awakenings have no
independent v0.1 score weight. A displayed penalty is an emulator penalty, never
an official Google component score.

Stable Light has a provisional continuous 20-minute candidate rule. The current
endpoint uses first Deep or REM for TTS and flags that approximation; if HR is
unavailable, it flags `tts_approximation_no_hr`. Sound Sleep uses the separately
versioned experimental `sound-sleep-hr-v1-exp-2026-10-04` classifier on minute
medians of raw sleep-window HR. It excludes restless/interrupted epochs and
applies an owner-observation-fitted nightly robust low-HR threshold (`alpha =
0.3`) and five-minute rolling-MAD stability threshold (`beta = 0.75` BPM).
Missing minute HR, stage or awakening data yields `null` with
`sound_sleep_unavailable_missing_epoch_data`; it is never zero-filled. The
response includes eligible, unknown, HR-covered and HR-sparse minute counts,
but no raw HR samples. The existing `/api/health/heart-rate` route remains hourly.

If duration, TTS, restlessness or interruptions cannot be derived, `score` and
`raw_score` are null, `insufficient_data` is true, `confidence` is `insufficient`,
and a `missing_*` flag explains why. Missing data is never zero. With all score
inputs present, `confidence` is `experimental`, or
`experimental_approximate` when the no-HR TTS fallback is used. The score is a
research approximation, not a medical diagnosis or Google's proprietary
formula. Google's exact low/steady-HR thresholds and component weights remain
unknown; any changed formula must receive a new model version.

The seven owner-provided Google Health app scores in
`tests/fixtures/sleep_score_google_calibration.json` are the only fitting
targets for the **numeric v0.1 score**. After a later owner authorization, the
seven app-displayed Sound Sleep minute observations became separate fitting
targets for the experimental HR classifier. Neither type of label is an API
field; all other fixture values were derived from stored Google Health API
sleep records after a real short-awakening backfill. Sep 30 is excluded because
its matching raw sleep session is missing. On these same seven fitting nights,
v0.1 raw-score error is MAE **1.322**, median absolute error **1.184**, maximum
absolute error **2.836**, and signed mean error **+0.174** points. This is
**in-sample fitting error, not validated accuracy**. Later labeled nights should
be reserved as a holdout set before making accuracy claims.

The S7 Sound Sleep classifier fits six complete nights: in-sample MAE **7.833**
minutes, median absolute error **3.5**, maximum absolute error **32**, signed
mean error **-4.167**. Oct 1 has sparse raw HR and returns unavailable. The
large Oct 2 miss and small sample limit confidence; the actual Google
low/steady-HR criteria remain unknown. Reproduce the research fit with
`python -m scripts.calibrate_sound_sleep` using a configured local InfluxDB.

Google Health ECG and irregular rhythm collection requires separate read scopes:
`https://www.googleapis.com/auth/googlehealth.ecg.readonly` and
`https://www.googleapis.com/auth/googlehealth.irn.readonly`. If the collector logs
`MISSING_OAUTH_SCOPE` for either data type, reauthorize the Health connection with
that scope in addition to the existing scopes, then replace its saved refresh
token. An authorized account can still have no records for a data type.

Health routes accept `?period=7d`; omitted periods use AI_DEFAULT_ANALYSIS_DAYS. Maximum is AI_MAX_ANALYSIS_DAYS (at most 90). The interval runs from midnight in the configured timezone on the first included day through now, with an inclusive start and exclusive end. Unknown query parameters are rejected. Devices accepts no query parameters and returns the latest stored observations regardless of age, including their timestamps.

Health responses contain `start`, `end` (UTC timestamps), `timezone`, and `series`. Each series has `measurement`, `resolution` (`hourly` or `stored`), and `rows`; each row contains a UTC `timestamp` and `fields`. Intraday fields are sum, count, min and max. Other measurements retain the selected stored fields and identity-related activity/sleep fields. Absent measurements have empty row lists; no synthetic data is returned.

Calendar rows are keyed by the person rather than by the wearable: they are filtered on USER_ID and the fixed provider `google_calendar`, so they survive a change of HEALTH_API_PROVIDER or DEVICE_ID, and each row carries its `CalendarId` and `EventId` alongside the stored event fields. Calendar rows are only present once calendar sync is connected and enabled (see docs/CALENDAR_SYNC.md).

Device responses contain `device_id`, `provider`, and `observations`. Each observation contains `measurement`, `timestamp`, and available `fields`. Missing battery telemetry produces no battery observation.

Errors: 401 for missing/invalid bearer token, 422 for invalid parameters or more than 20,000 rows per measurement, and 503 for unavailable/invalid stored data. Error bodies use the existing error/message envelope for application errors; FastAPI parameter validation retains its standard detail response. Use a shorter period when results exceed the limit. Existing AI endpoints and their comparison windows are unchanged.
