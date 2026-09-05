# Fitbit AI API Integration Documentation

## 1. Purpose

The AI API layer connects the Fitbit/Google Health data already stored in InfluxDB with the Gemini API so the application can:

- analyze sleep quality and sleep-stage patterns;
- analyze daily activity, steps, calories, distance, and active minutes;
- analyze workouts and recent exercise records;
- analyze heart-rate, resting heart-rate, HRV, SpO₂, breathing rate, and skin-temperature trends;
- compare recent values with the user's own historical baseline;
- identify useful trends or unusual changes;
- generate personalized, non-diagnostic fitness, recovery, sleep, and activity suggestions;
- answer natural-language questions about the user's stored wearable data.

The AI model should **not query InfluxDB directly**. The backend must retrieve and prepare the data first, then send a compact, structured summary to Gemini.

---

## 2. Existing Data Source

The collector writes wearable data to the `FitbitHealthStats` InfluxDB database.

The schema includes common tags:

- `UserId`
- `Provider`
- `Device`
- `DeviceId`

Main measurements available to the AI layer include:

### Cardiovascular
- `HeartRate_Intraday`
- `RestingHR`
- `HRV`
- `HR zones`

### Activity
- `Steps_Intraday`
- `Total Steps`
- `Activity Minutes`
- `Activity Records`
- `calories`
- `distance`
- optional `GPS`

### Sleep
- `Sleep Summary`
- `Sleep Levels`

### Recovery / health signals
- `SPO2`
- `SPO2_Intraday`
- `BreathingRate`
- `Skin Temperature Variation`

### Body metrics
- `weight`
- `height`
- `bmi`

### Device metadata
- `DeviceBatteryLevel`
- `Device Metadata`

---

## 3. High-Level Architecture

```text
Fitbit / Google Health API
        |
        v
Collector / Sync Service
        |
        v
InfluxDB: FitbitHealthStats
        |
        v
AI Data Service
  - queries InfluxDB
  - aggregates data
  - calculates trends/baselines
  - removes unnecessary identifiers
        |
        v
AI Context Builder
  - creates compact JSON
  - adds user question
  - adds safety instructions
        |
        v
Gemini API
        |
        v
AI Response Validator
        |
        v
REST API
        |
        v
Frontend
```

---

## 4. Core Responsibilities of the AI API

The AI API should do six things.

### 4.1 Retrieve the correct health data

For every AI request, the backend determines:

- which user is requesting analysis;
- what type of analysis is needed;
- what date range is relevant;
- which InfluxDB measurements are required.

Example:

A sleep question should retrieve:

- `Sleep Summary`
- `Sleep Levels`
- `RestingHR`
- `HRV`
- `BreathingRate`
- `SPO2`
- optionally `Skin Temperature Variation`

A workout/recovery question may retrieve:

- `Activity Records`
- `HR zones`
- `HeartRate_Intraday`
- `RestingHR`
- `HRV`
- `Total Steps`
- `Activity Minutes`
- recent sleep data

---

### 4.2 Aggregate raw data before sending it to Gemini

Do not send thousands of raw InfluxDB points unless they are specifically needed.

The backend should calculate useful statistics such as:

- daily totals;
- daily averages;
- minimum and maximum;
- 7-day average;
- 30-day average;
- percentage change;
- current value vs. personal baseline;
- trend direction;
- workout frequency;
- sleep consistency;
- resting-heart-rate change;
- HRV change;
- active-minute totals.

Example:

Instead of sending 10,000 intraday heart-rate samples:

```json
{
  "heart_rate": {
    "daily_average_bpm": 78,
    "resting_bpm": 61,
    "workout_average_bpm": 142,
    "workout_peak_bpm": 176,
    "resting_hr_7d_avg": 62.4,
    "resting_hr_30d_avg": 60.8
  }
}
```

---

### 4.3 Build a structured AI health context

The service should transform InfluxDB results into a consistent JSON structure.

Recommended internal structure:

```json
{
  "analysis_period": {
    "start": "2026-09-01",
    "end": "2026-09-07",
    "timezone": "America/Los_Angeles"
  },
  "sleep": {},
  "activity": {},
  "workouts": [],
  "cardiovascular": {},
  "recovery": {},
  "body": {},
  "trends": {},
  "data_quality": {}
}
```

Only include categories needed for the current request.

---

### 4.4 Send the prepared context to Gemini

Gemini should receive:

1. a system/developer instruction;
2. the prepared health-data context;
3. the user's question.

Example instruction:

```text
You are a wearable-fitness analytics assistant.

Analyze only the supplied wearable data.
Compare recent values with the user's own historical baseline when available.

You may:
- explain trends;
- summarize sleep, activity, recovery, and workout data;
- suggest general fitness, sleep, recovery, and activity adjustments.

You must not:
- diagnose a disease;
- claim that wearable data proves a medical condition;
- invent missing measurements;
- treat missing data as normal data.

Clearly mention uncertainty when data is missing or incomplete.
Return structured JSON.
```

---

### 4.5 Validate the AI response

The backend should require Gemini to return structured JSON instead of free-form text when possible.

Recommended response schema:

```json
{
  "summary": "string",
  "score": {
    "sleep": 0,
    "activity": 0,
    "recovery": 0
  },
  "insights": [
    {
      "category": "sleep",
      "title": "string",
      "observation": "string",
      "reasoning": "string",
      "priority": "low | medium | high"
    }
  ],
  "suggestions": [
    {
      "category": "recovery",
      "title": "string",
      "recommendation": "string",
      "based_on": ["HRV", "Sleep Summary"]
    }
  ],
  "warnings": [],
  "data_gaps": []
}
```

The backend must validate:

- required fields exist;
- numeric scores are inside the allowed range;
- model output is valid JSON;
- no unsupported medical claims are returned;
- the answer does not reference data that was not supplied.

---

## 5. Recommended Public REST Endpoints

### `POST /api/ai/analyze`

General health analysis.

Request:

```json
{
  "period": "7d",
  "focus": ["sleep", "activity", "recovery", "workouts"]
}
```

Response:

```json
{
  "summary": "...",
  "insights": [],
  "suggestions": [],
  "warnings": [],
  "data_gaps": []
}
```

---

### `POST /api/ai/sleep`

Analyzes sleep and recovery.

Data sources:

- `Sleep Summary`
- `Sleep Levels`
- `RestingHR`
- `HRV`
- `SPO2`
- `BreathingRate`
- optionally `Skin Temperature Variation`

The API should calculate:

- total sleep time;
- sleep efficiency;
- awake time;
- deep/light/REM duration;
- time to fall asleep;
- bedtime/wake-time consistency;
- 7-day sleep average;
- comparison with previous periods.

---

### `POST /api/ai/activity`

Analyzes general daily activity.

Data sources:

- `Total Steps`
- `Steps_Intraday`
- `Activity Minutes`
- `calories`
- `distance`
- `HR zones`

The API should calculate:

- steps today;
- 7-day average steps;
- active vs. sedentary minutes;
- active-zone minutes;
- distance;
- daily calorie trend;
- activity consistency.

---

### `POST /api/ai/workouts`

Analyzes recent workouts.

Data sources:

- `Activity Records`
- `HR zones`
- `HeartRate_Intraday`
- optional `GPS`
- sleep/recovery measurements when useful

The API should calculate:

- recent workout count;
- workout type;
- duration;
- average heart rate;
- calories;
- steps;
- distance;
- approximate workout intensity using available heart-rate information;
- training frequency;
- recovery context from sleep, HRV, and resting HR.

---

### `POST /api/ai/recovery`

Provides a non-medical recovery analysis.

Data sources:

- `HRV`
- `RestingHR`
- `Sleep Summary`
- `SPO2`
- `BreathingRate`
- `Skin Temperature Variation`
- recent `Activity Records`

The service should compare recent values with the user's historical baseline rather than using one universal threshold.

---

### `POST /api/ai/ask`

Natural-language questions about stored data.

Request:

```json
{
  "question": "Why do I seem more tired after my workouts this week?",
  "period": "14d"
}
```

The backend should:

1. classify the question;
2. choose the necessary measurements;
3. query InfluxDB;
4. compute summary statistics;
5. send the resulting context plus the question to Gemini;
6. return the answer.

Possible questions:

- "How was my sleep this week?"
- "Am I walking more than last week?"
- "How many workouts did I have this month?"
- "Was my resting heart rate higher after my last workout?"
- "How has my HRV changed over the last 30 days?"
- "Should I consider taking a lighter training day today?"

---

## 6. Data-Selection Rules

The AI service should use the minimum data required.

| User intent | Main measurements |
|---|---|
| Sleep | Sleep Summary, Sleep Levels |
| Sleep + recovery | Sleep Summary, Sleep Levels, HRV, RestingHR, SPO2, BreathingRate |
| Steps/activity | Total Steps, Steps_Intraday, Activity Minutes, distance, calories |
| Workout | Activity Records, HR zones, HeartRate_Intraday |
| Recovery | HRV, RestingHR, Sleep Summary, recent Activity Records |
| Oxygen/breathing | SPO2, SPO2_Intraday, BreathingRate |
| Body trend | weight, bmi, height |
| Complete health summary | all relevant measurements, aggregated first |

---

## 7. Derived Metrics the Backend Should Calculate

Gemini should interpret useful features, but deterministic calculations should remain in Python.

### Sleep

```text
sleep_hours = minutesAsleep / 60
deep_sleep_percent = minutesDeep / minutesAsleep * 100
rem_percent = minutesREM / minutesAsleep * 100
awake_percent = minutesAwake / minutesInBed * 100
```

Also calculate:

- 7-day average sleep duration;
- 30-day average sleep duration;
- sleep-efficiency trend;
- bedtime variability;
- wake-time variability.

### Steps and activity

Calculate:

- today vs. 7-day average;
- current week vs. previous week;
- sedentary percentage;
- very-active-minute trend;
- active-zone-minute trend.

### Heart and recovery

Calculate:

- resting HR today vs. 7-day baseline;
- resting HR today vs. 30-day baseline;
- HRV today vs. 7-day baseline;
- HRV today vs. 30-day baseline;
- breathing-rate deviation from baseline;
- skin-temperature deviation from baseline.

### Workouts

Calculate:

- workouts in last 7/30 days;
- average workout duration;
- average workout HR;
- total workout calories;
- workout frequency by type;
- training days in a row;
- rest days;
- recent intensity trend.

---

## 8. Example AI Context

```json
{
  "analysis_period": {
    "days": 7
  },
  "sleep": {
    "last_night_hours": 6.4,
    "seven_day_average_hours": 7.1,
    "efficiency_percent": 84,
    "deep_minutes": 62,
    "rem_minutes": 88
  },
  "activity": {
    "today_steps": 6250,
    "seven_day_average_steps": 9180,
    "active_minutes_today": 31,
    "sedentary_minutes_today": 590
  },
  "cardiovascular": {
    "resting_hr_today": 67,
    "resting_hr_30d_average": 61.5,
    "hrv_today_rmssd": 42,
    "hrv_30d_average_rmssd": 55
  },
  "workouts": {
    "last_7_days": 5,
    "consecutive_training_days": 4
  }
}
```

Gemini can then produce an observation such as:

```text
Your recent sleep duration is below your 7-day average while resting heart
rate is above your 30-day baseline and HRV is below baseline. Combined with
four consecutive training days, the data suggests that a lighter activity day
may be reasonable.
```

This is an interpretation of supplied data, not a medical diagnosis.

---

## 9. Suggested Backend Modules

```text
app/
├── api/
│   └── ai_routes.py
│
├── services/
│   ├── influx_service.py
│   ├── health_analytics_service.py
│   ├── ai_context_service.py
│   ├── gemini_service.py
│   └── ai_response_validator.py
│
├── models/
│   ├── ai_request.py
│   └── ai_response.py
│
├── prompts/
│   ├── health_analysis.txt
│   ├── sleep_analysis.txt
│   ├── workout_analysis.txt
│   └── recovery_analysis.txt
│
└── config.py
```

### `influx_service.py`

Responsibilities:

- connect to InfluxDB;
- query measurements;
- filter by `UserId`;
- apply time ranges;
- return normalized Python objects.

### `health_analytics_service.py`

Responsibilities:

- calculate averages;
- calculate baselines;
- calculate percentage changes;
- summarize workouts;
- summarize sleep stages;
- detect missing data;
- produce deterministic metrics.

### `ai_context_service.py`

Responsibilities:

- choose only relevant metrics;
- remove unnecessary identifying metadata;
- construct the JSON context;
- attach data-quality information.

### `gemini_service.py`

Responsibilities:

- initialize the Gemini client;
- read the model from configuration;
- send prompt + structured data;
- request structured output;
- handle Gemini API errors/timeouts.

Recommended environment variables:

```env
GEMINI_API_KEY=...
GEMINI_MODEL=your-selected-gemini-model
AI_DEFAULT_ANALYSIS_DAYS=7
AI_MAX_ANALYSIS_DAYS=90
```

### `ai_response_validator.py`

Responsibilities:

- validate JSON;
- validate required response fields;
- reject malformed responses;
- ensure recommendations are tied to supplied metrics;
- prevent unsupported diagnostic language.

---

## 10. Query Strategy

Different data has different resolutions.

### Daily summary measurements

Examples:

- `Total Steps`
- `RestingHR`
- `SPO2`
- `BreathingRate`
- `calories`
- `distance`

These can usually be queried for 7-30 days and aggregated directly.

### High-frequency measurements

Examples:

- `HeartRate_Intraday`
- `Steps_Intraday`
- `SPO2_Intraday`
- `Sleep Levels`
- `GPS`

These should usually be summarized by the backend before going to Gemini.

Do not send an entire month of second-by-second or minute-by-minute measurements to the model when an average, range, trend, or selected interval can answer the question.

---

## 11. Data Quality

The API must explicitly track missing measurements.

Recommended field:

```json
{
  "data_quality": {
    "available": [
      "sleep",
      "steps",
      "resting_hr"
    ],
    "missing": [
      "spo2"
    ],
    "partial": [
      "hrv"
    ]
  }
}
```

Gemini should be told never to infer a missing metric.

Provider-specific missing data must be treated normally. For example, optional GPS and battery measurements may not exist depending on the provider and permissions.

---

## 12. Security and Privacy

### API key

- keep `GEMINI_API_KEY` in `.env`;
- never return it to the frontend;
- never commit `.env` to Git;
- call Gemini only from the backend.

### User data

Only retrieve records for the authenticated user.

InfluxDB queries should filter using the authenticated user's `UserId`.

Do not trust a `UserId` sent directly by the frontend without authorization checks.

### Gemini payload

Avoid sending identifiers that Gemini does not need, including:

- real name;
- email;
- device ID;
- account identifiers.

Prefer aggregated, pseudonymous health context.

---

## 13. Safety Rules

This feature should be presented as fitness/wellness analytics, not medical diagnosis.

The AI may say:

- "Your sleep has been lower than your recent average."
- "Your HRV is below your recent baseline."
- "Your recent training load appears higher."
- "A lighter activity day may be reasonable."

It should not say:

- "You have a heart condition."
- "You are sick."
- "Your SpO₂ proves you have a specific disease."
- "You should stop prescribed treatment."

When the data shows a potentially serious issue, the model can advise the user to consider seeking qualified medical advice rather than diagnosing a condition.

---

## 14. Error Handling

The REST API should handle:

### No data

```json
{
  "error": "INSUFFICIENT_DATA",
  "message": "Not enough sleep data is available for this analysis."
}
```

### Gemini unavailable

```json
{
  "error": "AI_SERVICE_UNAVAILABLE",
  "message": "AI analysis is temporarily unavailable."
}
```

### Invalid period

```json
{
  "error": "INVALID_ANALYSIS_PERIOD",
  "message": "Analysis period must be between 1 and 90 days."
}
```

### Invalid AI output

The backend should retry once with a strict JSON instruction. If validation still fails, return a controlled error instead of sending malformed model output to the frontend.

---

## 15. Performance / Free-Tier Usage

To reduce Gemini usage:

- aggregate data before model calls;
- cache identical analyses for a short time;
- do not send raw intraday data unless needed;
- limit default analysis to 7 days;
- use 30/90-day data mainly for numeric baselines calculated in Python;
- do not call Gemini for deterministic calculations;
- reuse a prepared daily/weekly feature summary when possible.

Example:

```text
Raw database
   20,000+ points
        |
        v
Python aggregation
   ~50 useful values
        |
        v
Gemini
```

---

## 16. MVP Implementation Order

### Phase 1 - Gemini connection
- read `GEMINI_API_KEY`;
- initialize Gemini client;
- create a test endpoint.

### Phase 2 - InfluxDB health retrieval
Implement queries for:

1. `Sleep Summary`
2. `Sleep Levels`
3. `Total Steps`
4. `Activity Minutes`
5. `Activity Records`
6. `RestingHR`
7. `HRV`

### Phase 3 - Analytics
Calculate:

- sleep totals/trends;
- step totals/trends;
- workout summary;
- resting-HR baseline;
- HRV baseline.

### Phase 4 - AI context
Create one normalized JSON object containing those values.

### Phase 5 - AI analysis
Implement:

```text
POST /api/ai/analyze
```

### Phase 6 - Specialized endpoints
Add:

```text
POST /api/ai/sleep
POST /api/ai/activity
POST /api/ai/workouts
POST /api/ai/recovery
POST /api/ai/ask
```

### Phase 7 - Frontend
Add:

- AI health summary;
- sleep insights;
- workout/recovery suggestions;
- "Ask my health data" interface.

---

## 17. MVP Definition of Done

The first version is complete when a user can request:

```text
Analyze my last 7 days.
```

and the backend can:

```text
1. identify the authenticated user
2. query relevant InfluxDB measurements
3. calculate 7-day/30-day statistics
4. build structured AI context
5. send that context to Gemini
6. validate the Gemini response
7. return insights and suggestions to the frontend
```

The model should never require direct database credentials or unrestricted access to InfluxDB.
