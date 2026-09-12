"""Per-event calendar reads: period rules, bucket width and resting baselines (C2.3)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.core.exceptions import DataUnavailable, QueryLimitExceeded
from app.api.main import create_app

EVENT_START = "2026-03-09T10:00:00+00:00"
EVENT_MINUTES = 30


def event(**overrides):
    begin = datetime.fromisoformat(EVENT_START)
    row = {
        "time": EVENT_START,
        "CalendarId": "primary",
        "EventId": "event-1",
        "summary": "Weekly sync",
        "startTime": EVENT_START,
        "endTime": (begin + timedelta(minutes=EVENT_MINUTES)).isoformat(),
        "duration_seconds": EVENT_MINUTES * 60,
        "status": "confirmed",
        "eventType": "default",
        "transparency": "opaque",
        "attendees": 3,
        "isOrganizer": True,
        "responseStatus": "accepted",
        "recurringEventId": "series-1",
        "isAllDay": False,
        "updated": "2026-03-08T08:00:00+00:00",
    }
    row.update(overrides)
    return row


def heart_rate(width=3, count=10, value=100):
    begin = datetime.fromisoformat(EVENT_START)
    return [
        {
            "time": (begin + timedelta(minutes=index * width)).isoformat(),
            "sum": value * width,
            "count": width,
            "min": value,
            "max": value,
        }
        for index in range(count)
    ]


def stored(calendar=(), hr=(), resting=()):
    """Answer the read layer per measurement, like the identity-scoped query does."""
    rows = {
        "Calendar Events": list(calendar),
        "HeartRate_Intraday": list(hr),
        "RestingHR": list(resting),
    }

    def query(measurement, start, end, bucket="1h"):
        return rows.get(measurement, [])

    return query


@pytest.fixture
def setup():
    cfg = Settings(api_token="t" * 40, gemini_key="test", model="test")
    db, gemini = Mock(), Mock()
    db.query.side_effect = stored()
    clock = lambda: datetime(2026, 3, 9, 12, tzinfo=timezone.utc)
    return cfg, db, gemini, clock


def read(client, cfg, query=""):
    return client.get(
        "/api/calendar/events" + query,
        headers={"Authorization": "Bearer " + cfg.api_token},
    )


def test_events_require_a_bearer_token_and_reject_unknown_parameters(setup):
    cfg, db, gemini, clock = setup
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        assert client.get("/api/calendar/events").status_code == 401
        assert read(client, cfg, "?UserId=other").status_code == 422
        assert read(client, cfg, "?period=91d").status_code == 422
        assert read(client, cfg, "?period=0d").status_code == 422
        assert read(client, cfg, "?period=week").status_code == 422
    gemini.generate.assert_not_called()


def test_a_period_without_events_returns_no_events_and_reads_no_vitals(setup):
    cfg, db, gemini, clock = setup
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        response = read(client, cfg)
        assert response.status_code == 200
        body = response.json()
        assert body["events"] == []
        assert body["timezone"] == cfg.timezone
        assert body["start"] == "2026-03-03T08:00:00Z"
        assert body["bucket_minutes"] == 1
    assert [call.args[0] for call in db.query.call_args_list] == ["Calendar Events"]


def test_vitals_are_computed_from_stored_buckets_at_the_period_width(setup):
    cfg, db, gemini, clock = setup
    db.query.side_effect = stored(
        calendar=[event()],
        hr=heart_rate(),
        resting=[{"time": "2026-03-09T08:00:00Z", "value": 60.0}],
    )
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        body = read(client, cfg, "?period=30d").json()
    assert body["bucket_minutes"] == 3
    assert len(body["events"]) == 1
    stored_event = body["events"][0]
    assert stored_event["event_id"] == "event-1"
    assert stored_event["calendar_id"] == "primary"
    assert stored_event["summary"] == "Weekly sync"
    assert stored_event["start"] == "2026-03-09T10:00:00Z"
    assert stored_event["duration_minutes"] == EVENT_MINUTES
    assert stored_event["attendees"] == 3
    assert stored_event["is_organizer"] is True
    assert stored_event["response_status"] == "accepted"
    assert stored_event["recurring_event_id"] == "series-1"
    assert stored_event["notes"] == []
    vitals = stored_event["vitals"]
    assert (vitals["mean_hr"], vitals["max_hr"], vitals["coverage_pct"]) == (100, 100, 100)
    assert vitals["hr_vs_resting_pct"] == pytest.approx(200 / 3, abs=5e-4)
    assert vitals["movement_confounded"] is False
    assert vitals["steps"] is None
    intraday = [call for call in db.query.call_args_list if call.args[0] == "HeartRate_Intraday"]
    assert intraday and intraday[0].kwargs["bucket"] == "3m"


def test_events_that_cannot_be_read_are_left_out(setup):
    cfg, db, gemini, clock = setup
    db.query.side_effect = stored(
        calendar=[
            event(EventId="cancelled", status="cancelled"),
            event(EventId="all-day", isAllDay=True),
            event(EventId="free", transparency="transparent"),
            event(),
        ],
        hr=heart_rate(),
    )
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        body = read(client, cfg, "?period=30d").json()
    assert [row["event_id"] for row in body["events"]] == ["event-1"]


def test_a_nearby_resting_rate_is_the_baseline_and_a_stale_one_is_not(setup):
    cfg, db, gemini, clock = setup
    for day, elevation in (("2026-03-05", pytest.approx(200 / 3, abs=5e-4)), ("2026-02-14", None)):
        db.query.side_effect = stored(
            calendar=[event()],
            hr=heart_rate(),
            resting=[{"time": day + "T08:00:00Z", "value": 60.0}],
        )
        with TestClient(create_app(cfg, db, gemini, clock)) as client:
            body = read(client, cfg, "?period=30d").json()
        vitals = body["events"][0]["vitals"]
        assert vitals["hr_vs_resting_pct"] == elevation
        assert bool(body["events"][0]["notes"]) is (elevation is None)


def test_thin_coverage_reports_a_note_without_vitals(setup):
    cfg, db, gemini, clock = setup
    db.query.side_effect = stored(calendar=[event()], hr=heart_rate(count=2))
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        body = read(client, cfg, "?period=30d").json()
    assert body["events"][0]["vitals"] is None
    assert any("covers" in note for note in body["events"][0]["notes"])


def test_storage_failures_reuse_the_health_error_codes_without_details(setup):
    cfg, db, gemini, clock = setup
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        for error, status, code in (
            (DataUnavailable("secret"), 503, "DATA_SERVICE_UNAVAILABLE"),
            (QueryLimitExceeded("secret"), 422, "HEALTH_QUERY_TOO_LARGE"),
        ):
            db.query.side_effect = error
            response = read(client, cfg, "?period=30d")
            assert response.status_code == status
            assert response.json()["error"] == code
            assert "secret" not in response.text


# --- C3.3 GET /api/calendar/insights -------------------------------------------------

INSIGHT_DAYS = 19
MEETING_HOUR = 18  # UTC; a local morning on both sides of the daylight-saving switch.


def insight_rows():
    """One growing meeting per day, a matching resting rate, and buckets covering both."""
    first = datetime(2026, 2, 18, MEETING_HOUR, tzinfo=timezone.utc)
    events, buckets, resting = [], [], []
    for index in range(INSIGHT_DAYS):
        begin = first + timedelta(days=index)
        minutes = 30 + index
        events.append(
            event(
                time=begin.isoformat(),
                EventId=f"event-{index}",
                startTime=begin.isoformat(),
                endTime=(begin + timedelta(minutes=minutes)).isoformat(),
                duration_seconds=minutes * 60,
            )
        )
        buckets += [
            {
                "time": (begin + timedelta(minutes=step * 3)).isoformat(),
                "sum": 300,
                "count": 3,
                "min": 100,
                "max": 100,
            }
            for step in range(minutes // 3)
        ]
        resting.append({"time": begin.isoformat(), "value": float(50 + index)})
    return events, buckets, resting


def insights(client, cfg, query=""):
    return client.get(
        "/api/calendar/insights" + query,
        headers={"Authorization": "Bearer " + cfg.api_token},
    )


def test_insights_require_a_bearer_token_and_reject_unknown_parameters(setup):
    cfg, db, gemini, clock = setup
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        assert client.get("/api/calendar/insights").status_code == 401
        assert insights(client, cfg, "?focus=calendar").status_code == 422
        assert insights(client, cfg, "?period=91d").status_code == 422
        assert insights(client, cfg, "?period=month").status_code == 422
    gemini.generate.assert_not_called()


def test_a_period_without_events_returns_empty_sections_and_reads_no_metrics(setup):
    cfg, db, gemini, clock = setup
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        response = insights(client, cfg)
        assert response.status_code == 200
        body = response.json()
    assert body["period"] == {
        "start": "2026-03-03T08:00:00Z",
        "end": "2026-03-09T12:00:00Z",
        "timezone": cfg.timezone,
        "days": 7,
        "bucket_minutes": 1,
    }
    assert body["days_with_events"] == 0
    assert (body["daily_load"], body["series"], body["top_events"]) == ([], [], [])
    assert (body["correlations"], body["tercile_comparison"]) == ({}, {})
    assert body["time_of_day"]["morning"] == {"mean_hr_vs_resting_pct": None, "n": 0}
    assert body["caveats"]
    assert [call.args[0] for call in db.query.call_args_list] == ["Calendar Events"]
    db.fetch.assert_not_called()


def test_insights_report_load_series_and_correlations_over_the_period(setup):
    cfg, db, gemini, clock = setup
    events, buckets, resting = insight_rows()
    db.query.side_effect = stored(calendar=events, hr=buckets, resting=resting)
    db.fetch.return_value = {"RestingHR": resting}
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        body = insights(client, cfg, "?period=30d").json()

    assert body["period"]["days"] == 30 and body["period"]["bucket_minutes"] == 3
    assert body["days_with_events"] == INSIGHT_DAYS
    assert len(body["daily_load"]) == 14  # the last fortnight only
    assert body["daily_load"][-1] == {
        "date": "2026-03-08",
        "event_count": 1,
        "meeting_count": 1,
        "meeting_minutes": 48,
        "event_minutes": 48,
        "back_to_back_count": 0,
        "first_event_hour": 11,
        "last_event_hour": 11,
    }
    # Meeting minutes and the resting rate both climb by one a day.
    assert body["correlations"]["resting_hr"]["same_day"] == {
        "r": 1.0,
        "n": INSIGHT_DAYS,
        "insufficient_data": False,
    }
    assert body["correlations"]["resting_hr"]["next_day"]["n"] == INSIGHT_DAYS - 1
    terciles = body["tercile_comparison"]["resting_hr"]["same_day"]
    assert terciles["days"] == 6 and terciles["insufficient_data"] is False
    assert terciles["top_third_mean"] > terciles["bottom_third_mean"]
    assert len(body["series"]) == 1
    assert body["series"][0]["occurrences"] == INSIGHT_DAYS
    assert body["series"][0]["with_vitals"] == INSIGHT_DAYS
    assert body["time_of_day"]["morning"]["n"] == INSIGHT_DAYS
    assert body["time_of_day"]["evening"] == {"mean_hr_vs_resting_pct": None, "n": 0}
    # The quietest days carry the lowest resting rate, so their elevation is the steepest.
    assert [row["event_id"] for row in body["top_events"]] == [
        f"event-{index}" for index in range(5)
    ]
    assert body["top_events"][0]["mean_hr"] == 100
    assert body["caveats"]


def test_insights_caveat_lists_the_events_heart_rate_could_not_cover(setup):
    cfg, db, gemini, clock = setup
    events, buckets, resting = insight_rows()
    # Only the first meeting keeps its buckets, so the other eighteen cannot be read.
    db.query.side_effect = stored(calendar=events, hr=buckets[:10], resting=resting)
    db.fetch.return_value = {}
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        body = insights(client, cfg, "?period=30d").json()
    assert [row["event_id"] for row in body["top_events"]] == ["event-0"]
    assert body["series"][0]["with_vitals"] == 1
    assert body["correlations"] == {}
    assert any("coverage" in caveat for caveat in body["caveats"])
    assert f"{INSIGHT_DAYS - 1} of {INSIGHT_DAYS}" in " ".join(body["caveats"])


def test_insight_failures_reuse_the_health_error_codes_without_details(setup):
    cfg, db, gemini, clock = setup
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        for error, status, code in (
            (DataUnavailable("secret"), 503, "DATA_SERVICE_UNAVAILABLE"),
            (QueryLimitExceeded("secret"), 422, "HEALTH_QUERY_TOO_LARGE"),
        ):
            db.query.side_effect = error
            response = insights(client, cfg, "?period=30d")
            assert response.status_code == status
            assert response.json()["error"] == code
            assert "secret" not in response.text
