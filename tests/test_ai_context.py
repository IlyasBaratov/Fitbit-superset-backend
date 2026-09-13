from datetime import datetime, timezone
import json
from unittest.mock import Mock
import pytest
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


def insights(days=14, series_title="Weekly sync", correlated_days=12):
    """A `CalendarInsightsResponse.model_dump()` the AI context summarizes (C3.3)."""
    return {
        "period": {"days": 30, "timezone": "UTC", "bucket_minutes": 3},
        "days_with_events": days,
        # 2026-09-01 is a Tuesday; Wednesdays carry twice the meeting minutes here.
        "daily_load": [{"date": f"2026-09-{day:02d}", "event_count": 2, "meeting_count": 1,
                        "meeting_minutes": 120 if day % 7 == 2 else 60, "event_minutes": 90,
                        "back_to_back_count": 1, "first_event_hour": 9.0, "last_event_hour": 16.5}
                       for day in range(1, days+1)],
        "correlations": {
            "sleep_hours": {"same_day": {"r": 0.1, "n": correlated_days, "insufficient_data": False},
                            "next_day": {"r": -0.6, "n": correlated_days, "insufficient_data": False}},
            "resting_hr": {"same_day": {"r": None, "n": 4, "insufficient_data": True},
                           "next_day": {"r": None, "n": 4, "insufficient_data": True}},
        },
        "tercile_comparison": {},
        "series": [{"title": series_title, "occurrences": 4, "with_vitals": 4,
                    "mean_hr_vs_resting_pct": 22.5, "mean_recovery_delta": -3.0, "confounded_count": 0}],
        "time_of_day": {"morning": {"mean_hr_vs_resting_pct": 20.0, "n": 3},
                        "afternoon": {"mean_hr_vs_resting_pct": None, "n": 0},
                        "evening": {"mean_hr_vs_resting_pct": None, "n": 0}},
        "top_events": [{"event_id": "secret-event", "title": series_title, "hr_vs_resting_pct": 30.0}],
        "caveats": ["Elevated heart rate is a proxy for stress, not a measurement of it (D7)."],
    }


def test_calendar_question_selects_calendar_beside_the_metric_it_asks_about():
    assert set(classify("how do meetings affect my sleep")) == {"calendar", "sleep"}
    assert set(classify("busy day schedule")) == {"calendar"}
    assert "Calendar Events" in measurements(["calendar"])


def test_calendar_focus_builds_an_aggregated_section_without_event_rows():
    w = Window(30, "UTC", datetime(2026,9,14,12,tzinfo=timezone.utc))
    context, sufficient = build_context({}, w, ["calendar"], insights())
    assert sufficient
    section = context["calendar"]
    assert "secret-event" not in json.dumps(section)
    assert section["load"]["days_with_events"] == 14
    assert section["load"]["mean_meeting_minutes"] == 68.5714
    assert section["load"]["busiest_weekday"] == "Wednesday"
    # Only correlations with enough paired days behind them are reported.
    assert set(section["correlations"]) == {"sleep_hours"}
    assert section["correlations"]["sleep_hours"]["next_day"] == {"r": -0.6, "n": 12}
    assert section["series"][0]["label"] == "Weekly sync"
    assert section["time_of_day"]["afternoon"] == {"mean_hr_vs_resting_pct": None, "n": 0}
    assert section["caveats"] and "proxy" in section["caveats"][0]
    assert context["evidence_keys"] == ["calendar_load", "calendar_series"]
    assert "Calendar Events" not in context["data_quality"]["missing"]


def test_calendar_titles_are_replaced_when_the_setting_turns_them_off():
    w = Window(30, "UTC", datetime(2026,9,14,12,tzinfo=timezone.utc))
    context, _ = build_context({}, w, ["calendar"], insights(), False)
    assert context["calendar"]["series"][0]["label"] == "series-1"
    assert "Weekly sync" not in json.dumps(context)


def test_a_period_without_events_is_insufficient_for_a_calendar_question():
    w = Window(30, "UTC", datetime(2026,9,14,12,tzinfo=timezone.utc))
    for calendar in (None, insights(days=0)):
        context, sufficient = build_context({}, w, ["calendar"], calendar)
        assert not sufficient and "calendar" not in context
        assert "Calendar Events" in context["data_quality"]["missing"]


def test_calendar_insights_are_injected_once_and_never_fail_the_analysis():
    from app.config import Settings
    from app.errors import APIError
    from app.models import AIResponse, AnalysisRequest
    from app.services.analysis_service import AnalysisService

    settings = Settings(api_token="x"*40, gemini_key="k", model="m", timezone="UTC")
    influx, gemini, calendar = Mock(), Mock(), Mock()
    influx.fetch.return_value = {}
    calendar.insights.return_value = insights()
    gemini.generate.return_value = AIResponse(summary="Summary", insights=[], suggestions=[], warnings=[], data_gaps=[])
    service = AnalysisService(settings, influx, gemini, lambda: datetime(2026,9,14,12,tzinfo=timezone.utc), calendar)
    assert service.run(AnalysisRequest(period="30d", focus=["calendar"]), "analyze", settings.user_id).summary
    assert calendar.insights.call_args.args == ("30d",)
    assert "calendar" in gemini.generate.call_args.args[0]

    calendar.insights.side_effect = APIError("DATA_SERVICE_UNAVAILABLE", "unavailable", 503)
    with pytest.raises(APIError) as err:
        service.run(AnalysisRequest(period="30d", focus=["calendar"]), "analyze", settings.user_id)
    assert err.value.code == "INSUFFICIENT_DATA"


def test_long_period_keeps_full_statistics_but_compacts_daily_detail():
    from datetime import timedelta
    w = Window(90, "UTC", datetime(2026,9,5,12,tzinfo=timezone.utc))
    rows = [{"time": (w.now-timedelta(days=i)).isoformat(), "value": 100} for i in range(90)]
    context, sufficient = build_context({"Total Steps": rows}, w, ["activity"])
    metric = context["activity"]["steps"]
    assert sufficient and metric["observed_days"] == 90
    assert metric["recorded_period_total"] == 9000
    assert len(metric["daily"]) == 14
