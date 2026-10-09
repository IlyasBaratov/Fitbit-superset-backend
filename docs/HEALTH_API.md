# Health read API

All routes require the existing `Authorization: Bearer <AI_API_TOKEN>` header. Identity always comes from USER_ID, HEALTH_API_PROVIDER and DEVICE_ID; clients cannot override it. These reads do not call Gemini.

| GET route | Measurements |
| --- | --- |
| /api/health/heart-rate | HeartRate_Intraday, RestingHR, HRV, HR zones |
| /api/health/sleep | Sleep Summary, Sleep Levels, Sleep Respiratory Rate |
| /api/health/sleep-score | Derived main-sleep features and experimental score v0.1 |
| /api/health/readiness-score | Owner-observed historical Readiness facts or experimental v0.3 calculation |
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
Score data type through this backend's Google Health API access. The owner separately
provided real historical Readiness scores observed in the Google Health app; these
factual labels are preserved with provenance by the Readiness endpoint below.
`efficiency` is the percentage of time in bed spent asleep; it
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

For future Google Health nights, the collector stores each supplied
`shortAwakenings[]` interval in `Sleep Short Awakenings` with its session ID and
original start/end times. It stores each `heart-rate` sample at its actual
timestamp in `HeartRate_Intraday`; the score service reads those raw samples
internally for a bounded sleep window. The collector refreshes current-day HR
every three minutes, previous-day HR hourly, and the rolling sleep group every
four hours. Sleep and HR pagination must complete before their points are
written; an interrupted source window is retried on a later scheduled run.
The local InfluxDB `autogen` policy currently retains raw points without an
expiry. Other deployments must retain raw HR for the sleep-score history they
serve. Google Health may omit intervals or HR samples, and outages beyond the
automatic lookback require a historical backfill; missing inputs remain
unavailable rather than being inferred.

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

## Readiness Score: observed facts and experimental v0.3 emulator

`GET /api/health/readiness-score?period=7d` uses the same bearer token,
server-controlled identity, `period` syntax, local-day bounds, and strict unknown-query
rejection as the other `/api/health/*` routes. Omit `period` for the configured default;
the maximum is the configured value, at most 90 days. There is no request body. The
response has one `days` entry for each requested local date, oldest first, and exposes
`start`, `end`, `timezone`, `model_version: readiness-emulator-v0.3`, and caveats.
OpenAPI exposes this authenticated GET path with a 200 `ReadinessScoreResponse`, optional
`period`, and the existing FastAPI 422 validation response.

### Factual historical values and provenance

The owner-provided Google Health app Readiness observations are real factual data,
preserved in `app/scores/data/readiness_observed_v1.json` with date, exact score,
`source: google_health_owner_observation`, and `observed: true`. No mock or synthetic
readiness labels are used. These are manually supplied app observations; this backend
does not retrieve a proprietary Readiness score from a Google/Fitbit API.

For a date in that file, public `score` is exactly its observed value,
`source = observed_google_health`, `confidence = observed_fact`, and `observed_score`
repeats the fact. The independently computed emulator estimate, when sufficient real
health data exists, appears only in `calculated_score` and `calculated_raw_score` for
comparison. An observed score stays public even when the calculation is unavailable;
`calculation_insufficient_data` describes only that calculation. For an unobserved date,
including future dates as they arrive, public `score` equals the computed v0.3 value,
`source = calculated_v0.3`, and `observed_score` is null. If the calculation also lacks
required inputs, `score` is null and `source = insufficient`. Adding a later real
observation makes that exact fact authoritative for its date without changing the
emulator formula. Observed labels never enter model baselines, balances, or predictors.

### Stored inputs and local-date selection

The only model inputs are stored `HRV.dailyRmssd` (ms), `RestingHR.value` (BPM), and
main-sleep `Sleep Summary.minutesAsleep` (minutes). Sleep Score is not an input.
Activity, steps, workouts, HR zones, temperature, respiratory rate, SpO2, body data,
Gemini, and external provider calls are not used. Each measurement is queried once
per request using the existing identity-scoped repository. For a requested first local
date `first`, the query begins at local midnight of `first - 30 days` and ends at
the normal request `end` timestamp.

HRV and RHR rows belong to the local date of their stored timestamp; the latest valid
positive finite value on a date wins. A sleep session belongs to the local date of
`endTime`. For multiple sessions on one wake date, the service reuses the Sleep Score
processed `isMainSleep` selection semantics and prefers the longest valid main sleep.
Only finite, nonnegative `minutesAsleep` is accepted. Missing dates are never
forward-filled or treated as zero sleep.

### Exact v0.3 calculation

For scored local date `d`, each HRV and RHR baseline uses valid daily values from
**`d-30` through `d-1`**, never `d`. Each needs at least 14 valid calendar days.
With `statistics.stdev` sample SD (denominator `n-1`):

```text
mu_H = mean(HRV baseline); sd_H = sample_sd(HRV baseline)
scale_H = max(sd_H, 1.0 ms); z_H = (HRV_d - mu_H) / scale_H
mu_R = mean(RHR baseline); sd_R = sample_sd(RHR baseline)
scale_R = max(sd_R, 1.0 bpm); z_R = (mu_R - RHR_d) / scale_R

H_pos = max(z_H, 0); H_neg = max(-z_H - 1, 0)
R_pos = max(z_R, 0); R_neg = max(-z_R - 1, 0)
```

RHR's direction is reversed so a lower current RHR is favorable. The negative
terms have a one-SD dead band; favorable positive values have no dead band. The
1 ms and 1 BPM SD floors are numerical guards, surfaced as flags when used.

Seven-day HRV Balance inspects **`d, d-1, ..., d-6`**. Date `d-k` keeps weight
`0.8^k` for `k=0..6`, even when another date is missing. Require current HRV and
at least five valid dates. With five or six, renormalize over available weights and
flag the partial window:

```text
HRV7 = sum(0.8^k * HRV_(d-k) for valid dates) / sum(0.8^k for valid dates)
z_H7 = (HRV7 - mu_H) / scale_H
B_H = max(-z_H7, 0)
```

`B_H` is only a penalty for sustained below-baseline HRV; positive balance adds no
bonus. The same prior-30-day HRV baseline is used for current HRV and HRV7.

Seven-day Sleep Balance inspects main-sleep minutes on wake dates `d-6` through `d`.
The configured `settings.sleep_goal_minutes` defaults to the owner's 420-minute
goal and must be positive. Require at least five valid nights:

```text
debt_i = max(0, sleep_goal_minutes - minutesAsleep_i)
Debt7 = sum(debt_i)                           if seven nights are present
Debt7 = sum(observed_debt_i) * 7 / nights_used if five or six are present
SleepBalance = 100 * exp(-Debt7 / sleep_goal_minutes)
```

Missing nights are not zero-filled; five or six nights estimate a full-week debt
from their observed mean. Extra sleep never creates negative debt or bonus credit.
The final owner-approved fitted equation is exactly:

```text
raw = 53.81
    + 16.83 * H_pos - 18.57 * H_neg
    +  9.85 * R_pos - 38.21 * R_neg
    - 10.24 * B_H + 0.05 * SleepBalance
clamped_raw = min(100.0, max(1.0, raw))
calculated_raw_score = clamped_raw
calculated_score = floor(clamped_raw + 0.5)
```

The score is in **1–100**. This is half-up rounding, not Python's ties-to-even
`round()`. The coefficients are fitted equation coefficients, not percentages.
Changing a coefficient, window, threshold, baseline rule, or field name requires a
new model version; v0.3 is frozen for future holdout evaluation.

### Missing data, flags, and response fields

The v0.3 calculation is insufficient when current HRV or RHR is missing/invalid,
either prior-30-day baseline has fewer than 14 valid days, the 7-day HRV window has
fewer than five valid dates, the sleep window has fewer than five valid nights, or
the configured sleep goal is nonpositive. Then `calculated_score` and
`calculated_raw_score` are null and `calculation_insufficient_data` is true.
Available component fields remain visible; no NaN or infinity is returned.

Stable flags are `missing_current_hrv`, `missing_current_rhr`,
`insufficient_hrv_baseline`, `insufficient_rhr_baseline`,
`insufficient_hrv_balance_window`, `insufficient_sleep_window`,
`partial_hrv_balance_window`, `partial_sleep_window`, `hrv_sd_floor_applied`,
`rhr_sd_floor_applied`, and `invalid_sleep_goal`. With a complete unobserved
calculation, `confidence` is `experimental`, or `experimental_partial` if a
five/six-day HRV or sleep window was used. A factual date always has
`confidence = observed_fact`; a date with neither fact nor calculation has
`confidence = insufficient`.

Each day includes `hrv_baseline_days`, `rhr_baseline_days`, `flags`, and typed
`components`: `hrv_current` and `rhr_current` expose value, baseline mean,
sample SD, scale, z, positive/negative terms and days used; `hrv_balance_7d`
exposes weighted value, z, penalty term, days used and decay; `sleep_balance_7d`
exposes goal, estimated weekly debt, balance and nights used. A client can
reconstruct each calculated result from those values and the equation above.
Strict Pydantic response models reject extra fields and nonfinite numbers.

These calculated scores are an **experimental emulator**, not Google's or
Fitbit's proprietary algorithm and not a medical assessment. The three-day
owner holdout can be reproduced without refitting with
`python -m scripts.compare_readiness_holdout`; it is a research comparison,
not a claim of validated accuracy. The endpoint uses stored data only, and
`/api/ai/recovery` remains a separate AI analysis route. Query limit failures
return 422 `HEALTH_QUERY_TOO_LARGE`; unavailable or invalid stored data returns
503 `DATA_SERVICE_UNAVAILABLE`, without leaking exception details.

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
