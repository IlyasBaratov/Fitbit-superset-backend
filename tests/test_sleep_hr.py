from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from app.scores.sleep import HeartRateSample, Interval, SleepSessionFeatures, SleepStageInterval
from app.scores.sleep_hr import (
    SoundSleepParameters,
    sleep_hr_epochs,
    sound_calibration_mae,
    sound_sleep_candidate,
)


def sample_session():
    start = datetime(2026, 10, 4, 8, 50, tzinfo=timezone.utc)
    return SleepSessionFeatures(
        wake_date=date(2026, 10, 4), session_id="s", start_time=start,
        end_time=start + timedelta(minutes=2), minutes_asleep=2,
        minutes_in_bed=2, sleep_goal_minutes=420, stages=(),
        short_awakenings=None, short_awakening_seconds=None,
        short_awakening_count=None,
    )


def test_epoch_median_rejects_spikes_and_sparse_minutes():
    session = sample_session()
    start = session.start_time
    samples = [HeartRateSample(start + timedelta(seconds=i * 3), 60) for i in range(9)]
    samples += [HeartRateSample(start + timedelta(seconds=30), 200)]
    samples += [HeartRateSample(start + timedelta(minutes=1, seconds=5), 70)]
    session = replace(
        session,
        end_time=start + timedelta(minutes=2),
        stages=(SleepStageInterval(start, start + timedelta(minutes=2), "light"),),
        short_awakenings=(Interval(start + timedelta(seconds=20), start + timedelta(seconds=30)),),
        heart_rate_samples=tuple(samples),
    )
    first, second = sleep_hr_epochs(session)
    assert first.sample_count == 10 and first.minute_hr == 60
    assert first.stage == "light" and first.is_short_awakening is True
    assert second.sample_count == 1 and second.minute_hr is None
    assert second.is_short_awakening is False


def test_epoch_partial_boundary_and_unknown_awakening_state():
    session = sample_session()
    start = session.start_time + timedelta(seconds=30)
    end = start + timedelta(seconds=90)
    samples = tuple(HeartRateSample(start + timedelta(seconds=i), 65) for i in range(10))
    session = replace(session, start_time=start, end_time=end,
                      stages=(SleepStageInterval(start, end, "deep"),),
                      heart_rate_samples=samples)
    epochs = sleep_hr_epochs(session)
    assert [epoch.minutes for epoch in epochs] == [0.5, 1]
    assert epochs[0].minute_hr == 65
    assert epochs[0].is_short_awakening is None


def test_sound_candidates_require_explicit_parameters_and_complete_data():
    session = sample_session()
    start = session.start_time
    samples = tuple(
        HeartRateSample(start + timedelta(minutes=minute, seconds=second), bpm)
        for minute, bpm in enumerate((60, 61))
        for second in range(10)
    )
    session = replace(
        session,
        stages=(SleepStageInterval(start, session.end_time, "light"),),
        short_awakenings=(),
        heart_rate_samples=samples,
    )
    epochs = sleep_hr_epochs(session)
    robust = SoundSleepParameters("robust", 1, 2)
    percentile = SoundSleepParameters("percentile", 100, 2)
    assert sound_sleep_candidate(epochs, robust).minutes == 2
    assert sound_sleep_candidate(epochs, percentile).minutes == 2
    assert sound_calibration_mae(((epochs, 1.0),), robust) == 1
    incomplete = replace(session, short_awakenings=None)
    result = sound_sleep_candidate(sleep_hr_epochs(incomplete), robust)
    assert result.minutes is None and result.unknown_minutes == 2
