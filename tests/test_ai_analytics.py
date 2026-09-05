from datetime import datetime, timedelta, timezone
import pytest
from app.services.health_analytics_service import Window, analyze, stats, percent

@pytest.fixture
def window():
    return Window(7, "America/Los_Angeles", datetime(2026, 9, 5, 19, tzinfo=timezone.utc))

def test_dst_boundaries_are_calendar_days():
    w = Window(7, "America/Los_Angeles", datetime(2026, 3, 10, tzinfo=timezone.utc))
    from datetime import date
    assert w.boundary(date(2026,3,9))-w.boundary(date(2026,3,8)) == timedelta(hours=23)

def test_baselines_exclude_today_and_missing_days(window):
    result = stats({window.today: 100, window.today-timedelta(days=1): 0, window.today-timedelta(days=2): 20}, window)
    assert result["baseline_7d_average"] == 10
    assert result["baseline_7d_observed_days"] == 2
    assert result["today_vs_7d_percent"] == 900
    assert percent(5, 0) is None

def test_steps_do_not_double_count_and_hr_is_weighted(window):
    result = analyze({"Total Steps": [{"time": "2026-09-05T07:00:00Z", "value": 100}],
        "Steps_Intraday": [{"time": "2026-09-05T08:00:00Z", "sum": 20, "count": 2}],
        "HeartRate_Intraday": [{"time": "2026-09-05T08:00:00Z", "sum": 100, "count": 2, "min": 40, "max": 60},
                               {"time": "2026-09-05T09:00:00Z", "sum": 100, "count": 1, "min": 100, "max": 100}]}, window)
    assert result["metrics"]["steps"]["today"] == 100
    assert result["metrics"]["heart_rate"]["today"] == pytest.approx(200/3)
    assert result["metrics"]["heart_rate_max"]["today"] == 100

def test_sleep_deduplication_wake_day_and_stage_fallback(window):
    row = {"time": "2026-09-04T23:00:00-07:00", "startTime": "2026-09-04T23:00:00-07:00", "endTime": "2026-09-05T07:00:00-07:00", "SleepSessionId": "s", "minutesAsleep": 420, "minutesInBed": 480}
    result = analyze({"Sleep Summary": [row, row], "Sleep Levels": [{"time": row["time"], "SleepSessionId": "s", "duration_seconds": 3600, "stageName": "deep"}]}, window)["metrics"]
    assert result["sleep_hours"]["today"] == 7
    assert result["deep_minutes"]["today"] == 60
    assert result["sleep_efficiency"]["today"] == 87.5
    assert result["deep_sleep_percent"]["today"] == pytest.approx(100/7)
    assert "rem_minutes" not in result

def test_workout_units_and_missing_rest_evidence(window):
    row = {"time": "2026-09-04T12:00:00-07:00", "ActivityId": "a", "ActivityName": "Walk", "duration": 1800, "distance": 2, "calories": 0}
    result = analyze({"Activity Records": [row, row]}, window)
    assert result["workouts"]["count"] == 1
    assert result["workouts"]["average_duration_seconds"] == 1800
    assert result["metrics"]["workout_distance"]["latest"] == 2
    assert "rest_days" not in result["workouts"]

def test_body_units_and_nonfinite_values(window):
    result = analyze({"weight": [{"time": "2026-09-05T10:00:00-07:00", "weightKg": 70, "weightLbs": 154}],
                      "HRV": [{"time": "2026-09-05T10:00:00Z", "dailyRmssd": float("nan")}]}, window)
    assert result["metrics"]["weight"]["today"] == 70
    assert result["metrics"]["weight"]["unit"] == "kg"
    assert "hrv_rmssd" not in result["metrics"]

def test_bedtime_consistency_wraps_midnight(window):
    rows = [{"time": f"2026-09-0{day}T00:00:00-07:00", "SleepSessionId": str(day), "startTime": f"2026-09-0{day}T{clock}:00-07:00", "endTime": f"2026-09-0{day}T08:00:00-07:00", "minutesAsleep": 400} for day, clock in [(3, "23:55"), (4, "00:05")]]
    assert analyze({"Sleep Summary": rows}, window)["sleep_consistency"]["bedtime_stddev_minutes"] == 5

def test_activity_totals_and_zone_fallback(window):
    time = "2026-09-05T10:00:00-07:00"
    result = analyze({"Activity Minutes": [{"time": time, "minutesSedentary": 60, "minutesLightlyActive": 20, "minutesFairlyActive": 10, "minutesVeryActive": 10}], "HR zones": [{"time": time, "TotalActiveZoneMinutes": 30}]}, window)["metrics"]
    assert result["active_minutes"]["today"] == 40
    assert result["sedentary_percent"]["today"] == 60
    assert result["active_zone_minutes"]["today"] == 30


def test_period_totals_and_workout_summary(window):
    data = {"Total Steps": [{"time": "2026-09-04T12:00:00-07:00", "value": 100}, {"time": "2026-09-05T12:00:00-07:00", "value": 200}],
            "Activity Records": [{"time": "2026-09-04T12:00:00-07:00", "calories": 150, "AverageHeartRate": 120}]}
    result = analyze(data, window)
    assert result["metrics"]["steps"]["recorded_period_total"] == 300
    assert result["workouts"]["total_recorded_calories"] == 150
    assert result["workouts"]["average_heart_rate_bpm"] == 120
