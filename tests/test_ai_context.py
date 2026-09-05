from datetime import datetime, timezone
import json
from app.services.health_analytics_service import Window
from app.services.ai_context_service import classify, measurements, build_context

def test_question_selection():
    assert classify("How has my weight changed?") == ["body"]
    assert set(classify("Tired after workouts")) == {"workouts", "recovery"}
    assert "GPS" not in measurements(classify("Overall summary"))
    assert "Total Steps" not in measurements(["sleep"])

def test_context_removes_identifiers_and_reports_missing():
    w = Window(7, "UTC", datetime(2026,9,5,12,tzinfo=timezone.utc))
    context, sufficient = build_context({"Total Steps": [{"time": "2026-09-05T00:00:00Z", "value": 0, "UserId": "secret-user", "DeviceId": "secret-device"}]}, w, ["activity"])
    assert sufficient
    assert "secret" not in json.dumps(context)
    assert context["activity"]["steps"]["today"] == 0
    assert "calories" in context["data_quality"]["missing"]
    assert "Total Steps" in context["data_quality"]["partial"]
    assert context["evidence_keys"] == ["steps"]

def test_historical_or_auxiliary_data_cannot_satisfy_sleep_request():
    w = Window(7, "UTC", datetime(2026,9,5,12,tzinfo=timezone.utc))
    for data in [{"Sleep Summary": [{"time": "2026-08-01T00:00:00Z", "minutesAsleep": 400}]},
                 {"RestingHR": [{"time": "2026-09-05T00:00:00Z", "value": 60}]}]:
        assert not build_context(data, w, ["sleep"])[1]

def test_workout_context_excludes_record_ids():
    w = Window(7, "UTC", datetime(2026,9,5,12,tzinfo=timezone.utc))
    context, sufficient = build_context({"Activity Records": [{"time": "2026-09-04T00:00:00Z", "ActivityId": "secret-id", "ActivityName": "Run", "duration": 500}]}, w, ["workouts"])
    assert sufficient and "secret-id" not in json.dumps(context)
    assert "workout_summary" in context["evidence_keys"]


def test_long_period_keeps_full_statistics_but_compacts_daily_detail():
    from datetime import timedelta
    w = Window(90, "UTC", datetime(2026,9,5,12,tzinfo=timezone.utc))
    rows = [{"time": (w.now-timedelta(days=i)).isoformat(), "value": 100} for i in range(90)]
    context, sufficient = build_context({"Total Steps": rows}, w, ["activity"])
    metric = context["activity"]["steps"]
    assert sufficient and metric["observed_days"] == 90
    assert metric["recorded_period_total"] == 9000
    assert len(metric["daily"]) == 14
