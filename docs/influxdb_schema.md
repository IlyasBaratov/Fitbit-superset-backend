# InfluxDB measurement schema

The collector writes to `FitbitHealthStats`. This schema extends the upstream
Grafana-compatible measurements while preserving their exact names.

## Common tags and point identity

Every point has these string tags:

| Tag | Source |
| --- | --- |
| `UserId` | Stable `USER_ID` configuration |
| `Provider` | Active `HEALTH_API_PROVIDER` (`google` or `fitbit`); `google_calendar` for calendar rows |
| `Device` | Human-readable `DEVICENAME` or discovered name |
| `DeviceId` | Stable `DEVICE_ID` configuration |

InfluxDB identifies a point by measurement, complete tag set, and timestamp.
Samples use their provider timestamp, daily summaries use the local-day boundary
converted to UTC, and all stored timestamps are UTC. Repeated synchronization
therefore updates the same point.

## Measurements

| Measurement | Additional tags | Fields (InfluxDB types) | Unit/notes |
| --- | --- | --- | --- |
| `HeartRate_Intraday` | — | `value` integer | BPM; actual sample time |
| `RestingHR` | — | `value` float | BPM; float preserves the live historical field type |
| `HRV` | — | `dailyRmssd`, `deepRmssd`, `nonRemHeartRateBpm`, `entropy` float | Only available fields are written |
| `HR zones` | — | `Normal`, `Fat Burn`, `Cardio`, `Peak`, `TotalActiveZoneMinutes` integer | Only provider-reported fields; Google does not fabricate `Normal` |
| `Steps_Intraday` | — | `value` integer | Steps in the provider interval |
| `Total Steps` | — | `value` float | Daily steps; float preserves the live historical field type |
| `Activity Minutes` | — | `minutesSedentary`, `minutesLightlyActive`, `minutesFairlyActive`, `minutesVeryActive`, `minutesActiveZone` integer | Minutes; only available categories |
| `Activity Records` | `ActivityName` | `ActivityId`, `startTime`, `endTime` string; `ActiveDuration`, `duration`, `AverageHeartRate`, `calories`, `steps` integer; `distance` float | Durations in seconds; distance in km; up to 50 recent records |
| `calories` | — | `value` float | Daily kcal |
| `distance` | — | `value` float | Daily km |
| `GPS` | `ActivityName` | `ActivityId` string; `lat`, `lon`, `altitude`, `distance`, `speed_kph` float; `heart_rate` integer | Optional; never estimated |
| `Sleep Summary` | `isMainSleep` (`true`/`false`) | `SleepSessionId`, `startTime`, `endTime` string; `efficiency`, `minutesAfterWakeup`, `minutesAsleep`, `minutesAwake`, `minutesDeep`, `minutesInBed`, `minutesLight`, `minutesREM`, `minutesToFallAsleep` integer | Session start time; calculated efficiency only when absent |
| `Sleep Levels` | `isMainSleep` (`true`/`false`) | `SleepSessionId`, `stageName` string; `level`, `duration_seconds` integer | Stage start time; deep=0, light=1, rem=2, awake=3, unknown=4 |
| `SPO2` | — | `avg`, `min`, `max` float | Daily percent; only returned bounds |
| `SPO2_Intraday` | — | `value` float | Percent; actual sample time |
| `BreathingRate` | — | `value` float | Breaths/minute |
| `Skin Temperature Variation` | — | `RelativeValue`, `nightlyTemperatureCelsius`, `baselineTemperatureCelsius`, `stddev30d` float | Celsius; relative value is nightly minus baseline |
| `weight` | — | `value`, `weightKg`, `weightLbs` float | `value` and `weightKg` are kg; `weightLbs` uses 2.2046226218 lb/kg |
| `height` | — | `value`, `heightCm`, `heightMeters` float; `heightMillimeters` integer | `value` is cm; actual sample time |
| `bmi` | — | `value`, `weightKg`, `heightMeters` float; `isCalculated` boolean | Weight timestamp; only when weight and height exist |
| `DeviceBatteryLevel` | — | `value` float | Percent; omitted when provider has no battery API |
| `Device Metadata` | — | `deviceName`, `deviceModel`, `timezone`, `lastSyncTime`, `firmwareVersion`, `connectionStatus` string; `batteryPercent` float | Actual available metadata only; written when content changes |
| `Calendar Events` | `CalendarId`, `EventId` | `summary`, `startTime`, `endTime`, `status`, `eventType`, `transparency`, `responseStatus`, `recurringEventId`, `updated` string; `duration_seconds`, `attendees` integer; `isOrganizer`, `isAllDay` boolean | Event start; all-day events use the local-day boundary. Person-keyed: `Provider=google_calendar`, `Device`/`DeviceId` are constants, not the wearable. `summary` keeps ≤ 200 printable characters; attendee identities are never stored |

## Compatibility decisions

- The referenced upstream schema defines the legacy names and types used by the
  existing Grafana dashboards.
- Live inspection found `RestingHR.value` and `Total Steps.value` stored as
  floats. New values remain floats because InfluxDB 1.x cannot change a field
  type in place without an explicit historical rewrite.
- No historical `weight` rows existed at migration time, so Google weight uses
  kilograms as the canonical `value` without mixing units.
- Adding the four common tags creates new series alongside legacy rows that only
  had `Device`. It does not alter or delete historical data.

## Optional and provider-specific data

Google Health does not currently expose battery telemetry or exercise GPS
coordinates through the endpoints used here, so those measurements are skipped.
Fitbit battery and TCX GPS remain supported. Missing permissions, unsupported
types, and empty date ranges produce warnings and do not stop other metrics.
