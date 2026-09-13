"""Per-event vitals: bucket arithmetic, coverage floors and movement confounds (D6, D7)."""
from datetime import datetime, timedelta

import pytest

from app.calendar.vitals import (
    CONTEXT_MINUTES,
    MIN_COVERAGE_PCT,
    MIN_EVENT_MINUTES,
    MOVEMENT_STEPS_PER_MINUTE,
    bucket_minutes,
    event_vitals,
    usable_events,
)

START = "2026-09-01T09:00:00+00:00"


def event(event_id="e1", start=START, minutes=60, **overrides):
    begin = datetime.fromisoformat(start)
    row = {
        "time": start,
        "CalendarId": "primary",
        "EventId": event_id,
        "summary": "Weekly sync",
        "startTime": start,
        "endTime": (begin + timedelta(minutes=minutes)).isoformat(),
        "duration_seconds": minutes * 60,
        "status": "confirmed",
        "eventType": "default",
        "transparency": "opaque",
        "attendees": 3,
        "isAllDay": False,
        "updated": "2026-09-01T08:00:00+00:00",
    }
    row.update(overrides)
    return row


def buckets(first, samples, width=10):
    """Consecutive `width`-minute aggregate rows, one (sum, count) pair each."""
    begin = datetime.fromisoformat(first)
    return [
        {
            "time": (begin + timedelta(minutes=index * width)).isoformat(),
            "sum": total,
            "count": count,
            "min": total / count,
            "max": total / count,
        }
        for index, (total, count) in enumerate(samples)
    ]


def test_bucket_minutes_keeps_every_period_under_the_row_cap():
    assert bucket_minutes(1) == 1
    assert bucket_minutes(7) == 1
    assert bucket_minutes(30) == 3
    assert bucket_minutes(90) == 7
    assert all(days * 1440 / bucket_minutes(days) <= 20000 for days in range(1, 191))


def test_mean_is_weighted_by_sample_count_over_covered_buckets():
    vitals, notes = event_vitals(
        event(),
        buckets(START, [(200, 2), (90, 1), (90, 1), (90, 1), (90, 1), (90, 1)]),
        [],
        [],
        resting_hr=60,
        bucket_minutes=10,
    )
    assert vitals["mean_hr"] == pytest.approx(650 / 7, abs=5e-5)
    assert vitals["sample_count"] == 7
    assert vitals["coverage_pct"] == 100
    assert vitals["max_hr"] == 100
    assert vitals["hr_vs_resting_pct"] == pytest.approx((650 / 7 - 60) / 60 * 100, abs=5e-4)
    assert notes == []


def test_a_bucket_counts_for_the_window_holding_its_midpoint():
    vitals, _ = event_vitals(
        event(minutes=20),
        buckets("2026-09-01T08:50:00+00:00", [(60, 1), (100, 1), (110, 1), (80, 1)]),
        [],
        [],
        resting_hr=None,
        bucket_minutes=10,
    )
    # 08:50 midpoint 08:55 -> pre-window, 09:20 midpoint 09:25 -> post-window.
    assert vitals["mean_hr"] == 105
    assert vitals["pre30_mean_hr"] == 60
    assert vitals["post30_mean_hr"] == 80
    assert vitals["recovery_delta"] == -25
    assert vitals["hr_vs_resting_pct"] is None
    assert vitals["coverage_pct"] == 100


def test_context_windows_stop_at_the_configured_distance():
    far = datetime.fromisoformat(START) - timedelta(minutes=CONTEXT_MINUTES + 20)
    vitals, _ = event_vitals(
        event(minutes=20),
        buckets(far.isoformat(), [(50, 1)]) + buckets(START, [(100, 1), (100, 1)]),
        [],
        [],
        resting_hr=None,
        bucket_minutes=10,
    )
    assert vitals["pre30_mean_hr"] is None
    assert vitals["post30_mean_hr"] is None
    assert vitals["recovery_delta"] is None


def test_step_rate_above_the_threshold_flags_movement():
    minutes, hr = 20, buckets(START, [(100, 1), (100, 1)])
    walking, _ = event_vitals(
        event(minutes=minutes),
        hr,
        buckets(START, [(300, 1), (300, 1)]),
        [],
        resting_hr=60,
        bucket_minutes=10,
    )
    assert walking["steps"] == 600
    assert walking["steps_per_minute"] == 30
    assert walking["movement_confounded"] is True

    seated, notes = event_vitals(
        event(minutes=minutes),
        hr,
        buckets(START, [(50, 1), (50, 1)]),
        [],
        resting_hr=60,
        bucket_minutes=10,
    )
    assert seated["steps_per_minute"] == 5
    assert seated["steps_per_minute"] < MOVEMENT_STEPS_PER_MINUTE
    assert seated["movement_confounded"] is False
    assert notes == []


def test_overlapping_workout_flags_movement_without_step_buckets():
    vitals, notes = event_vitals(
        event(minutes=20),
        buckets(START, [(100, 1), (100, 1)]),
        [],
        [
            {
                "time": "2026-09-01T09:10:00+00:00",
                "ActivityId": "a1",
                "ActivityName": "Walk",
                "duration": 1800,
            }
        ],
        resting_hr=60,
        bucket_minutes=10,
    )
    assert vitals["steps"] is None
    assert vitals["movement_confounded"] is True
    assert any("movement" in note.lower() for note in notes)


def test_workout_outside_the_event_does_not_flag_movement():
    vitals, _ = event_vitals(
        event(minutes=20),
        buckets(START, [(100, 1), (100, 1)]),
        [],
        [{"time": "2026-09-01T09:20:00+00:00", "duration": 600}],
        resting_hr=60,
        bucket_minutes=10,
    )
    assert vitals["movement_confounded"] is False


def test_thin_coverage_yields_no_vitals_and_a_note():
    vitals, notes = event_vitals(
        event(),
        buckets(START, [(100, 1), (100, 1)]),
        [],
        [],
        resting_hr=60,
        bucket_minutes=10,
    )
    assert vitals is None
    assert len(notes) == 1
    assert str(MIN_COVERAGE_PCT) in notes[0]


def test_missing_resting_baseline_is_reported_as_a_note():
    vitals, notes = event_vitals(
        event(minutes=20),
        buckets(START, [(100, 1), (100, 1)]),
        [],
        [],
        resting_hr=None,
        bucket_minutes=10,
    )
    assert vitals["hr_vs_resting_pct"] is None
    assert any("resting" in note.lower() for note in notes)


def test_event_without_an_end_has_no_vitals():
    row = event()
    row.pop("endTime")
    row.pop("duration_seconds")
    assert event_vitals(row, [], [], [], resting_hr=60) == (None, ["Event has no usable start and end."])


def test_usable_events_keeps_the_newest_row_per_event():
    stale = event(summary="Old title", updated="2026-09-01T08:00:00+00:00")
    fresh = event(
        start="2026-09-01T11:00:00+00:00",
        summary="Moved",
        updated="2026-09-01T10:00:00+00:00",
    )
    assert [row["summary"] for row in usable_events([fresh, stale])] == ["Moved"]
    assert [row["summary"] for row in usable_events([stale, fresh])] == ["Moved"]


def test_usable_events_drops_events_that_cannot_be_read():
    rows = [
        event("cancelled", status="cancelled"),
        event("all-day", isAllDay=True),
        event("free", transparency="transparent"),
        event("short", minutes=MIN_EVENT_MINUTES - 1),
        event("kept", start="2026-09-01T07:00:00+00:00"),
    ]
    assert [row["EventId"] for row in usable_events(rows)] == ["kept"]


def test_a_newer_cancellation_removes_the_event_entirely():
    rows = [
        event(updated="2026-09-01T08:00:00+00:00"),
        event(status="cancelled", updated="2026-09-01T12:00:00+00:00"),
    ]
    assert usable_events(rows) == []


def test_usable_events_are_ordered_by_start():
    later, earlier = event("late", start="2026-09-01T15:00:00+00:00"), event("early")
    assert [row["EventId"] for row in usable_events([later, earlier])] == ["early", "late"]
