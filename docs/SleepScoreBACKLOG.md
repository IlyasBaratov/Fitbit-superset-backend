# Sleep Score API: implementation plan and backlog

> **For agentic workers:** implement exactly ONE task per run: the first unchecked line in
> [Status](#status). Read the whole task, the formulas it references, and the existing files it touches
> before editing. Keep the score engine deterministic and independent of Gemini. Update this file in the
> same commit when a task is completed or when an assumption changes.

**Goal:** Add a deterministic sleep-score endpoint to `IlyasBaratov/Fitbit-superset-backend` using Google
Health sleep data plus high-resolution heart-rate data. The endpoint must expose the raw sleep-quality
metrics used to produce the score, document every formula, and version the model so later calibration
changes are visible.

**Important:** this is an **emulator / research approximation of Google Health's current Sleep Score**, not
Google's proprietary formula. Google does not expose the final Sleep Score or the internal per-component
scores through the public Health API. The current formula is calibrated from a small labeled sample and is
**not finished or 100% accurate**. Ship it only with an explicit model version and caveat.

**Current target user calibration:** age 21, male, sleep-duration goal 7 h = 420 min. Age, gender, and sleep
goal must be configuration/profile inputs rather than permanent constants in the scoring code.

**Repository areas already relevant:**
- `app/providers/google_health/provider.py` — Google Health fetch orchestration. Current `INTRADAY` declares
  heart rate at `1sec`.
- `app/providers/google_health/intraday.py` — maps each Google `heart-rate` sample to
  `HeartRate_Intraday` with a `value` field.
- `app/providers/google_health/sleep.py` — maps `Sleep Summary` and `Sleep Levels`.
- `app/storage/influx/queries.py` — current generic read path treats `HeartRate_Intraday` as intraday and
  applies `GROUP BY time(1h)`, which is why API exports are hourly even when raw samples exist.
- `app/api/health_service.py` and `app/api/routes/health.py` — existing health API read path and routes.
- `app/api/schemas/health.py` — existing health response models.

---

## Status

- [x] S1 Verify raw heart-rate retention and add a raw sleep-window query
- [x] S2 Persist all sleep inputs needed by the score engine
- [x] S3 Build the sleep-session normalization model
- [x] S4 Implement exact sleep efficiency, restlessness, interruptions and full awakenings
- [x] S5 Implement Time to Sound Sleep v1
- [x] S6 Implement high-resolution sleep-HR epoch generation
- [ ] S7 Implement and calibrate Sound Sleep v1
- [x] S8 Implement Sleep Score Emulator v0.1
- [ ] S9 Add versioned sleep-score schemas and endpoint
- [ ] S10 Add unit, calibration and route tests
- [ ] S11 Document caveats, confidence and missing-data behavior
- [ ] S12 Collect more Google-labeled nights and calibrate v0.2

---

## Architecture

```text
Google Health API
      |
      +--> sleep ----------------------------------------------+
      |      Sleep Summary                                     |
      |      Sleep Levels / stages                             |
      |      short awakenings                                  |
      |                                                        |
      +--> heart-rate (high resolution) ------------------+     |
                                                          |     |
                                                          v     v
                                                    InfluxDB raw data
                                                          |
                                                          v
                                            Sleep session normalizer
                                                          |
             +----------------+----------------+-----------+-----------+----------------+
             |                |                |                       |                |
             v                v                v                       v                v
       duration/goal       efficiency    restlessness          interruptions       TTS / sound
                                                                                         |
                                                                                         v
                                                                              Sleep Score Engine
                                                                                         |
                                                                                         v
                                                                         /api/health/sleep-score
```

The score engine must be a pure analytics module: no HTTP calls, no InfluxDB calls, no Gemini calls. The
service layer reads data, normalizes it, then calls the pure engine.

---

## Ground truth and what the Google API does NOT provide

Google's current consumer Sleep Score uses these concepts:

1. sleep duration;
2. time to sound sleep;
3. sound sleep;
4. restlessness;
5. interruptions;
6. full awakenings.

The Google Health API gives enough data to calculate or approximate most raw inputs, but it does **not**
provide public fields such as `sleepScore`, `soundSleepMinutes`, `timeToSoundSleepScore`,
`restlessnessScore`, or `interruptionScore`.

Therefore this backend must distinguish:

- **raw/derived metric** — e.g. 16 minutes of restlessness;
- **component score/penalty** — our model's transformation of that metric;
- **final score** — the versioned emulator output.

Do not represent our component penalties as official Google component scores.

Reference material used while designing this backlog:
- Google Health Sleep Score help: https://support.google.com/googlehealth/answer/14236513
- Google Health sleep data type: https://developers.google.com/health/data-types/sleep
- Fitbit/Google patent material used only as implementation evidence, not proof of the live proprietary
  formula: https://patents.google.com/patent/US20250114034A1/en

---

## Calibration data currently available

Owner clarification (2026-10-04): of the values listed below, only the seven
`Google score` values are ground-truth targets for model fitting. TTS, Sound
Sleep, restlessness, interruptions and full awakenings are contextual display
observations, not public Google Health API fields or fitting targets. Production
components must be derived from raw API records; the display values must never
be written back as measurements or substituted for missing raw data.

Sep 30 has a Google Sleep Score but no corresponding raw sleep session in the exported dataset. **Exclude
Sep 30 from model fitting. Do not convert missing telemetry into zero sleep.** Missing data and zero are
semantically different.

| Wake date | Minutes asleep | Google score | TTS | Sound sleep | Restless | Interruptions | Full awakenings |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2026-09-27 | 464 | 87 | 16 | 179 | 16 | 0 | 0 |
| 2026-09-28 | 388 | 84 | 13 | 145 | 8 | 0 | 0 |
| 2026-09-29 | 361 | 80 | 14 | 152 | 9 | 0 | 0 |
| 2026-10-01 | 399 | 84 | 19 | 155 | 15 | 0 | 0 |
| 2026-10-02 | 389 | 82 | 23 | 142 | 15 | 0 | 0 |
| 2026-10-03 | 409 | 72 | 20 | 162 | 21 | 96 | 3 |
| 2026-10-04 | 437 | 77 | 26 | 159 | 16 | 33 | 1 |

The current sample is useful but underdetermined. In particular, interruption minutes and full-awakening
count are almost perfectly correlated in the only nights where either is non-zero, so their separate Google
weights cannot yet be identified.

---

## Data contract required by the score engine

For a single main sleep session, normalize the provider data into an internal structure equivalent to:

```python
SleepSessionFeatures(
    wake_date: date,
    session_id: str,
    start_time: datetime,
    end_time: datetime,
    minutes_asleep: float,
    minutes_in_bed: float,
    sleep_goal_minutes: float,
    stages: list[SleepStageInterval],       # awake/light/deep/rem with exact timestamps
    short_awakenings: list[Interval],       # micro-awakenings/restlessness
    heart_rate_samples: list[HeartRateSample],
    age: int | None,
    gender: str | None,
)
```

Required raw measurements:

| Requirement | Source | Required for |
|---|---|---|
| `minutesAsleep` | `Sleep Summary` | duration, efficiency, score |
| `minutesInSleepPeriod` / stored `minutesInBed` | `Sleep Summary` | efficiency |
| session start/end | `sleep.interval` | all temporal calculations |
| stage start/end/type | `sleep.stages` / `Sleep Levels` | TTS, interruptions, sound sleep |
| short awakenings start/end | `sleep.shortAwakenings` if available | restlessness |
| high-resolution BPM + timestamp | `heart-rate` | stable-light detection, sound sleep |
| sleep goal | user/profile config | duration shortfall |
| age/gender | user/profile config | future target-curve calibration |

### Main-sleep selection

For a wake date, choose the session marked main sleep. If provider semantics produce multiple main sessions,
use the longest processed/main session for that wake date and emit a diagnostic flag. Never merge unrelated
naps into the main Sleep Score unless a later model explicitly requires that.

---

## Heart-rate storage requirement

### Problem

The score cannot reproduce Google's definition of Sound Sleep from hourly heart-rate buckets. Sound sleep
requires distinguishing periods of low, steady heart rate inside Light/Deep/REM sleep.

The current repository already appears to do more than the exported API response suggests:

- `GoogleHealthProvider.INTRADAY` requests heart rate with a declared `1sec` resolution;
- `map_intraday()` writes each sample as `HeartRate_Intraday`;
- the generic Influx read path later aggregates intraday measurements with `GROUP BY time(1h)`.

Therefore **do not blindly add duplicate high-resolution storage**. S1 must first prove what production
InfluxDB actually retains.

### Required outcome

During every sleep session, the scoring service must be able to retrieve high-resolution heart-rate samples
at their stored timestamps. A one-minute median derived from raw samples is sufficient for the first sound-
sleep classifier; an hourly bucket is not.

Preferred implementation:

1. retain raw `HeartRate_Intraday` samples in InfluxDB;
2. add a repository method such as `query_raw_intraday(measurement, start, end)` that performs no
   `GROUP BY`;
3. use that raw method only for narrow sleep-session windows, so row counts stay bounded;
4. leave the existing hourly `/api/health/heart-rate` response unchanged for dashboard/chart consumers;
5. if production retention policies currently discard raw samples, change the policy so sleep-window HR is
   retained. If necessary, persist a dedicated `SleepHeartRate` series tagged with `SleepSessionId` rather
   than retaining unlimited raw HR forever.

The important requirement is: **stop relying on hourly rollups for sleep scoring; retrieve and retain the
high-resolution heart-rate samples that overlap each sleep session.**

---

## Exact / near-exact metrics

### 1. Sleep duration

```text
sleep_duration_minutes = minutesAsleep
```

Current user sleep goal:

```text
sleep_goal_minutes = 420
```

Duration shortfall used by the current emulator:

```text
D = max(0, sleep_goal_minutes - sleep_duration_minutes)
```

Sleeping longer than the goal does not create negative shortfall. This does **not** prove Google caps its
own duration contribution exactly this way; it is the v0.1 emulator assumption.

### 2. Sleep efficiency

Calculate independently even if the provider also stores `efficiency`:

```text
sleep_efficiency_percent = 100 * minutesAsleep / minutesInBed
```

Guard:

```text
if minutesInBed <= 0: efficiency = null
```

Example, 2026-10-04:

```text
437 / 482 * 100 = 90.66% -> display 91%
```

Sleep efficiency is useful output, but the current redesigned Google Sleep Score documentation does not list
it as one of the six named components. Do not automatically add it as a score weight without new evidence.

### 3. Restlessness

Preferred calculation:

```text
restlessness_seconds = sum(end - start for shortAwakening in shortAwakenings)
restlessness_minutes = restlessness_seconds / 60
```

If the normalized payload already stores `shortAwakeningSeconds`, use it and verify it equals the interval
sum. Store both count and seconds for debugging.

Example, 2026-10-04:

```text
shortAwakeningSeconds = 960
restlessness_minutes = 960 / 60 = 16
```

This matched the Google app's 16-minute value for the labeled night.

### 4. Interruptions

Google's displayed interruptions are well reproduced by long **internal** awake bouts. Use:

```text
long_awake_bouts = awake stage intervals with duration > 5 minutes
                   AND with asleep-stage data both before and after the interval

interruption_minutes = sum(duration(long_awake_bouts)) / 60
```

The internal rule matters:

- do not count leading awake time before the first actual asleep stage as an interruption;
- do not count trailing awake time after the final actual asleep stage as an interruption;
- do count an awake bout between Light/Deep/REM segments when its duration is > 5 min.

Example, 2026-10-04:

```text
one internal awake interval = 1,980 sec
1,980 / 60 = 33 interruption minutes
```

### 5. Full awakenings

Use the same long internal awake bouts:

```text
full_awakenings_count = count(long_awake_bouts)
```

Example, 2026-10-04:

```text
1 long internal awake bout -> 1 full awakening
```

This intentionally ties the raw metrics together but does **not** assume Google gives the two metrics the
same final score weight.

---

## Time to Sound Sleep v1

### Google concept

Time to Sound Sleep is not `minutesToFallAsleep`. It measures the settling-down phase from the beginning of
the sleep attempt/session until the person first enters a qualifying sound-sleep state.

Current evidence says a sound-sleep start can be:

- the start of the first Deep interval;
- the start of the first REM interval;
- the start of a sufficiently long, steady Light interval with calm/steady HR.

Patent material gives an example of an uninterrupted Light bout of approximately 20 minutes; treat 20
minutes as a **provisional calibration constant**, not an official public Google threshold.

### Formula

Let:

```text
T_deep  = start time of first Deep interval, or +infinity
T_rem   = start time of first REM interval, or +infinity
T_light = start time of first qualifying Stable Light interval, or +infinity
```

Then:

```text
T_sound = min(T_deep, T_rem, T_light)
time_to_sound_sleep_minutes = (T_sound - session_start) / 60 seconds
```

### Stable Light candidate rule

A Light interval qualifies when:

1. continuous Light sleep lasts at least `LIGHT_STABLE_MINUTES = 20` minutes;
2. it contains no long awake interruption;
3. its minute-level HR epochs satisfy the provisional low/steady-HR classifier described below.

### Evidence from current labels

For all seven usable labeled nights, Google's displayed Time to Sound Sleep exactly matched:

```text
first Deep start - stored sleep session start
```

Observed values: `16, 13, 14, 19, 23, 20, 26` minutes. This is strong validation of the first-Deep path for
this user's current sample, but other users/nights may enter stable Light or REM first.

### Fallback behavior

If high-resolution HR is unavailable:

```text
T_sound_fallback = min(T_deep, T_rem)
```

Return a flag such as `tts_approximation_no_hr=true`. Do not silently claim the result is exact.

---

## High-resolution HR epoch generation

Sound-sleep calculations should operate on one-minute epochs, derived from raw HR samples rather than using
hourly aggregates.

For each local/UTC minute overlapping the sleep session:

```text
minute_hr = median(all valid BPM samples inside that minute)
```

Why median: brief optical-sensor spikes are less influential than with the arithmetic mean.

Suggested data-quality fields per minute:

```text
sample_count
minute_hr
stage
is_short_awakening
is_long_interruption
```

Provisional minimum sample requirement:

```text
if sample_count < MIN_HR_SAMPLES_PER_MINUTE:
    minute_hr = unknown
```

Do not hard-code the threshold until the actual Google Health sample cadence in production is measured.
Tests should cover sparse minutes.

---

## Sound Sleep v1

### Google concept

Sound Sleep is total steady, undisturbed sleep. Qualifying periods may be Light, Deep, or REM, but Google
also describes low/steady heart rate as part of the classification. Therefore:

```text
SoundSleep != Deep + REM
```

Example, 2026-10-04:

```text
Deep + REM = 62 + 123 = 185 min
Google Sound Sleep = 159 min
```

### Epoch formula

For each minute `t`:

```text
StageOK_t      = stage_t in {LIGHT, DEEP, REM}
NotRestless_t  = minute does not overlap a short awakening
NotInterrupted_t = minute does not overlap a long awake interruption
LowHR_t        = low-heart-rate classifier says true
SteadyHR_t     = heart-rate-stability classifier says true

SoundEpoch_t = StageOK_t
               AND NotRestless_t
               AND NotInterrupted_t
               AND LowHR_t
               AND SteadyHR_t
```

Then:

```text
sound_sleep_minutes = sum(duration of SoundEpoch_t)
```

With one-minute epochs, each qualifying complete epoch contributes one minute. Handle partial boundary
minutes by exact overlap duration if practical.

### Candidate low-HR model A: robust threshold

For the whole asleep portion of the night:

```text
HR_med = median(minute_hr)
MAD_hr = median(abs(minute_hr - HR_med))
robust_scale_hr = 1.4826 * MAD_hr
```

Candidate rule:

```text
LowHR_t = minute_hr_t <= HR_med + alpha * robust_scale_hr
```

`alpha` is **not known yet** and must be calibrated against Google-labeled Sound Sleep minutes.

### Candidate low-HR model B: nightly percentile

Alternative:

```text
Qq = q-th percentile of valid sleeping minute_hr values
LowHR_t = minute_hr_t <= Qq
```

Learn `q` from calibration data rather than assuming 40% or any other value.

### Candidate steady-HR rule

Using a centered or trailing five-minute window:

```text
window = minute_hr[t-2 : t+2]
rolling_median = median(window)
rolling_MAD = median(abs(x - rolling_median) for x in window)
SteadyHR_t = rolling_MAD <= beta
```

`beta` is also a fitted parameter.

### Parameter fitting

For each labeled night `i`, calculate:

```text
predicted_sound_i(alpha, beta)
```

and fit parameters by minimizing:

```text
MAE(alpha, beta) = mean(abs(predicted_sound_i - google_sound_i))
```

For percentile model B, search over `q` plus `beta`.

Do not optimize and validate on the same tiny set and then claim accuracy. Once enough labels are collected,
reserve later dates as a holdout set.

---

## Sleep Score Emulator v0.1

### Purpose

This is the current empirical formula fitted to the seven usable labeled nights. It is intentionally simple
and should remain versioned as an emulator, not named `google_sleep_score`.

### Current formula

```text
D = max(0, sleep_goal_minutes - minutesAsleep)
T = time_to_sound_sleep_minutes
R = restlessness_minutes
I = interruption_minutes

raw_score = 100
            - 0.163 * D
            - 0.606 * T
            - 0.123 * R
            - 0.124 * I

sleep_score = clip(raw_score, 0, 100)
```

Current coefficients:

| Feature | Coefficient / penalty | Interpretation inside v0.1 only |
|---|---:|---|
| duration shortfall | `0.163` per minute | 30 min below goal ~= 4.9 points |
| time to sound sleep | `0.606` per minute | 20 min ~= 12.1 points |
| restlessness | `0.123` per minute | 16 min ~= 2.0 points |
| interruptions | `0.124` per minute | 33 min ~= 4.1 points |

### Current fit

| Date | Google | v0.1 prediction | Error |
|---|---:|---:|---:|
| 2026-09-27 | 87 | 88.3 | +1.3 |
| 2026-09-28 | 84 | 85.9 | +1.9 |
| 2026-09-29 | 80 | 80.8 | +0.8 |
| 2026-10-01 | 84 | 83.2 | -0.8 |
| 2026-10-02 | 82 | 79.2 | -2.8 |
| 2026-10-03 | 72 | 71.6 | -0.4 |
| 2026-10-04 | 77 | 78.2 | +1.2 |

In-sample mean absolute error is about 1.3 points. **This is not an out-of-sample accuracy claim.** Seven
observations are too few, and the same observations were used to fit and measure the formula.

### Why Sound Sleep and Full Awakenings are missing from v0.1

They are **not assumed to have zero importance**.

- Sound-sleep values vary only moderately in the current sample and are confounded with duration/quality.
- Full-awakening count is almost perfectly correlated with interruption minutes in the only non-zero nights:
  `96 min / 3 awakenings` and `33 min / 1 awakening`.

The model cannot separately identify those effects yet. Keep `sound_sleep_minutes` and
`full_awakenings_count` in the endpoint response and calibration dataset; add their terms only after more
informative labeled nights are collected.

### Future general form

The target family remains:

```text
SleepScore = 100
             - a * duration_shortfall
             - b * time_to_sound_sleep
             + c * sound_sleep_quality_term
             - d * restlessness
             - e * interruption_minutes
             - f * full_awakenings
             + optional age/gender/goal target adjustments
```

Do not choose `c` or `f` merely to make the existing seven nights fit exactly.

---

## Endpoint contract

Recommended route:

```text
GET /api/health/sleep-score?period=7d
```

Use the same bearer auth and bounded `period` semantics as the existing health endpoints. Returning a period,
not only today, makes calibration and app charts easier.

Suggested response shape:

```json
{
  "start": "2026-09-28T07:00:00Z",
  "end": "2026-10-04T18:00:00Z",
  "timezone": "America/Los_Angeles",
  "model_version": "sleep-score-emulator-v0.1",
  "days": [
    {
      "date": "2026-10-04",
      "score": 78,
      "sleep_efficiency": 90.66,
      "insufficient_data": false,
      "confidence": "experimental",
      "components": {
        "duration": {
          "minutes_asleep": 437,
          "goal_minutes": 420,
          "shortfall_minutes": 0,
          "penalty": 0.0
        },
        "time_to_sound_sleep": {
          "minutes": 26,
          "method": "first_deep_or_rem_or_stable_light",
          "penalty": 15.756
        },
        "sound_sleep": {
          "minutes": 159,
          "method": "hr_classifier_v1",
          "penalty": null
        },
        "restlessness": {
          "minutes": 16,
          "penalty": 1.968
        },
        "interruptions": {
          "minutes": 33,
          "penalty": 4.092
        },
        "full_awakenings": {
          "count": 1,
          "penalty": null
        }
      },
      "flags": ["experimental_formula"]
    }
  ],
  "caveats": [
    "This score is an experimental emulator and is not the proprietary Google/Fitbit Sleep Score.",
    "Sound Sleep and Full Awakenings are not independently weighted in v0.1 because current calibration data is insufficient."
  ]
}
```

If the score engine lacks required raw inputs, set `score = null`, `insufficient_data = true`, and explain the
reason in flags. Do not fabricate zeroes.

---

## Files to create / modify

Exact names can change during implementation, but prefer this structure because it separates deterministic
analytics from I/O:

**Create**
- `app/scores/__init__.py`
- `app/scores/sleep.py` — pure feature and score formulas
- `app/scores/sleep_hr.py` — minute-epoch and Sound Sleep classifier
- `app/api/sleep_score_service.py` — fetch/normalize/call pure scorer
- `app/api/schemas/scores.py` — response/component schemas if a shared score schema does not already exist
- `tests/test_sleep_score.py`
- `tests/test_sleep_score_routes.py`
- `tests/fixtures/sleep_score_labels.json` — calibration labels, clearly marked research-only

**Modify**
- `app/storage/influx/queries.py` — raw bounded intraday query for sleep windows
- `app/providers/google_health/sleep.py` — ensure short awakenings are retained and session IDs/timestamps are
  sufficient for joins
- `app/providers/google_health/intraday.py` only if production does not already persist raw samples correctly
- `app/api/routes/health.py` — endpoint
- `app/api/dependencies.py` — score service dependency if consistent with current architecture
- `app/api/main.py` — service initialization/version if needed
- `app/domain/measurements.py` / `app/storage/influx/schema.py` only if new fields or a `SleepHeartRate`
  measurement are actually required
- docs/OpenAPI docs after the route is stable

Do not add Gemini as a dependency of this endpoint.

---

## Tasks

### S1 · Verify raw heart-rate retention and add a raw sleep-window query

Completed 2026-10-04: the running local InfluxDB 1.x has an unlimited `autogen` retention policy.
The seven labeled sleep windows contain 8,553–12,824 raw `HeartRate_Intraday` samples each,
typically 23–25 samples per minute. The new identity-scoped read is limited to one 24-hour
window and 20,000 rows without `GROUP BY`; the existing hourly public read is unchanged.
Retention on any separate deployment remains to be checked there.

**Work**
1. Inspect real Influx rows for `HeartRate_Intraday` during a known sleep interval.
2. Confirm whether second/sub-minute timestamps are retained before the hourly API aggregation.
3. Add a bounded raw query that returns `time,value` without `GROUP BY` for one sleep session at a time.
4. If raw data is not retained, modify ingestion/retention so sleep-window samples are kept.
5. Keep existing dashboard heart-rate reads hourly to avoid a breaking API/performance change.

**Done when:** a test sleep interval returns multiple high-resolution HR samples per minute when available,
and the normal heart-rate endpoint still returns its existing aggregated shape.

### S2 · Persist all sleep inputs needed by the score engine

Completed 2026-10-04: `Sleep Short Awakenings` now stores exact interval starts,
ends and durations with session IDs. Missing summary fields remain absent rather
than becoming zero. The owner-approved historical Google Health backfill recovered
all seven labeled sessions and wrote 68 real short-awakening intervals. Stored
summary seconds equal the interval sums on each of the seven dates, including
Sep 27–29, whose previous summaries lacked the totals. Oct 4 stores 437 minutes
asleep, 482 minutes in bed and 960 short-awakening seconds; its stage rows are
available for interruption derivation.

Ensure `Sleep Summary` / `Sleep Levels` retain session ID, start/end, stage durations, short-awakening count and
seconds/intervals. Prefer exact interval data over only summary counts.

**Done when:** one database read can reconstruct all non-HR features for Oct 4 and reproduce 437 asleep,
482 in bed, 16 min restlessness, 33 min interruption, 1 full awakening.

### S3 · Build the sleep-session normalization model

Completed 2026-10-04: provider-independent immutable interval, stage, HR sample,
session and day-selection models normalize aware timestamps to UTC. Main sessions
are grouped by configured local wake date; multiple main candidates prefer a
processed session and then the longest duration, with a diagnostic flag. Missing
short-awakening intervals remain unavailable rather than becoming an empty list.

Create provider-independent dataclasses/Pydantic-internal models for main session, stage intervals,
short-awakening intervals, and raw HR samples. Resolve all timestamps to aware UTC datetimes; use configured
local timezone only to assign the wake date.

### S4 · Implement exact sleep efficiency, restlessness, interruptions and full awakenings

Completed 2026-10-04: pure functions calculate efficiency from asleep/in-bed
minutes, restlessness from stored seconds or exact interval sums, and
interruptions/full awakenings from strictly greater-than-five-minute internal
awake bouts. Missing inputs return unavailable; leading and trailing awake time
is excluded. Overlapping short-awakening intervals follow the documented sum
of durations, not a union of time ranges.

Implement the formulas in this file as pure functions. Include boundary tests for exactly 5:00 awake vs
5:01 awake, leading/trailing wake, and overlapping short awakenings.

### S5 · Implement Time to Sound Sleep v1

Completed 2026-10-04: the pure candidate selector takes the earliest first Deep,
first REM or qualified Stable Light start. Stable Light requires a continuous
20-minute Light bout and a separately supplied HR qualifier. Until the HR rule
is validated, Deep/REM selection carries an explicit approximation flag.
Recomputing from the seven stored stage series gives first-Deep offsets of
16, 13, 14, 19, 23, 20 and 26 minutes, respectively; these are derived
stage values, not Google API score labels.

Implement first Deep, first REM, and provisional stable-Light candidates. For the known seven labeled nights,
first-Deep path must reproduce `16,13,14,19,23,20,26`.

### S6 · Implement high-resolution sleep-HR epoch generation

Completed 2026-10-04: pure one-minute UTC epochs use medians of valid raw BPM
samples within the session. Each epoch carries sample count, stage, short-wake
and long-interruption state; unknown wake state remains unknown. Partial session
boundary minutes retain their exact overlap duration. The provisional quality
cutoff is 10 HR samples per minute, based on the measured 20–25/minute cadence
on the seven owner nights; sparse minutes have unknown HR. This cutoff is not
a low/steady-HR classifier threshold.

Join raw HR samples to the sleep interval, aggregate robustly to minute medians, assign stage/awakening flags,
and expose data-quality counts.

### S7 · Implement and calibrate Sound Sleep v1

Partially implemented 2026-10-04: pure robust-threshold and percentile low-HR
candidates, rolling five-minute MAD stability, and a research-only MAE helper
accept explicit parameters and independently verified Sound Sleep targets.
No low/steady-HR parameters have been fitted or enabled in production: the
seven approved fitting targets contain only final Sleep Score labels, and
v0.1 has no independently identifiable Sound Sleep weight. Sound Sleep and
HR-qualified Stable Light remain unavailable until suitable evidence exists.

Implement both robust-threshold and percentile low-HR candidates plus rolling-MAD stability. Grid-search
parameters against labeled Sound Sleep minutes. Keep calibration code/test tooling separate from production
runtime constants.

### S8 · Implement Sleep Score Emulator v0.1

Completed 2026-10-04: the pure `sleep-score-emulator-v0.1` scorer applies the
four published coefficients to derived duration shortfall, TTS, restlessness
and internal interruption minutes. Score is clamped to 0–100, with nearest
integer public score and unrounded internal value. Sound Sleep, full awakenings
and efficiency are reported without added v0.1 weights. Missing required
features yield null score and explicit flags.

Implement the current four-term formula and explicit formula version. Return raw components even when a
component has no v0.1 weight.

### S9 · Add versioned sleep-score schemas and endpoint

Add `GET /api/health/sleep-score?period=Nd`, auth, bounded period, response version, components, flags,
confidence and caveats. No LLM call.

### S10 · Add unit, calibration and route tests

Minimum tests:
- efficiency 437/482 -> 90.66%;
- short-awakening 960 sec -> 16 min;
- internal awake 1,980 sec -> 33 min and one full awakening;
- leading/trailing awake excluded from interruptions;
- TTS Oct 4 -> 26 min;
- v0.1 Oct 4 -> approximately 78.2 before integer rounding;
- all seven calibration predictions listed above within their recorded errors;
- missing raw sleep -> insufficient, not zero;
- missing high-res HR -> TTS fallback flag and Sound Sleep unavailable/approximate;
- endpoint never calls Gemini.

### S11 · Document caveats, confidence and missing-data behavior

Put formulas and constants in API docs. State clearly that the score is experimental, user-specific calibration
is small, Google internals are proprietary, and changes require a new model version.

### S12 · Collect more Google-labeled nights and calibrate v0.2

Collect at least 30 labeled nights before treating fitted coefficients as stable. Prioritize nights that break
current feature correlations:
- same interruption minutes with different awakening counts;
- very different Sound Sleep with similar duration;
- stable Light appearing before Deep/REM;
- unusually short and unusually long TTS;
- nights above and below the sleep goal;
- nights with sparse HR samples.

Reserve later observations as holdout validation data. Report MAE on holdout, not only training MAE.

---

## Non-goals / safety rules

- Do not claim this equals Google's proprietary Sleep Score.
- Do not use the score as a medical diagnosis.
- Do not convert missing data to zero.
- Do not use age/gender to infer anything beyond explicitly configured score targets; v0.1 currently does not
  have enough data to identify those adjustments.
- Do not expose raw second-level HR in the public response unless a separate endpoint explicitly requires it;
  use it internally for scoring.
- Do not log raw health payloads, tokens, or user-identifying data.

---

## Definition of done for the first usable version

The first production-capable experimental version is complete when:

1. the backend can read high-resolution HR over the main sleep window;
2. all raw sleep features are reproducible from stored data;
3. Oct 4 reproduces approximately 91% efficiency, 16 min restlessness, 33 min interruptions, one full
   awakening and 26 min TTS;
4. Sound Sleep is returned with a documented classifier and calibration error, or explicitly `null` if high-
   resolution HR is unavailable;
5. `sleep-score-emulator-v0.1` returns a deterministic 0-100 score with all components and caveats;
6. route/unit tests are green and Gemini is not involved;
7. docs state that the formula is **not final** and will be recalibrated as more Google-labeled nights are
   collected.
