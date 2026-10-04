"""Pure sleep feature tests; calibration labels are added in S10."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from statistics import mean, median
import pytest
from app.scores.sleep import (
    Interval,
    SleepSessionFeatures,
    SleepStageInterval,
    aware_utc,
    full_awakenings_count,
    interruption_minutes,
    normalize_sleep_days,
    restlessness_minutes,
    sleep_efficiency_percent,
    score_sleep_session,
    score_v01_raw,
    time_to_sound_sleep,
)


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


def sample_session(**changes):
    start = datetime(2026, 10, 4, 8, 50, tzinfo=timezone.utc)
    session = SleepSessionFeatures(
        wake_date=date(2026, 10, 4), session_id="s", start_time=start,
        end_time=start + timedelta(minutes=482), minutes_asleep=437,
        minutes_in_bed=482, sleep_goal_minutes=420, stages=(),
        short_awakenings=None, short_awakening_seconds=None,
        short_awakening_count=None,
    )
    return replace(session, **changes)


def stage(start, offset, minutes, name):
    beginning = start + timedelta(minutes=offset)
    return SleepStageInterval(beginning, beginning + timedelta(minutes=minutes), name)


def test_exact_efficiency_and_missing_denominator():
    assert sleep_efficiency_percent(sample_session()) == pytest.approx(90.6639004149)
    assert sleep_efficiency_percent(sample_session(minutes_in_bed=0)) is None
    assert sleep_efficiency_percent(sample_session(minutes_in_bed=None)) is None


def test_restlessness_uses_seconds_or_exact_interval_sum_and_never_missing_zero():
    session = sample_session(short_awakening_seconds=960)
    assert restlessness_minutes(session) == 16
    first = Interval(session.start_time, session.start_time + timedelta(minutes=8))
    overlapping = Interval(session.start_time + timedelta(minutes=4), session.start_time + timedelta(minutes=12))
    assert restlessness_minutes(replace(session, short_awakening_seconds=None, short_awakenings=(first, overlapping))) == 16
    assert restlessness_minutes(replace(session, short_awakenings=(first,))) is None
    assert restlessness_minutes(sample_session()) is None


def test_internal_awake_strict_five_minute_rule_and_edge_exclusion():
    start = sample_session().start_time
    stages = (
        stage(start, 0, 10, "awake"),
        stage(start, 10, 20, "light"),
        stage(start, 30, 5, "awake"),
        stage(start, 35, 20, "deep"),
        stage(start, 55, 33, "awake"),
        stage(start, 88, 20, "rem"),
        stage(start, 108, 10, "awake"),
    )
    session = sample_session(stages=stages)
    assert interruption_minutes(session) == 33
    assert full_awakenings_count(session) == 1
    stages = stages[:2] + (stage(start, 30, 5 + 1/60, "awake"),) + stages[3:]
    assert interruption_minutes(sample_session(stages=stages)) == pytest.approx(33 + 301/60)
    assert full_awakenings_count(sample_session(stages=stages)) == 2
    assert interruption_minutes(sample_session()) is None


def test_time_to_sound_sleep_uses_first_deep_rem_or_qualified_light():
    start = sample_session().start_time
    session = sample_session(stages=(
        stage(start, 0, 10, "awake"),
        stage(start, 10, 16, "light"),
        stage(start, 26, 16, "deep"),
        stage(start, 42, 20, "rem"),
    ))
    result = time_to_sound_sleep(session)
    assert result.minutes == 26
    assert result.method == "first_deep"
    assert "tts_stable_light_unvalidated" in result.flags
    rem_first = replace(session, stages=(stage(start, 5, 10, "rem"), stage(start, 26, 16, "deep")))
    assert time_to_sound_sleep(rem_first).minutes == 5
    stable_first = replace(session, stages=(stage(start, 0, 21, "light"), stage(start, 26, 16, "deep")))
    assert time_to_sound_sleep(stable_first, lambda *_: True).minutes == 0
    assert time_to_sound_sleep(stable_first, lambda *_: True).method == "stable_light"
    assert time_to_sound_sleep(stable_first, lambda *_: False).minutes == 26
    assert time_to_sound_sleep(sample_session()).minutes is None


def test_v01_oct4_score_and_missing_restlessness():
    start = sample_session().start_time
    session = sample_session(
        short_awakening_seconds=960,
        stages=(stage(start, 0, 10, "awake"), stage(start, 10, 16, "light"),
                stage(start, 26, 100, "deep"), stage(start, 126, 33, "awake"),
                stage(start, 159, 100, "light")),
    )
    result = score_sleep_session(session, time_to_sound_sleep(session))
    assert result.raw_score == pytest.approx(78.184)
    assert result.score == 78
    assert result.components["full_awakenings"]["count"] == 1
    assert result.components["sound_sleep"]["penalty"] is None
    missing = score_sleep_session(replace(session, short_awakening_seconds=None), time_to_sound_sleep(session))
    assert missing.score is None and missing.insufficient_data is True
    assert "missing_restlessness" in missing.flags


def test_seven_real_owner_score_labels_against_api_derived_features():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "sleep_score_google_calibration.json")
        .read_text(encoding="utf-8")
    )
    nights = fixture["nights"]
    assert [night["wake_date"] for night in nights] == [
        "2026-09-27", "2026-09-28", "2026-09-29", "2026-10-01",
        "2026-10-02", "2026-10-03", "2026-10-04",
    ]
    assert [night["sleep_score"] for night in nights] == [87, 84, 80, 84, 82, 72, 77]
    assert [night["observed_app_sound_sleep_minutes"] for night in nights] == [
        179, 145, 152, 155, 142, 162, 159,
    ]
    assert "2026-09-30" in fixture["excluded_wake_dates"]
    predicted, errors = [], []
    for night in nights:
        raw = night["derived_from_raw_api"]
        assert raw["restlessness_minutes"] == raw["short_awakening_seconds"] / 60
        assert raw["sleep_efficiency_percent"] == pytest.approx(
            100 * raw["minutes_asleep"] / raw["minutes_in_bed"]
        )
        value = score_v01_raw(
            max(0, fixture["model_goal_minutes"] - raw["minutes_asleep"]),
            raw["time_to_sound_sleep_minutes"], raw["restlessness_minutes"],
            raw["interruption_minutes"],
        )
        predicted.append(value)
        errors.append(value - night["sleep_score"])
    assert predicted == pytest.approx([88.336, 85.922, 80.792, 83.218, 79.164, 71.6, 78.184])
    assert mean(map(abs, errors)) == pytest.approx(1.3217142857)
    assert median(map(abs, errors)) == pytest.approx(1.184)
    assert max(map(abs, errors)) == pytest.approx(2.836)
    assert mean(errors) == pytest.approx(0.1737142857)
    oct4 = nights[-1]["derived_from_raw_api"]
    assert oct4["minutes_asleep"] == 437 and oct4["minutes_in_bed"] == 482
    assert oct4["short_awakening_seconds"] == 960
    assert oct4["interruption_minutes"] == 33
    assert oct4["full_awakenings_count"] == 1
    assert oct4["time_to_sound_sleep_minutes"] == 26
