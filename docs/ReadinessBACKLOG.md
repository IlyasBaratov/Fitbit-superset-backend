# Readiness Score v0.3: implementation plan and backlog

> **For agentic workers:** implement exactly ONE task per run: the first unchecked line in
> [Status](#status). Follow [How to work a task](#how-to-work-a-task). Only the Status list uses
> checkboxes; numbered steps inside a task are guidance, not trackers.
>
> This document is intentionally self-contained. Do **not** substitute an older readiness/recovery
> formula from another backlog, an Oura formula, a Gemini-generated score, or a Google/Fitbit score.
> The formula specified here is the owner-approved experimental **Readiness emulator v0.3**.

**Goal:** add a deterministic, explainable `GET /api/health/readiness-score` endpoint to
`IlyasBaratov/Fitbit-superset-backend`. The endpoint calculates one 1–100 Readiness Score per local
calendar day from the user's own HRV, resting heart rate and recent sleep history. It must use the
exact v0.3 formulas and data-window rules in this backlog, never Gemini, and must expose enough
component data to audit every score.

The model is an **experimental emulator**, not Google's proprietary Daily Readiness algorithm and
not a medical assessment. It was designed from the owner's observed Google Health readiness labels,
then improved with true holdout days. The current holdout result that justified proceeding with v0.3
was approximately:

| Holdout date | Google Health readiness | v0.3 estimate | absolute error |
|---|---:|---:|---:|
| 2026-10-06 | 13 | ~16 | ~3 |
| 2026-10-07 | 65 | ~66 | ~1 |
| 2026-10-08 | 53 | ~50 | ~3 |

Those holdout comparisons are research observations. **However, the owner has also supplied real historical
Google Health Readiness scores as factual observed data. Those historical labels are not mock data, demo data,
or synthetic test targets. They must be preserved as observed facts with provenance.**

For dates that have an owner-provided observed Google Health Readiness score, the API must return that exact
observed score as the authoritative historical value. For dates without an observed factual score, including all
future dates until a new observed label is explicitly added, the API must calculate Readiness with
`readiness-emulator-v0.3`. Never fabricate a Google label and never silently replace an observed fact with the
emulator output. The emulator may still be calculated alongside an observed fact for research comparison, but it
must be exposed separately as a calculated/model value.

**Architecture:** follow the existing deterministic Sleep Score architecture. Pure scoring/math lives
under `app/scores/`; storage reads and response composition live under `app/api/`; the FastAPI route
lives in `app/api/routes/health.py`; request-scoped access comes through `app/api/dependencies.py`;
composition happens in `app/api/main.py`. No storage, FastAPI, HTTP, Gemini or provider code may be
imported into the pure scoring module.

**Tech stack:** existing Python/FastAPI/Pydantic/InfluxDB stack only. Use the standard library
(`math`, `statistics`, `datetime`) for model math. Do not add a numerical/scientific dependency for
this feature.

**Current backend facts this plan relies on:**

- `GET /api/health/heart-rate` already exposes stored `RestingHR` and `HRV` series.
- The HRV field used by this model is `HRV.dailyRmssd` in milliseconds.
- The resting-heart-rate field used by this model is `RestingHR.value` in BPM.
- `GET /api/health/sleep` already exposes `Sleep Summary` rows.
- `GET /api/health/sleep-score` already exists and is the separate experimental
  `sleep-score-emulator-v0.1`.
- The Readiness model **does not consume the Sleep Score**. It consumes `Sleep Summary.minutesAsleep`
  over the recent 7-day sleep window.
- The current configured owner sleep goal is 420 minutes (7 hours). The readiness service must read
  the configured sleep goal rather than duplicate a second hard-coded owner setting.
- There is currently no deterministic readiness endpoint. `/api/ai/recovery` is an AI analysis route
  and must remain separate.
- The owner has supplied real Google Health Readiness observations for historical dates. Add them as a
  versioned factual observation dataset. These are **real measurements/labels provided by the owner**, not mocks.
- Existing HRV, RHR and sleep rows continue to come from the real stored health data already available through
  this backend. Do not duplicate them as fake fixture values for production behavior.
- Future/unobserved readiness dates are calculated with v0.3. If the owner later supplies a Google Health
  readiness value for a previously calculated date, append that factual observation with provenance; the observed
  fact becomes the public historical score while the model estimate remains available for comparison.

**Supersession rule:** the example project backlog contains an older F3 readiness design based on a
28-day z-score/recovery/load model. That design is **not** the formula to implement here. For
Readiness, this `ReadinessBACKLOG.md` is the source of truth. Do not add activity load, cardio-zone
load, skin temperature, breathing rate, previous-day activity, Recovery Index, or Oura's published
weights to v0.3.

---

## Status

- [ ] R1 Pure Readiness v0.3 model and unit tests
- [ ] R2 Readiness service, schemas and authenticated API route
- [ ] R3 Route/service integration tests, missing-data rules and calibration fixture
- [ ] R4 Documentation, OpenAPI verification and final cleanup

---

## How to work a task

1. `git pull --rebase origin main` and read the first unchecked Status task plus every existing file it
   touches before editing.
2. Run the existing backend test suite before editing. The baseline must be green.
3. Implement only that task. For pure model behavior, write the failing tests first, run them and
   verify they fail for the intended reason, then implement.
4. Run the focused tests for the task, then the full backend test suite.
5. Update this file in the implementation branch if it is copied into the repository: tick only the
   completed Status line and replace the task's `Notes:` with `done: <summary>` plus deviations.
6. Do not silently change a coefficient, time window, missing-data threshold, baseline rule or field
   name. A formula change requires a new model version (`v0.4`, etc.) and owner approval.
7. Commit with a conventional commit message. Suggested final feature commit:
   `feat(health): add deterministic readiness score v0.3`.

If implementation cannot remain green, revert code changes, document the blocker and stop. Never
commit a red build.

---

## Global constraints

- The public name is **Readiness Score**, but all docs and response caveats must call it an
  experimental emulator and explicitly say it is not Google's/Fitbit's proprietary score.
- Model version is exactly `readiness-emulator-v0.3`.
- Score range is **1 through 100**, inclusive. Do not return 0 for a computed score.
- Public `score` is null only when there is neither an observed factual readiness label nor enough real health
  data to calculate v0.3. `calculation_insufficient_data` refers only to the model calculation.
- The endpoint must be deterministic: same stored data + same configuration + same clock => same
  result.
- Never call Gemini or any LLM from the readiness route or service.
- Never call an external Google/Fitbit API while serving the endpoint. Use already stored Influx data.
- Never call the existing `/api/health/sleep-score` endpoint internally. Readiness uses raw
  `Sleep Summary.minutesAsleep`, not Sleep Score.
- Do not use activity, steps, workouts, HR zones, temperature, respiratory rate, SpO2 or body data in
  v0.3.
- Do not treat a missing sleep night as zero minutes of sleep and do not treat it as a perfect night.
- Do not forward-fill missing HRV or RHR values.
- A baseline is based on **calendar days**, not “the previous N observations”.
- A daily HRV/RHR measurement belongs to the local calendar date of its stored timestamp.
- A sleep session belongs to its local **wake date**, i.e. the local date of `endTime`.
- For a wake date with multiple main-sleep sessions, use the same main-sleep selection semantics as
  the existing sleep-score implementation: choose a processed `isMainSleep` candidate and prefer the
  longest valid main sleep. Do not create a conflicting second interpretation of “main sleep”.
- Every average, standard deviation, weighted mean and component must use only finite, valid numeric
  values.
- HRV must be strictly positive. RHR must be strictly positive. Sleep minutes must be nonnegative.
- Use sample standard deviation (`statistics.stdev`, denominator `n - 1`) for the 30-day baselines.
- The SD floors below are numerical guards, not fitted coefficients. They prevent division by zero on
  an unnaturally flat baseline and must be surfaced with a flag when applied.
- No `float('nan')` or infinity may reach a Pydantic response.
- Keep Pydantic score models strict (`extra="forbid"`, `strict=True`, `allow_inf_nan=False`) like the
  current Sleep Score response.
- The route accepts only the existing `period` query parameter through `HealthQuery`; unknown query
  parameters remain rejected.
- Bearer authentication and server-controlled identity must match the other `/api/health/*` routes.
- The response must preserve oldest-to-newest local date order.
- Do not modify the existing Sleep Score formula while implementing Readiness.
- **No mock/synthetic readiness labels.** Every historical readiness label listed in this backlog came from the
  owner's real Google Health app and must be marked `observed_google_health`.
- Observed historical facts always take precedence over a calculated v0.3 value for the same local date.
- Do not hard-code observed scores inside the mathematical formula. Keep the fact dataset separate from the pure
  model so future/unobserved dates are genuinely calculated.

---

## Model decisions

### D1 · Inputs are HRV, RHR and recent sleep only

Readiness v0.3 has three data families:

1. **HRV** — `HRV.dailyRmssd` in milliseconds.
2. **Resting heart rate** — `RestingHR.value` in BPM.
3. **Recent sleep duration** — main-sleep `Sleep Summary.minutesAsleep` in minutes.

The Oura-style formula that inspired the “balance” idea is a research reference only. Do not copy its
activity, temperature, Recovery Index or previous-day-activity terms. v0.3 deliberately omits them.

### D2 · Current physiology uses a 30-day personal baseline

For a scored local day `d`, the baseline calendar window is exactly:

```text
[d - 30 days, d - 1 day]
```

The current day is never included in its own baseline.

For HRV:

```text
mu_hrv = arithmetic mean of valid daily HRV values in d-30 ... d-1
sd_hrv = sample standard deviation of those values
scale_hrv = max(sd_hrv, 1.0 ms)
z_hrv = (hrv_today - mu_hrv) / scale_hrv
```

For resting heart rate, direction is reversed so **positive always means favorable**:

```text
mu_rhr = arithmetic mean of valid daily RHR values in d-30 ... d-1
sd_rhr = sample standard deviation of those values
scale_rhr = max(sd_rhr, 1.0 bpm)
z_rhr = (mu_rhr - rhr_today) / scale_rhr
```

Minimum baseline coverage:

```text
HRV baseline: at least 14 valid prior-day values
RHR baseline: at least 14 valid prior-day values
```

If either current HRV/current RHR is missing, or either 30-day baseline has fewer than 14 valid
values, Readiness for that day is insufficient.

Why mean + SD instead of median + MAD: v0.3 is the Google-emulation branch of the research, and the
holdout model that outperformed v0.2 was defined using a recent-data mean/SD baseline. Do not replace
it with the earlier median/MAD approach without creating a new model version.

### D3 · Negative-current-value dead band

A mildly below-baseline value is not treated as severe physiological strain. Transform the current
z-scores into four one-sided terms:

```text
H_pos = max(z_hrv, 0)
H_neg = max(-z_hrv - 1, 0)

R_pos = max(z_rhr, 0)
R_neg = max(-z_rhr - 1, 0)
```

Interpretation:

- `z = 0` is exactly at the personal mean.
- positive z is favorable and contributes immediately through `*_pos`.
- a current value between `0` and `-1 SD` has no explicit negative-current penalty.
- only the portion worse than `-1 SD` contributes to `H_neg` or `R_neg`.

Examples:

```text
z_hrv = +0.7  -> H_pos = 0.7, H_neg = 0
z_hrv = -0.6  -> H_pos = 0,   H_neg = 0
z_hrv = -2.4  -> H_pos = 0,   H_neg = 1.4
```

Do not apply a symmetric dead band to positive values in v0.3.

### D4 · Seven-day HRV Balance is date-weighted, recent-first

Seven-day HRV history remains important, but it is a separate persistence penalty rather than a
30% average mixed directly into current HRV.

For day `d`, inspect the seven local calendar dates:

```text
d, d-1, d-2, d-3, d-4, d-5, d-6
```

Use date-specific decay weights:

```text
d     -> 1.0
d-1   -> 0.8
d-2   -> 0.8^2 = 0.64
d-3   -> 0.8^3
d-4   -> 0.8^4
d-5   -> 0.8^5
d-6   -> 0.8^6
```

The weighted mean is:

```text
hrv_7 = sum(weight_i * hrv_i for valid dates) / sum(weight_i for valid dates)
```

Missing dates do **not** shift the remaining observations forward. Example: if `d-2` is missing,
`d-3` still keeps weight `0.8^3`.

Coverage requirement:

```text
at least 5 valid HRV dates in d-6 ... d, and d itself must be valid
```

With 5 or 6 valid dates, renormalize over the available date weights and add
`partial_hrv_balance_window` to flags. With 7 valid dates there is no partial-window flag. With fewer
than 5, the day's Readiness is insufficient.

Standardize the seven-day weighted HRV value against the same prior-30-day HRV baseline used for
current HRV:

```text
z_hrv_7 = (hrv_7 - mu_hrv) / scale_hrv
B_H = max(-z_hrv_7, 0)
```

`B_H` only penalizes a recent weighted HRV balance below baseline. A positive seven-day balance does
not add a bonus in v0.3.

### D5 · Seven-day Sleep Balance uses sleep debt, not Sleep Score

Readiness v0.3 does **not** use Google Sleep Score and does **not** use this backend's experimental
Sleep Score. It uses actual main-sleep duration relative to the configured sleep-duration goal.

For each wake date `i` in `d-6 ... d`:

```text
debt_i = max(0, sleep_goal_minutes - minutes_asleep_i)
```

Extra sleep above the goal does not create negative debt or bonus credit.

When all 7 nights are present:

```text
Debt7 = sum(debt_i for all 7 nights)
```

Missing-data rule: require at least 5 valid main-sleep nights. If exactly 5 or 6 nights exist, do not
zero-fill the missing nights. Estimate a full-week debt from the observed nightly mean:

```text
Debt7 = sum(observed_debt) * 7 / observed_nights
```

and add `partial_sleep_window` to flags. Fewer than 5 valid main-sleep nights makes the day's
Readiness insufficient.

Convert weekly debt to the bounded 0–100 Sleep Balance term:

```text
SleepBalance = 100 * exp(-Debt7 / sleep_goal_minutes)
```

With the owner's current 420-minute goal:

```text
Debt7 =   0 min -> SleepBalance = 100.0
Debt7 = 210 min -> SleepBalance ≈ 60.65
Debt7 = 420 min -> SleepBalance ≈ 36.79
```

The service must use `settings.sleep_goal_minutes`. For the current owner calibration it is 420.
A nonpositive configured goal is invalid service data and must not be silently replaced.

### D6 · Exact Readiness v0.3 equation

After D2–D5 produce the terms, calculate:

```text
raw = (
    53.81
    + 16.83 * H_pos
    - 18.57 * H_neg
    +  9.85 * R_pos
    - 38.21 * R_neg
    - 10.24 * B_H
    +  0.05 * SleepBalance
)
```

Then:

```text
clamped_raw = clamp(raw, 1.0, 100.0)
score = round_half_up(clamped_raw)
```

Python's built-in `round()` uses bankers rounding and is **not** the required definition. For a
nonnegative clamped score use:

```python
score = math.floor(clamped_raw + 0.5)
```

The pure v0.3 calculation returns both `calculated_score` and `calculated_raw_score` (the pre-round value after
the 1–100 clamp is preferred for API transparency; if exposing unclamped `raw`, name it explicitly). The service
then applies D10 provenance precedence to choose the public `score`: observed fact first, otherwise the calculated
score.

Coefficient meaning:

| term | coefficient | effect |
|---|---:|---|
| intercept | +53.81 | typical starting level of v0.3 fit |
| `H_pos` | +16.83 | rewards current HRV above baseline |
| `H_neg` | −18.57 | penalizes current HRV beyond 1 SD below baseline |
| `R_pos` | +9.85 | rewards favorable current RHR |
| `R_neg` | −38.21 | strongly penalizes RHR beyond 1 SD unfavorable |
| `B_H` | −10.24 | penalizes sustained below-baseline 7-day HRV balance |
| `SleepBalance` | +0.05 | contributes 0–5 points based on recent sleep debt |

Do not re-normalize these coefficients to percentages. They are fitted equation coefficients, not
importance percentages.

### D7 · No extra “physiology gate” in v0.3

Earlier experiments used a separate logistic contributor score and a low-physiology gate. v0.3
replaced that behavior with the dead-band terms and fitted equation above. Do not reintroduce:

- `100 / (1 + exp(-z))` contributor transforms;
- a `min(H, R)` gate;
- a “both HRV and RHR < 30 => halve readiness” rule;
- the older `0.40 HRV + 0.30 RHR + 0.15 sleep + 0.15 sleep balance` formula.

Those belong to v0.2 research, not this implementation.

### D8 · Daily-data selection

For `HRV` and `RestingHR`, build a local-date map:

```text
local_date -> latest valid stored row for that local date
```

If more than one valid row maps to the same date, the latest timestamp wins.

For sleep, select one main sleep per local wake date. Reuse the semantics already implemented by the
sleep-score code rather than inventing a second rule. The only readiness field needed from that
session is `minutesAsleep`.

### D9 · Insufficient data and flags

A day is insufficient if any required condition fails:

- current HRV missing/invalid;
- current RHR missing/invalid;
- fewer than 14 HRV baseline days in prior 30;
- fewer than 14 RHR baseline days in prior 30;
- fewer than 5 HRV values in the seven-day balance window;
- fewer than 5 valid main-sleep nights in the seven-day sleep window;
- configured sleep goal <= 0.

When the **v0.3 calculation** is insufficient:

```text
calculated_score = null
calculated_raw_score = null
calculation_insufficient_data = true
```

Then apply D10:

```text
if an observed Google Health readiness fact exists for d:
    score = observed_score
    source = "observed_google_health"
    confidence = "observed_fact"
else:
    score = null
    source = "insufficient"
    confidence = "insufficient"
```

Populate whatever calculation components can still be computed and add explicit flags. Suggested stable flags:

```text
missing_current_hrv
missing_current_rhr
insufficient_hrv_baseline
insufficient_rhr_baseline
insufficient_hrv_balance_window
insufficient_sleep_window
partial_hrv_balance_window
partial_sleep_window
hrv_sd_floor_applied
rhr_sd_floor_applied
invalid_sleep_goal
```

For an **unobserved** date with a complete calculation, confidence is `"experimental"`; a calculated score using
a 5/6-day HRV or sleep window is `"experimental_partial"`. Any date with a factual Google Health label is
`"observed_fact"` regardless of whether a parallel model estimate is complete.

### D10 · Historical observed Readiness is factual data; future Readiness is calculated

The owner supplied the following **real Google Health Readiness scores**. Treat these as observed facts, not
mock data and not values to regenerate by forcing the model to match them exactly:

| Local date | Observed Google Health readiness | Status |
|---|---:|---|
| 2026-09-27 | 67 | observed fact |
| 2026-09-28 | 56 | observed fact |
| 2026-09-29 | 65 | observed fact |
| 2026-09-30 | 62 | observed fact; exclude from formula regression when required raw sleep is missing |
| 2026-10-01 | 52 | observed fact |
| 2026-10-02 | 61 | observed fact |
| 2026-10-03 | 15 | observed fact |
| 2026-10-04 | 22 | observed fact |
| 2026-10-05 | 25 | observed fact |
| 2026-10-06 | 13 | observed fact; v0.3 holdout |
| 2026-10-07 | 65 | observed fact; v0.3 holdout |
| 2026-10-08 | 53 | observed fact; v0.3 holdout |

Persist these in a small versioned factual-data file, for example:

```text
app/scores/data/readiness_observed_v1.json
```

Each record must include at minimum:

```json
{
  "date": "2026-10-08",
  "score": 53,
  "source": "google_health_owner_observation",
  "observed": true
}
```

Do not call this a fixture in runtime code, do not label it demo/mock, and do not add invented rows. The file is an
owner-provided historical observation dataset. A test may load this same factual file, but tests must not replace its
readiness labels with synthetic values.

Runtime precedence for each requested local date `d`:

```text
1. If d exists in readiness_observed_v1.json:
     public score = exact observed Google Health score
     source = observed_google_health
     confidence = observed_fact
     also compute v0.3 model estimate when real HRV/RHR/sleep inputs are sufficient, solely for comparison

2. Else if v0.3 has enough real health data:
     public score = calculated v0.3 score
     source = calculated_v0.3
     confidence = experimental or experimental_partial

3. Else:
     public score = null
     source = insufficient
     confidence = insufficient
```

Observed readiness values are labels from Google Health. They are **not inputs to the v0.3 calculation** and must
never leak into the baseline, HRV balance, sleep balance or coefficient equation. This preserves a clean separation:

```text
known historical dates -> factual observed score
future/unobserved dates -> v0.3 calculated score
```

If a future calculated day later receives a real Google Health readiness label from the owner, append that exact
label to the factual dataset rather than editing coefficients or rewriting history. Keep the previously calculated
model value available for validation/error analysis.

---

## R1 · Pure Readiness v0.3 model and unit tests

**Files**

- Create `app/scores/readiness.py`.
- Create `tests/test_readiness_score.py`.
- Do not modify storage or API files in R1.

**Public/pure model surface**

Exact names may be adjusted to repository naming conventions, but the responsibilities must remain
separate and testable:

```python
READINESS_MODEL_VERSION = "readiness-emulator-v0.3"
HRV_BASELINE_DAYS = 30
RHR_BASELINE_DAYS = 30
MIN_BASELINE_VALUES = 14
BALANCE_DAYS = 7
MIN_BALANCE_VALUES = 5
RECENCY_DECAY = 0.8
HRV_SD_FLOOR_MS = 1.0
RHR_SD_FLOOR_BPM = 1.0

# fitted v0.3 constants
INTERCEPT = 53.81
HRV_POS_COEF = 16.83
HRV_NEG_COEF = -18.57
RHR_POS_COEF = 9.85
RHR_NEG_COEF = -38.21
HRV_BALANCE_NEG_COEF = -10.24
SLEEP_BALANCE_COEF = 0.05
```

Keep the calculation pure. Suitable helpers include:

```python
sample_mean_and_scale(values, floor)
weighted_seven_day(values_by_date, day, decay=0.8)
sleep_debt_balance(sleep_minutes_by_wake_date, day, goal_minutes)
readiness_v03(...)
```

All constants should have short comments distinguishing **fitted model constants** from
**implementation/coverage constants**.

**Tests**

Write tests before implementation. At minimum:

1. baseline uses only `d-30 ... d-1`, never current day;
2. baseline uses calendar days rather than “last 30 observations”;
3. sample SD is used and the 1.0 unit floor is applied only when necessary;
4. HRV z direction: larger-than-mean HRV => positive z;
5. RHR z direction: lower-than-mean RHR => positive z;
6. dead band: `z=-0.9` produces zero negative term; `z=-1.9` produces 0.9;
7. 7-day HRV weights are exactly `1, .8, .8^2 ... .8^6` by date;
8. a missing `d-2` date does not shift `d-3` to the `d-2` weight;
9. 5/6 HRV values renormalize weights and flag partial; 4 values are insufficient;
10. nightly sleep debt is `max(0, goal - minutesAsleep)`;
11. extra sleep never creates negative debt;
12. 5/6 sleep nights extrapolate debt by `7/n`; 4 nights are insufficient;
13. `SleepBalance = 100 * exp(-Debt7 / goal)` to tight floating tolerance;
14. exact v0.3 coefficient equation;
15. final clamp is 1–100;
16. half-up rounding is used (`50.5 -> 51`);
17. higher current HRV, all else fixed, never lowers score;
18. lower current RHR, all else fixed, never lowers score;
19. more sleep debt, all else fixed, never raises score;
20. more negative 7-day HRV balance, all else fixed, never raises score;
21. no NaN/inf is emitted from flat baselines because floors apply.

**Done when:** pure tests are green; `app/scores/readiness.py` has no import from `app.api`,
`app.storage`, `fastapi`, provider clients, Gemini or requests/http libraries.

Notes:

---

## R2 · Readiness service, schemas and authenticated API route

**Files**

- Create `app/api/readiness_score_service.py`.
- Create `app/scores/data/readiness_observed_v1.json` containing only the real owner-provided Google Health
  readiness observations listed in D10.
- Modify `app/api/schemas/scores.py`.
- Modify `app/api/dependencies.py`.
- Modify `app/api/routes/health.py`.
- Modify `app/api/main.py`.

Follow the existing Sleep Score composition pattern instead of creating a parallel framework.

### Endpoint

Add:

```text
GET /api/health/readiness-score?period=7d
```

Contract:

- bearer authentication via existing `authenticate` dependency;
- query model is existing `HealthQuery`;
- period semantics come from existing `resolve_interval`;
- no request body;
- no Gemini;
- response model `ReadinessScoreResponse`;
- unknown query params remain 422 through the strict query model;
- one `days` entry per requested local date, oldest first;
- historical dates in the factual observation dataset return the exact observed Google Health score;
- dates absent from that dataset return the calculated v0.3 score when sufficient real health data exists.

### Storage query window

For a requested period beginning at local date `first`, the service needs context beginning at local
midnight of:

```text
first - 30 days
```

through the endpoint's normal `end` timestamp.

That single context window contains both the 30-day baseline needed for the first requested day and
its seven-day balance inputs. Query each required measurement **once per request**, never once per
scored day:

```text
HRV
RestingHR
Sleep Summary
```

Do not query Sleep Levels, raw intraday heart rate, activity, HR zones, workouts, SpO2, temperature
or breathing rate for v0.3.

Reuse the repository's bounded `query(measurement, start, end)` interface and existing exception
translation conventions:

```text
QueryLimitExceeded -> 422 HEALTH_QUERY_TOO_LARGE
DataUnavailable / invalid stored data -> 503 DATA_SERVICE_UNAVAILABLE
```

### Response schemas

Extend `app/api/schemas/scores.py` with strict Readiness models. Recommended shape:

```python
class ReadinessMetricComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    value: float | None = None
    baseline_mean: float | None = None
    baseline_sd: float | None = None
    scale: float | None = None
    z: float | None = None
    positive_term: float | None = None
    negative_term: float | None = None
    days_used: int | None = None

class ReadinessBalanceComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    value: float | None = None
    z: float | None = None
    penalty_term: float | None = None
    days_used: int | None = None
    decay: float | None = None

class ReadinessSleepComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    goal_minutes: float | None = None
    debt_minutes: float | None = None
    balance: float | None = None
    nights_used: int | None = None

class ReadinessScoreDay(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    date: date

    # Public historical/current value. Exact observed fact when one exists; otherwise model score.
    score: int | None
    source: Literal["observed_google_health", "calculated_v0.3", "insufficient"]
    confidence: Literal["observed_fact", "experimental", "experimental_partial", "insufficient"]

    # Provenance split: never hide observed-vs-calculated semantics.
    observed_score: int | None = None
    calculated_score: int | None = None
    calculated_raw_score: float | None = None
    calculation_insufficient_data: bool

    hrv_baseline_days: int
    rhr_baseline_days: int
    components: dict[str, ...]  # use a typed structure if cleaner; do not fall back to Any
    flags: list[str]

class ReadinessScoreResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    start: AwareDatetime
    end: AwareDatetime
    timezone: str
    model_version: Literal["readiness-emulator-v0.3"]
    days: list[ReadinessScoreDay]
    caveats: list[str]
```

Prefer a typed `ReadinessComponents` model over `dict[str, Any]` if it keeps the contract clearer.
At minimum the response must expose these auditable components:

```text
hrv_current
rhr_current
hrv_balance_7d
sleep_balance_7d
```

For a complete calculated day the client must be able to reconstruct the v0.3 model estimate from response
values plus the documented coefficients. For an observed historical day, `score` is the factual Google Health
value, while `calculated_score`/`calculated_raw_score` expose the independently calculated emulator result when
inputs are sufficient. The two values must never be conflated.

### Suggested JSON shape

The example below intentionally uses the **real owner-provided 2026-10-08 readiness fact (53)** for provenance
semantics. Baseline/component numbers remain illustrative unless they come from the stored backend data at test
time; do not treat the illustrative component numbers as factual health measurements:

```json
{
  "start": "2026-10-02T07:00:00Z",
  "end": "2026-10-08T23:00:00Z",
  "timezone": "America/Los_Angeles",
  "model_version": "readiness-emulator-v0.3",
  "days": [
    {
      "date": "2026-10-08",
      "score": 53,
      "source": "observed_google_health",
      "confidence": "observed_fact",
      "observed_score": 53,
      "calculated_score": 50,
      "calculated_raw_score": 49.8,
      "calculation_insufficient_data": false,
      "hrv_baseline_days": 22,
      "rhr_baseline_days": 21,
      "components": {
        "hrv_current": {
          "value": 57.0,
          "baseline_mean": 63.0,
          "baseline_sd": 8.0,
          "scale": 8.0,
          "z": -0.75,
          "positive_term": 0.0,
          "negative_term": 0.0,
          "days_used": 22
        },
        "rhr_current": {
          "value": 61.0,
          "baseline_mean": 60.0,
          "baseline_sd": 2.0,
          "scale": 2.0,
          "z": -0.5,
          "positive_term": 0.0,
          "negative_term": 0.0,
          "days_used": 21
        },
        "hrv_balance_7d": {
          "value": 54.2,
          "z": -1.1,
          "penalty_term": 1.1,
          "days_used": 7,
          "decay": 0.8
        },
        "sleep_balance_7d": {
          "goal_minutes": 420.0,
          "debt_minutes": 154.0,
          "balance": 69.3,
          "nights_used": 7
        }
      },
      "flags": []
    }
  ],
  "caveats": [
    "Historical dates explicitly labeled as observed_google_health are real owner-provided Google Health readiness facts.",
    "Unobserved dates are calculated by the experimental readiness-emulator-v0.3 from stored HRV, resting heart rate and recent sleep duration.",
    "Calculated scores are not Google's or Fitbit's proprietary algorithm and are not a medical assessment."
  ]
}
```

Do not test those illustrative baseline numbers as owner data.

### Dependency + app state

Add a readiness dependency parallel to Sleep Score:

```python
def get_readiness_score(request: Request):
    return request.app.state.readiness_score
```

Compose once in `create_app`:

```python
app.state.readiness_score = ReadinessScoreReadService(cfg, db, clock)
```

### Route

Add a route parallel to `/api/health/sleep-score`:

```python
@router.get("/api/health/readiness-score", response_model=ReadinessScoreResponse)
def readiness_score(
    query: Annotated[HealthQuery, Query()],
    user=Depends(authenticate),
    service=Depends(get_readiness_score),
):
    return service.read(query.period)
```

**Done when:** endpoint boots, OpenAPI includes it, auth and period behavior match existing health
routes, and no Gemini call is reachable from the service path.

Notes:

---

## R3 · Route/service integration tests, missing-data rules and calibration fixture

**Files**

- Create `tests/test_readiness_score_routes.py`.
- Use the same `app/scores/data/readiness_observed_v1.json` factual observation dataset in tests; do not
  create a separate contradictory mock readiness-label fixture.
- Modify architecture tests if the repository already enforces pure-domain boundaries.

### Required route/service tests

Use a fixed clock and a deterministic test repository populated from the **real owner-provided historical health
data already captured by this project**. Do not invent alternate readiness labels. For missing/error-path tests,
derive cases by removing or withholding rows from a copy of the real-data fixture rather than making up fake
readiness observations. Infrastructure test doubles are fine; the health/readiness values they serve must come
from the real factual dataset except where a test specifically validates malformed/missing-data handling. Test at least:

1. 401 without bearer token;
2. valid `?period=7d` returns seven ordered local dates;
3. invalid period and unknown query parameter return 422 under existing conventions;
4. repository is queried once each for `HRV`, `RestingHR`, `Sleep Summary`;
5. context query begins 30 local days before the first requested day;
6. Gemini is never called;
7. empty database returns every requested day as insufficient rather than 500;
8. missing current HRV => null score + `missing_current_hrv`;
9. missing current RHR => null score + `missing_current_rhr`;
10. 13 baseline HRV/RHR days => insufficient; 14 valid days crosses the threshold;
11. six HRV balance dates => computed with partial flag; four => insufficient;
12. six sleep nights => scaled weekly debt + partial flag; four => insufficient;
13. SD-floor flags appear when a baseline is flat;
14. multiple main sleep sessions use the same selection rule as the Sleep Score path;
15. `QueryLimitExceeded` maps to 422 without leaking exception text;
16. `DataUnavailable` maps to 503 without leaking exception text;
17. returned Pydantic model rejects NaN/inf.

### Owner factual readiness observations — real data, never mock data

The readiness labels below were directly provided from the owner's real Google Health app. They are **factual
historical observations** and must be copied exactly into `readiness_observed_v1.json`. They are not mock data,
demo values, synthetic fixtures or outputs that the emulator is allowed to overwrite.

| Date | Observed Google readiness | HRV shown by app (ms) | RHR shown by app (bpm) |
|---|---:|---:|---:|
| 2026-09-27 | 67 | — | — |
| 2026-09-28 | 56 | — | — |
| 2026-09-29 | 65 | 70 | 60 |
| 2026-09-30 | 62 | 64 | 62 |
| 2026-10-01 | 52 | 60 | 62 |
| 2026-10-02 | 61 | 67 | 62 |
| 2026-10-03 | 15 | 56 | 64 |
| 2026-10-04 | 22 | 43 | 62 |
| 2026-10-05 | 25 | 43 | 61 |
| 2026-10-06 | 13 | 37 | 61 |
| 2026-10-07 | 65 | 70 | 60 |
| 2026-10-08 | 53 | 57 | 61 |

The readiness column is the authoritative fact dataset. HRV/RHR values shown here are app-displayed rounded real
measurements and are useful for visual cross-checks. When calculating v0.3, prefer the backend's stored real floats
(`HRV.dailyRmssd`, `RestingHR.value`) whenever available instead of replacing them with rounded screenshot values.

Sep 30's readiness value `62` is still a real observed fact. If the raw sleep data needed for a model estimate is
missing for that date, return the observed factual score with `source=observed_google_health` and leave the
calculated/model side unavailable or partial. **Never reinterpret missing sleep as zero sleep.**

Historical observed facts must never enter the calculation as predictors. They are output labels/provenance only.
Future dates with no observed fact are calculated from real stored HRV/RHR/sleep data using v0.3.

### True holdout expectation that selected v0.3

Oct 6–8 were used as holdout observations after v0.2. With the historical raw data available during
research, v0.3 produced approximately:

```text
2026-10-06: Google 13, v0.3 ~16
2026-10-07: Google 65, v0.3 ~66
2026-10-08: Google 53, v0.3 ~50
holdout MAE ≈ 2.3–2.5 points
```

If the repository contains/reconstructs the same historical raw baseline windows, add a non-blocking
research regression test or calibration script that reports these comparisons. Do not force a unit
test to use rounded screenshot HRV/RHR in place of stored floats just to hit the research numbers.

### Existing Sleep Score is separate evidence

The current Sleep Score endpoint is already a separate emulator. Recent backend outputs include:

```text
2026-10-02 -> 79
2026-10-03 -> 72
2026-10-04 -> 78
2026-10-05 -> 87
2026-10-06 -> 80
2026-10-07 -> 78
2026-10-08 -> 84
```

These values are useful to verify the Sleep Score path remains unchanged, but they are **not** inputs
to Readiness v0.3. Readiness reads sleep minutes directly.

**Done when:** all pure, service and route tests pass; the current Sleep Score tests remain unchanged
green; the factual owner labels are available to runtime through the versioned observed-data source and are
clearly distinguished from calculated v0.3 values; no synthetic readiness labels exist anywhere in the feature.

Notes:

---

## R4 · Documentation, OpenAPI verification and final cleanup

**Files**

- Modify `docs/HEALTH_API.md`.
- Modify `README.md` feature/endpoints section if it enumerates deterministic scores.
- Regenerate or verify any checked-in API contract if the repository has one; otherwise verify the
  FastAPI-generated OpenAPI manually/in tests.
- Update this backlog's Status/Notes if it is committed to the repo.

### `docs/HEALTH_API.md` must document

1. endpoint: `GET /api/health/readiness-score?period=7d`;
2. authentication and period semantics;
3. model version `readiness-emulator-v0.3`;
4. exact three stored inputs (`HRV.dailyRmssd`, `RestingHR.value`, `Sleep Summary.minutesAsleep`);
5. exact 30-day baseline window and 14-value minimum;
6. sample SD + 1 ms/1 bpm floors;
7. RHR sign reversal;
8. exact negative dead-band equations;
9. exact 7-day HRV weights and partial-window rule;
10. exact sleep debt and missing-night extrapolation rule;
11. exact `SleepBalance` exponential equation;
12. exact fitted readiness equation and coefficients;
13. 1–100 clamp and half-up rounding;
14. every insufficient-data condition and flag;
15. explicit statement that Sleep Score is not an input;
16. historical observed-fact precedence: exact owner-provided Google Health score when present;
17. `source`, `observed_score`, `calculated_score` and calculated/raw provenance semantics;
18. explicit statement that no mock/synthetic readiness labels are used;
19. explicit statement that unobserved/future dates are calculated by v0.3;
20. explicit statement that calculated scores are experimental and not Google's/Fitbit's proprietary algorithm or
    a medical assessment;
21. explicit statement that changing any fitted formula/constant requires a new model version.

### OpenAPI acceptance

OpenAPI must expose a new authenticated path:

```text
GET /api/health/readiness-score
```

with optional `period` query parameter, 200 `ReadinessScoreResponse`, and the existing FastAPI 422
validation response.

The current API already exposes `/api/health/sleep-score`; Readiness must be a sibling endpoint rather
than changing that contract.

### Final verification

Run:

- pure readiness tests;
- readiness route/service tests;
- existing Sleep Score tests;
- full backend test suite;
- OpenAPI generation/snapshot tests if present.

Manually inspect one observed historical response and verify its public `score` exactly equals the factual Google
Health label while its separately named `calculated_score` is still reproducible from components when possible.
Then inspect one unobserved/future-style day and verify its public `score` comes from v0.3. Also inspect one
insufficient-data day and one partial-window day.

**Done when:** everything is green, docs contain the complete formula, OpenAPI exposes the route, no
existing Sleep Score behavior changes, and there are no new dependencies.

Notes:

---

## Formula reference card

This section intentionally repeats the complete calculation in one place so an implementation agent
can cross-check code without reconstructing it from prose.

For local day `d`:

### Current HRV

```text
HRV baseline window = d-30 ... d-1
mu_H = mean(valid HRV.dailyRmssd)
sd_H = sample_sd(valid HRV.dailyRmssd)
scale_H = max(sd_H, 1.0 ms)
z_H = (HRV_d - mu_H) / scale_H

H_pos = max(z_H, 0)
H_neg = max(-z_H - 1, 0)
```

### Current resting HR

```text
RHR baseline window = d-30 ... d-1
mu_R = mean(valid RestingHR.value)
sd_R = sample_sd(valid RestingHR.value)
scale_R = max(sd_R, 1.0 bpm)
z_R = (mu_R - RHR_d) / scale_R

R_pos = max(z_R, 0)
R_neg = max(-z_R - 1, 0)
```

### Seven-day HRV balance

```text
for k = 0..6:
    date = d-k
    weight = 0.8^k

HRV7 = sum(weight * HRV_date for valid dates) / sum(weight for valid dates)
z_H7 = (HRV7 - mu_H) / scale_H
B_H = max(-z_H7, 0)
```

Require current HRV and at least 5 valid dates in the seven-day window. Renormalize available date
weights; never shift weights because a date is missing.

### Seven-day sleep balance

```text
goal = settings.sleep_goal_minutes
for wake date i in d-6 ... d:
    debt_i = max(0, goal - main_sleep_minutes_asleep_i)

if nights_used == 7:
    Debt7 = sum(debt_i)
elif nights_used in {5, 6}:
    Debt7 = sum(debt_i) * 7 / nights_used
else:
    insufficient

SleepBalance = 100 * exp(-Debt7 / goal)
```

### Final model

```text
raw = 53.81
    + 16.83 * H_pos
    - 18.57 * H_neg
    +  9.85 * R_pos
    - 38.21 * R_neg
    - 10.24 * B_H
    +  0.05 * SleepBalance

clamped_raw = min(100, max(1, raw))
score = floor(clamped_raw + 0.5)
```

### Minimum data

```text
current HRV: required
current RHR: required
prior-30 HRV baseline: >= 14 valid days
prior-30 RHR baseline: >= 14 valid days
7-day HRV balance: >= 5 valid dates including current
7-day sleep window: >= 5 valid main-sleep nights
sleep goal: > 0
```

---

## Non-goals for v0.3

Do not implement any of these as part of this backlog:

- Google/Fitbit proprietary Daily Readiness retrieval;
- Oura's readiness formula;
- activity balance or previous-day activity;
- HR-zone/cardio load;
- recovery index;
- skin temperature contribution;
- respiratory-rate contribution;
- SpO2 contribution;
- workout recommendation logic;
- Gemini-generated readiness;
- changing the Sleep Score v0.1 formula;
- training a model at runtime;
- per-user coefficient fitting at request time;
- writing scores back into InfluxDB;
- generating fake historical Google readiness labels or mock calibration rows.

Those can be researched as future model versions only after v0.3 is shipped and validated on more
owner holdout days.

---

## Future validation protocol

After v0.3 ships, do not immediately refit it whenever a new Google score differs.

Collect at least another 7–14 owner days. Until the owner supplies the corresponding Google Health label, the
endpoint must treat each new date as calculated-only. When the real Google label is later supplied, append it to
the observed factual dataset without changing the original model estimate. Each validation row should contain:

```text
date
Google Health readiness label
stored HRV.dailyRmssd
stored RestingHR.value
stored main-sleep minutesAsleep
```

Run v0.3 unchanged and report:

```text
MAE
median absolute error
maximum absolute error
signed mean error
per-day predicted vs observed
```

Only after that holdout evaluation should a `readiness-emulator-v0.4` be proposed. Keep v0.3's
constants frozen so its validation remains meaningful.
