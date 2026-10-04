"""Pure sleep feature tests; calibration labels are added in S10."""

from datetime import date, datetime, timezone
import pytest
from app.scores.sleep import aware_utc, normalize_sleep_days


def test_normalization_uses_local_wake_date_and_processed_main_session():
    rows = [
        {"startTime": "2026-10-04T07:00:00Z", "endTime": "2026-10-04T08:00:00Z", "SleepSessionId": "nap", "isMainSleep": "false"},
        {"startTime": "2026-10-04T08:50:00Z", "endTime": "2026-10-04T16:52:00Z", "SleepSessionId": "main", "isMainSleep": "true", "isProcessed": True, "minutesAsleep": 437, "minutesInBed": 482, "shortAwakeningSeconds": 960, "shortAwakeningCount": 1},
        {"startTime": "2026-10-04T10:00:00Z", "endTime": "2026-10-04T13:00:00Z", "SleepSessionId": "other", "isMainSleep": "true", "minutesAsleep": 100},
    ]
    levels = [{"time": "2026-10-04T09:00:00Z", "SleepSessionId": "main", "stageName": "light", "duration_seconds": 960}]
    short = [{"time": "2026-10-04T09:01:00Z", "endTime": "2026-10-04T09:17:00Z", "SleepSessionId": "main", "duration_seconds": 960}]
    day = normalize_sleep_days(rows, levels, short, "America/Los_Angeles", 420)[date(2026, 10, 4)]
    assert day.session.session_id == "main"
    assert day.session.start_time == datetime(2026, 10, 4, 8, 50, tzinfo=timezone.utc)
    assert day.session.short_awakenings[0].seconds == 960
    assert day.session.stages[0].stage == "light"
    assert day.flags == ("multiple_main_sleep_sessions",)


def test_no_main_session_and_missing_short_intervals_are_not_zero():
    row = {"startTime": "2026-10-04T08:00:00Z", "endTime": "2026-10-04T09:00:00Z", "SleepSessionId": "s", "isMainSleep": "false"}
    selected = normalize_sleep_days([row], [], [], "America/Los_Angeles", 420)
    assert selected[date(2026, 10, 4)].session is None
    row["isMainSleep"] = "true"
    selected = normalize_sleep_days([row], [], [], "America/Los_Angeles", 420)
    assert selected[date(2026, 10, 4)].session.short_awakenings is None
    assert selected[date(2026, 10, 4)].session.short_awakening_seconds is None


def test_normalization_rejects_ambiguous_stored_timestamps():
    with pytest.raises(ValueError, match="timezone"):
        aware_utc("2026-10-04T08:50:00")
