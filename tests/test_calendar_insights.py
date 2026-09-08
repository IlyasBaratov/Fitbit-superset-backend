"""Daily meeting load and its correlation with the stored daily metrics (D7, D8)."""
from datetime import date, datetime, timedelta

import pytest

from app.calendar.insights import (
    MIN_CORRELATION_DAYS,
    MIN_SERIES_OCCURRENCES,
    MIN_TERCILE_DAYS,
    TOP_EVENT_COUNT,
    correlate,
    daily_load,
    daily_series,
    series_summary,
    tercile_comparison,
    time_of_day,
    top_events,
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


def vitals(elevation=10.0, recovery=-2.0, confounded=False, mean_hr=80.0):
    """An `event_vitals` result, as the read service hands it to the insights layer."""
    return {
        "mean_hr": mean_hr,
        "max_hr": mean_hr + 10,
        "sample_count": 12,
        "coverage_pct": 100,
        "hr_vs_resting_pct": elevation,
        "steps": 40,
        "steps_per_minute": 2,
        "movement_confounded": confounded,
        "pre30_mean_hr": 65,
        "post30_mean_hr": mean_hr + recovery,
        "recovery_delta": recovery,
    }


def measured(
    start,
    elevation=10.0,
    summary="Weekly sync",
    recurring="",
    minutes=60,
    attendees=3,
    event_id=None,
    **overrides,
):
    """A stored event row carrying the vitals computed for it, or `None` when unreadable."""
    row = event(start, minutes=minutes, attendees=attendees, event_id=event_id)
    row["summary"] = summary
    row["recurringEventId"] = recurring
    row["vitals"] = vitals(elevation, **overrides) if elevation is not None else None
    return row


def test_series_groups_instances_of_one_recurring_event():
    rows = [
        measured("2026-09-01T07:00:00+00:00", 10, summary="Standup", recurring="r1"),
        measured("2026-09-02T07:00:00+00:00", 20, summary="Standup (moved)", recurring="r1"),
        measured("2026-09-03T07:00:00+00:00", 30, summary="Standup", recurring="r1"),
    ]
    assert series_summary(rows) == [
        {
            "title": "Standup",
            "occurrences": 3,
            "with_vitals": 3,
            "mean_hr_vs_resting_pct": 20,
            "mean_recovery_delta": -2,
            "confounded_count": 0,
        }
    ]


def test_series_without_a_recurring_id_group_on_the_normalized_summary():
    rows = [
        measured("2026-09-01T07:00:00+00:00", 10, summary="Weekly  Sync"),
        measured("2026-09-02T07:00:00+00:00", 20, summary="  weekly sync "),
        measured("2026-09-03T07:00:00+00:00", 30, summary="Retro"),
    ]
    result = series_summary(rows)
    assert [(group["title"], group["occurrences"]) for group in result] == [
        ("Weekly Sync", 2),
        ("Retro", 1),
    ]


def test_untitled_one_off_events_stay_separate_groups():
    rows = [
        measured("2026-09-01T07:00:00+00:00", 10, summary="", event_id="e1"),
        measured("2026-09-02T07:00:00+00:00", 20, summary="", event_id="e2"),
    ]
    assert [group["occurrences"] for group in series_summary(rows)] == [1, 1]


def test_only_series_with_enough_usable_occurrences_are_ranked_by_elevation():
    rows = [
        measured(f"2026-09-0{day}T07:00:00+00:00", 5, summary="Standup", recurring="r1")
        for day in range(1, MIN_SERIES_OCCURRENCES + 1)
    ] + [
        measured("2026-09-05T07:00:00+00:00", 50, summary="Board review", recurring="r2"),
        measured("2026-09-06T07:00:00+00:00", 50, summary="Board review", recurring="r2"),
    ]
    # The steep pair sorts behind the ranked series despite the higher elevation.
    assert [group["title"] for group in series_summary(rows)] == ["Standup", "Board review"]


def test_series_ranking_puts_the_steepest_qualifying_group_first():
    rows = [
        measured(f"2026-09-0{day}T07:00:00+00:00", 5, summary="Standup", recurring="r1")
        for day in range(1, 4)
    ] + [
        measured(f"2026-09-0{day}T12:00:00+00:00", 40, summary="Sales call", recurring="r2")
        for day in range(1, 4)
    ]
    assert [group["title"] for group in series_summary(rows)] == ["Sales call", "Standup"]


def test_series_counts_unmeasured_and_confounded_occurrences_separately():
    rows = [
        measured("2026-09-01T07:00:00+00:00", 10, summary="Standup", recurring="r1"),
        measured("2026-09-02T07:00:00+00:00", 30, summary="Standup", recurring="r1", confounded=True),
        measured("2026-09-03T07:00:00+00:00", None, summary="Standup", recurring="r1"),
    ]
    assert series_summary(rows) == [
        {
            "title": "Standup",
            "occurrences": 3,
            "with_vitals": 2,
            "mean_hr_vs_resting_pct": 20,
            "mean_recovery_delta": -2,
            "confounded_count": 1,
        }
    ]


def test_series_skips_rows_without_a_usable_window():
    assert series_summary([{"EventId": "e1", "summary": "Broken"}]) == []
    assert series_summary(None) == []


def test_time_of_day_buckets_events_by_their_local_start_hour():
    rows = [
        measured("2026-09-01T07:00:00+00:00", 10),  # 09:00 Berlin
        measured("2026-09-01T09:00:00+00:00", 20),  # 11:00 Berlin, still morning
        measured("2026-09-01T11:00:00+00:00", 30),  # 13:00 Berlin
        measured("2026-09-01T15:00:00+00:00", 40),  # 17:00 Berlin
    ]
    assert time_of_day(rows, ZONE) == {
        "morning": {"mean_hr_vs_resting_pct": 15, "n": 2},
        "afternoon": {"mean_hr_vs_resting_pct": 30, "n": 1},
        "evening": {"mean_hr_vs_resting_pct": 40, "n": 1},
    }


def test_time_of_day_counts_only_events_with_an_elevation():
    rows = [
        measured("2026-09-01T07:00:00+00:00", None),  # no vitals at all
        {**measured("2026-09-01T08:00:00+00:00", 10), "vitals": vitals(None)},
    ]
    assert time_of_day(rows, ZONE)["morning"] == {"mean_hr_vs_resting_pct": None, "n": 0}
    assert time_of_day(None, ZONE)["evening"] == {"mean_hr_vs_resting_pct": None, "n": 0}


def test_top_events_returns_the_steepest_events_without_movement():
    rows = [
        measured(f"2026-09-0{index}T07:00:00+00:00", index, event_id=f"e{index}")
        for index in range(1, 8)
    ]
    rows.append(
        measured("2026-09-08T07:00:00+00:00", 99, event_id="walk", confounded=True)
    )
    result = top_events(rows)
    assert len(result) == TOP_EVENT_COUNT
    assert [row["event_id"] for row in result] == ["e7", "e6", "e5", "e4", "e3"]
    assert result[0] == {
        "event_id": "e7",
        "title": "Weekly sync",
        "start": datetime.fromisoformat("2026-09-07T07:00:00+00:00"),
        "duration_minutes": 60,
        "attendees": 3,
        "mean_hr": 80.0,
        "hr_vs_resting_pct": 7,
        "recovery_delta": -2.0,
    }


def test_top_events_ignores_events_without_vitals():
    rows = [
        measured("2026-09-01T07:00:00+00:00", None, event_id="e1"),
        measured("2026-09-02T07:00:00+00:00", 5, event_id="e2"),
    ]
    assert [row["event_id"] for row in top_events(rows)] == ["e2"]
    assert top_events(None) == []


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
