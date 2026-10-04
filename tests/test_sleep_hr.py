from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from app.scores.sleep import HeartRateSample, Interval, SleepSessionFeatures, SleepStageInterval
from app.scores.sleep_hr import (
    SOUND_SLEEP_PARAMETERS,
    SleepHREpoch,
    SoundSleepParameters,
    sleep_hr_epochs,
    sound_calibration_mae,
    sound_sleep_candidate,
)
from app.scores.sleep_hr_calibration import SoundCalibrationNight, fit_sound_sleep_candidates


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
    missing_stage = (replace(epochs[0], stage=None), epochs[1])
    assert sound_sleep_candidate(missing_stage, robust).minutes is None


def test_calibration_skips_incomplete_hr_and_uses_explicit_observations():
    start = datetime(2026, 10, 4, tzinfo=timezone.utc)
    epochs = tuple(
        SleepHREpoch(start + timedelta(minutes=i), start + timedelta(minutes=i + 1),
                     20, 60, "deep", False, False)
        for i in range(3)
    )
    missing = (replace(epochs[0], minute_hr=None), *epochs[1:])
    fit = fit_sound_sleep_candidates(
        (SoundCalibrationNight("2026-10-04", epochs, 3),
         SoundCalibrationNight("2026-10-01", missing, 2)),
        alphas=(-1, 0), percentiles=(50,), betas=(0, 1),
    )
    assert fit.sample_count == 1
    assert fit.excluded_dates == ("2026-10-01",)
    assert fit.parameters == SoundSleepParameters("robust", -1, 0)
    assert fit.mae == 0 and fit.predictions == (("2026-10-04", 3, 3),)
    assert SOUND_SLEEP_PARAMETERS == SoundSleepParameters("robust", 0.3, 0.75)
