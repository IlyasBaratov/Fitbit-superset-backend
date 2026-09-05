"""Deterministic, missing-aware analytics over the collector's stored schema."""
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
import math
import statistics
import pytz


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def average(values):
    values = [v for v in values if number(v)]
    return round(statistics.mean(values), 4) if values else None


def percent(value, baseline):
    return round((value - baseline) / abs(baseline) * 100, 4) if number(value) and number(baseline) and baseline != 0 else None


class Window:
    def __init__(self, days, zone, now=None):
        self.zone = pytz.timezone(zone)
        self.now = (now or datetime.now(timezone.utc)).astimezone(self.zone)
        self.today = self.now.date()
        self.days = days
        self.start_date = self.today - timedelta(days=days-1)
        self.previous_start = self.start_date - timedelta(days=days)
        self.query_start = self.boundary(min(self.previous_start, self.today-timedelta(days=30))-timedelta(days=2))

    def boundary(self, day):
        return self.zone.localize(datetime.combine(day, time.min)).astimezone(timezone.utc)

    def parse(self, value):
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return (self.zone.localize(dt, is_dst=None) if dt.tzinfo is None else dt).astimezone(self.zone)
        except (ValueError, TypeError, pytz.InvalidTimeError):
            return None

    def day(self, row, sleep=False):
        dt = self.parse(row.get("endTime") if sleep and row.get("endTime") else row.get("time"))
        return dt.date() if dt else None


def unique(rows, identity=None):
    result = {}
    for row in rows:
        key = row.get(identity) if identity else None
        key = key or (row.get("time"), row.get("ActivityName", ""))
        result[key] = row
    return sorted(result.values(), key=lambda r: r.get("time", ""))


# name: (category, measurement, field, unit)
FIELDS = {
    "steps": ("activity", "Total Steps", "value", "steps"),
    "calories": ("activity", "calories", "value", "kcal"),
    "distance": ("activity", "distance", "value", "km"),
    "sedentary_minutes": ("activity", "Activity Minutes", "minutesSedentary", "minutes"),
    "lightly_active_minutes": ("activity", "Activity Minutes", "minutesLightlyActive", "minutes"),
    "fairly_active_minutes": ("activity", "Activity Minutes", "minutesFairlyActive", "minutes"),
    "very_active_minutes": ("activity", "Activity Minutes", "minutesVeryActive", "minutes"),
    "active_zone_minutes": ("activity", "Activity Minutes", "minutesActiveZone", "minutes"),
    "resting_hr": ("cardiovascular", "RestingHR", "value", "bpm"),
    "hrv_rmssd": ("recovery", "HRV", "dailyRmssd", "ms"),
    "hrv_deep_rmssd": ("recovery", "HRV", "deepRmssd", "ms"),
    "spo2": ("recovery", "SPO2", "avg", "percent"),
    "breathing_rate": ("recovery", "BreathingRate", "value", "breaths/min"),
    "skin_temperature_deviation": ("recovery", "Skin Temperature Variation", "RelativeValue", "C"),
    "weight": ("body", "weight", "weightKg", "kg"),
    "height": ("body", "height", "heightCm", "cm"),
    "bmi": ("body", "bmi", "value", "kg/m2"),
}


def stats(series, window):
    current = {d: v for d, v in series.items() if window.start_date <= d <= window.today}
    complete = [v for d, v in current.items() if d < window.today]
    previous = [v for d, v in series.items() if window.previous_start <= d < window.start_date]
    baseline = lambda n: [v for d, v in series.items() if window.today-timedelta(days=n) <= d < window.today]
    last_day = max(current) if current else None
    latest = current.get(last_day)
    avg = average(complete)
    b7, b30 = average(baseline(7)), average(baseline(30))
    change = percent(avg, average(previous))
    return {
        "latest": latest, "latest_date": last_day.isoformat() if last_day else None,
        "today": current.get(window.today), "complete_day_average": avg,
        "min": min(current.values()) if current else None, "max": max(current.values()) if current else None,
        "baseline_7d_average": b7, "baseline_7d_observed_days": len(baseline(7)),
        "baseline_30d_average": b30, "baseline_30d_observed_days": len(baseline(30)),
        "today_vs_7d_percent": percent(current.get(window.today), b7),
        "today_vs_30d_percent": percent(current.get(window.today), b30),
        "previous_period_average": average(previous), "period_change_percent": change,
        "trend": None if change is None else ("up" if change > 0 else "down" if change < 0 else "unchanged"),
        "observed_days": len(current), "expected_days": window.days,
        "daily": {d.isoformat(): round(v, 4) for d, v in sorted(current.items())},
    }


def analyze(data, window):
    daily, specs = {}, {}
    def add(name, category, source, unit, series):
        daily[name] = series
        specs[name] = (category, source, unit)

    for name, (category, measurement, field, unit) in FIELDS.items():
        series = {}
        for row in unique(data.get(measurement, [])):
            day, value = window.day(row), row.get(field)
            if day and number(value):
                series[day] = value  # daily snapshots: latest value, never sum duplicates
        add(name, category, measurement, unit, series)

    for measurement, name, category, unit in [
        ("Steps_Intraday", "intraday_steps", "activity", "steps"),
        ("HeartRate_Intraday", "heart_rate", "cardiovascular", "bpm"),
        ("SPO2_Intraday", "intraday_spo2", "recovery", "percent"),
    ]:
        groups = defaultdict(list)
        for row in unique(data.get(measurement, [])):
            if (day := window.day(row)) and number(row.get("sum")) and number(row.get("count")) and row["count"] > 0:
                groups[day].append(row)
        values = {d: sum(r["sum"] for r in rows) / (1 if name == "intraday_steps" else sum(r["count"] for r in rows)) for d, rows in groups.items()}
        if name == "intraday_steps":
            for d, value in values.items():
                daily["steps"].setdefault(d, value)
            if values:
                specs["steps"] = ("activity", "Total Steps|Steps_Intraday", "steps")
        else:
            add(name, category, measurement, unit, values)
            for suffix, operation in [("min", min), ("max", max)]:
                add(name+"_"+suffix, category, measurement, unit, {
                    d: operation(r[suffix] for r in rows if number(r.get(suffix)))
                    for d, rows in groups.items() if any(number(r.get(suffix)) for r in rows)})

    for row in unique(data.get("HR zones", [])):
        day = window.day(row)
        if not day:
            continue
        value = row.get("TotalActiveZoneMinutes")
        if number(value):
            daily["active_zone_minutes"].setdefault(day, value)
            specs["active_zone_minutes"] = ("activity", "Activity Minutes|HR zones", "minutes")
        for field in ("Normal", "Fat Burn", "Cardio", "Peak"):
            if number(row.get(field)):
                name = "hr_zone_" + field.lower().replace(" ", "_")
                if name not in daily:
                    add(name, "activity", "HR zones", "minutes", {})
                daily[name][day] = row[field]

    active, sedentary = {}, {}
    for row in unique(data.get("Activity Minutes", [])):
        day = window.day(row)
        values = [row.get(f) for f in ("minutesLightlyActive", "minutesFairlyActive", "minutesVeryActive")]
        if day and all(number(v) for v in values):
            active[day] = sum(values)
            s = row.get("minutesSedentary")
            if number(s) and sum(values)+s > 0:
                sedentary[day] = s / (sum(values)+s) * 100
    add("active_minutes", "activity", "Activity Minutes", "minutes", active)
    add("sedentary_percent", "activity", "Activity Minutes", "percent", sedentary)

    # Sleep stages supplement only absent summary fields, keyed by session.
    stages = defaultdict(lambda: defaultdict(float))
    for row in unique(data.get("Sleep Levels", [])):
        if row.get("SleepSessionId") and number(row.get("duration_seconds")):
            stages[row["SleepSessionId"]][row.get("stageName")] += row["duration_seconds"] / 60
    sleep_days = defaultdict(list)
    bedtimes, waketimes = [], []
    for original in unique(data.get("Sleep Summary", []), "SleepSessionId"):
        row = dict(original)
        day = window.day(row, sleep=True)
        if not day or day > window.today:
            continue
        for field, stage in [("minutesDeep", "deep"), ("minutesLight", "light"), ("minutesREM", "rem"), ("minutesAwake", "awake")]:
            fallback = stages.get(row.get("SleepSessionId"), {}).get(stage)
            if not number(row.get(field)) and fallback is not None:
                row[field] = fallback
        sleep_days[day].append(row)
    for field, name in [("minutesAsleep", "sleep_hours"), ("minutesDeep", "deep_minutes"), ("minutesREM", "rem_minutes"), ("minutesLight", "light_minutes"), ("minutesAwake", "awake_minutes"), ("minutesInBed", "time_in_bed_minutes")]:
        values = {d: sum(r[field] for r in rows) / (60 if name == "sleep_hours" else 1) for d, rows in sleep_days.items() if all(number(r.get(field)) for r in rows)}
        add(name, "sleep", "Sleep Summary|Sleep Levels", "hours" if name == "sleep_hours" else "minutes", values)
    for name, numerator, denominator, multiplier in [
        ("sleep_efficiency", "sleep_hours", "time_in_bed_minutes", 6000),
        ("deep_sleep_percent", "deep_minutes", "sleep_hours", 100/60),
        ("rem_percent", "rem_minutes", "sleep_hours", 100/60),
        ("awake_percent", "awake_minutes", "time_in_bed_minutes", 100),
    ]:
        add(name, "sleep", "Sleep Summary|Sleep Levels", "percent", {d: v/daily[denominator][d]*multiplier for d, v in daily[numerator].items() if daily[denominator].get(d, 0) > 0})
    latency = {}
    for day, rows in sleep_days.items():
        main = [r for r in rows if str(r.get("isMainSleep", "true")).lower() == "true"]
        if not main:
            continue
        row = max(main, key=lambda r: r.get("minutesAsleep") or 0)
        if number(row.get("minutesToFallAsleep")):
            latency[day] = row["minutesToFallAsleep"]
        if window.start_date <= day <= window.today:
            for field, target in [("startTime", bedtimes), ("endTime", waketimes)]:
                dt = window.parse(row.get(field))
                if dt:
                    target.append(dt.hour * 60 + dt.minute)
    add("sleep_latency", "sleep", "Sleep Summary", "minutes", latency)

    workouts = unique(data.get("Activity Records", []), "ActivityId")
    dated = [(window.day(r), r) for r in workouts if window.day(r) and window.day(r) <= window.today]
    current = [(d, r) for d, r in dated if d >= window.start_date]
    workout_days = set(d for d, r in current)
    recent = []
    for day, row in current[-20:]:
        recent.append({"date": day.isoformat(), "type": str(row.get("ActivityName") or "Unknown")[:80],
                       **{field: row[field] for field in ("duration", "ActiveDuration", "AverageHeartRate", "calories", "steps", "distance") if number(row.get(field))}})
    for field, name, unit in [("duration", "workout_duration", "seconds"), ("AverageHeartRate", "workout_hr", "bpm"), ("calories", "workout_calories", "kcal"), ("distance", "workout_distance", "km")]:
        groups = defaultdict(list)
        for day, row in dated:
            value = row.get(field)
            if value is None and field == "duration":
                value = row.get("ActiveDuration")
            if number(value):
                groups[day].append(value)
        add(name, "workouts", "Activity Records", unit, {d: average(v) if field == "AverageHeartRate" else sum(v) for d, v in groups.items()})
    consecutive = 0
    cursor = window.today if window.today in workout_days else window.today-timedelta(days=1)
    while cursor in workout_days:
        consecutive += 1
        cursor -= timedelta(days=1)
    workout_summary = {
        "count": len(current), "last_7_days": sum(d >= window.today-timedelta(days=6) for d, r in dated),
        "last_30_days": sum(d >= window.today-timedelta(days=29) for d, r in dated),
        "training_days": len(workout_days), "consecutive_recorded_training_days": consecutive,
        "days_without_recorded_workout": window.days-len(workout_days),
        "average_duration_seconds": average([r.get("duration", r.get("ActiveDuration")) for d, r in current]),
        "frequency_by_type": dict(Counter(str(r.get("ActivityName") or "Unknown")[:80] for d, r in current)),
        "recent": recent, "recent_list_truncated": len(current) > 20,
        "coverage_note": "Missing workout records do not establish rest days. Collector fetches only the most recent 50 exercises.",
    }
    # Circular deviations avoid treating 23:55 and 00:05 as 24 hours apart.
    def variability(values):
        if len(values) < 2:
            return None
        angles = [v*2*math.pi/1440 for v in values]
        center = math.atan2(sum(map(math.sin, angles)), sum(map(math.cos, angles)))*1440/(2*math.pi)
        return round(statistics.pstdev([(v-center+720) % 1440-720 for v in values]), 2)
    return {
        "metrics": {name: {"category": specs[name][0], "sources": specs[name][1].split("|"), "unit": specs[name][2], **stats(series, window)} for name, series in daily.items() if series},
        "sleep_consistency": {"bedtime_stddev_minutes": variability(bedtimes), "wake_time_stddev_minutes": variability(waketimes)},
        "workouts": workout_summary if dated else None,
    }
