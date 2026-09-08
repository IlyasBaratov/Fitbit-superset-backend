"""Daily meeting load and its correlation with the stored daily metrics (D7, D8)."""
from datetime import date, datetime, timedelta

import pytest

from app.calendar.insights import (
    MIN_CORRELATION_DAYS,
    MIN_TERCILE_DAYS,
    correlate,
    daily_load,
    daily_series,
    tercile_comparison,
)

ZONE = "Europe/Berlin"
FIRST = date(2026, 9, 1)


def event(start, minutes=60, attendees=3, event_id=None):
    """A stored `Calendar Events` row, as `usable_events` hands it over."""
    begin = datetime.fromisoformat(start)
    return {
        "time": start,
        "CalendarId": "primary",
        "EventId": event_id or start,
        "summary": "Weekly sync",
        "startTime": start,
        "endTime": (begin + timedelta(minutes=minutes)).isoformat(),
        "duration_seconds": minutes * 60,
        "attendees": attendees,
        "status": "confirmed",
    }


def load(values, first=FIRST):
    """Synthetic `daily_load` output; only `meeting_minutes` drives the statistics."""
    return {
        (first + timedelta(days=index)).isoformat(): {"meeting_minutes": value}
        for index, value in enumerate(values)
    }


def series(values, first=FIRST):
    return {
        (first + timedelta(days=index)).isoformat(): value
        for index, value in enumerate(values)
    }


MINUTES = [(index * 37) % 101 for index in range(30)]


def test_daily_load_counts_events_meetings_and_minutes_per_local_day():
    rows = [
        event("2026-09-01T07:00:00+00:00", minutes=60),
        event("2026-09-01T08:05:00+00:00", minutes=30),
        event("2026-09-01T12:00:00+00:00", minutes=45, attendees=0),
    ]
    result = daily_load(rows, ZONE)
    assert list(result) == ["2026-09-01"]
    assert result["2026-09-01"] == {
        "event_count": 3,
        "meeting_count": 2,
        "meeting_minutes": 90,
        "event_minutes": 135,
        "back_to_back_count": 1,
        "first_event_hour": 9,  # 07:00 UTC is 09:00 in Berlin
        "last_event_hour": 14,
    }


def test_back_to_back_counts_gaps_up_to_the_threshold_only():
    rows = [
        event("2026-09-01T07:00:00+00:00", minutes=60),
        event("2026-09-01T08:05:00+00:00", minutes=30),  # 5 minute gap
        event("2026-09-01T08:41:00+00:00", minutes=30),  # 6 minute gap
        event("2026-09-01T09:00:00+00:00", minutes=30),  # overlapping
    ]
    assert daily_load(rows, ZONE)["2026-09-01"]["back_to_back_count"] == 2


def test_days_are_local_so_a_late_event_belongs_to_the_next_day():
    rows = [event("2026-09-01T22:30:00+00:00", minutes=30)]
    assert list(daily_load(rows, ZONE)) == ["2026-09-02"]
    assert daily_load(rows, ZONE)["2026-09-02"]["first_event_hour"] == 0.5


def test_daily_load_skips_rows_without_a_usable_window():
    assert daily_load([{"EventId": "e1"}], ZONE) == {}
    assert daily_load(None, ZONE) == {}


def test_daily_series_takes_the_daily_maps_analyze_already_computed():
    metrics = {
        "resting_hr": {"unit": "bpm", "daily": {"2026-09-01": 58}},
        "sleep_hours": {"unit": "hours", "daily": {}},
        "weight": {"unit": "kg", "daily": {"2026-09-01": 70}},
    }
    assert daily_series(metrics) == {"resting_hr": {"2026-09-01": 58}}
    assert daily_series(None) == {}


def test_a_perfect_linear_relation_correlates_to_one():
    metrics = {"resting_hr": series([3 * value + 7 for value in MINUTES])}
    result = correlate(load(MINUTES), metrics)
    assert result["resting_hr"]["same_day"] == {"r": 1.0, "n": 30, "insufficient_data": False}
    assert correlate(load(MINUTES), {"hrv_rmssd": series([-value for value in MINUTES])})[
        "hrv_rmssd"
    ]["same_day"]["r"] == -1.0


def test_a_next_morning_metric_correlates_on_the_shifted_day():
    # Every day's sleep mirrors the meeting load of the day before.
    metrics = {"sleep_hours": series(MINUTES, first=FIRST + timedelta(days=1))}
    result = correlate(load(MINUTES), metrics)["sleep_hours"]
    assert result["next_day"] == {"r": 1.0, "n": 30, "insufficient_data": False}
    assert result["same_day"]["n"] == 29
    assert result["same_day"]["r"] < 1.0


def test_too_few_paired_days_report_insufficient_data():
    short = MINUTES[: MIN_CORRELATION_DAYS - 1]
    result = correlate(load(short), {"steps": series(short)})
    assert result["steps"]["same_day"] == {
        "r": None,
        "n": MIN_CORRELATION_DAYS - 1,
        "insufficient_data": True,
    }


def test_a_metric_that_never_moves_has_no_correlation():
    result = correlate(load(MINUTES), {"breathing_rate": series([14] * 30)})
    assert result["breathing_rate"]["same_day"] == {"r": None, "n": 30, "insufficient_data": False}


def test_correlations_cover_the_metrics_with_data_only():
    result = correlate(load(MINUTES), {"steps": series(MINUTES), "sleep_hours": {}})
    assert set(result) == {"steps"}
    assert correlate({}, {"steps": series(MINUTES)})["steps"]["same_day"]["n"] == 0


def test_terciles_compare_the_busiest_and_quietest_days():
    minutes = [10 * (index + 1) for index in range(12)]
    metric = [50 + index for index in range(12)]
    result = tercile_comparison(load(minutes), {"resting_hr": series(metric)})
    assert result["resting_hr"]["same_day"] == {
        "days": 4,
        "top_third_mean": 59.5,  # days 9..12
        "bottom_third_mean": 51.5,  # days 1..4
        "top_third_meeting_minutes": 105,
        "bottom_third_meeting_minutes": 25,
        "difference": 8.0,
        "percent": pytest.approx(8 / 51.5 * 100, abs=5e-4),
        "insufficient_data": False,
    }


def test_a_tercile_thinner_than_the_minimum_reports_insufficient_data():
    days = 3 * MIN_TERCILE_DAYS - 1
    result = tercile_comparison(load(MINUTES[:days]), {"steps": series(MINUTES[:days])})
    assert result["steps"]["same_day"] == {
        "days": MIN_TERCILE_DAYS - 1,
        "top_third_mean": None,
        "bottom_third_mean": None,
        "top_third_meeting_minutes": None,
        "bottom_third_meeting_minutes": None,
        "difference": None,
        "percent": None,
        "insufficient_data": True,
    }


def test_terciles_shift_with_the_metric_like_the_correlations():
    minutes = [10 * (index + 1) for index in range(12)]
    metric = series([50 + index for index in range(12)], first=FIRST + timedelta(days=1))
    result = tercile_comparison(load(minutes), {"hrv_rmssd": metric})["hrv_rmssd"]
    assert result["next_day"]["top_third_mean"] == 59.5
    assert result["next_day"]["days"] == 4
    assert result["same_day"]["days"] == 3
    assert result["same_day"]["insufficient_data"] is True


def test_load_and_correlations_line_up_end_to_end():
    events, metric = [], []
    for index in range(30):
        day = FIRST + timedelta(days=index)
        events.append(
            event(f"{day.isoformat()}T07:00:00+00:00", minutes=30 + index, event_id=f"e{index}")
        )
        metric.append(50 + index)
    result = correlate(daily_load(events, ZONE), {"resting_hr": series(metric)})
    assert result["resting_hr"]["same_day"]["r"] == 1.0
