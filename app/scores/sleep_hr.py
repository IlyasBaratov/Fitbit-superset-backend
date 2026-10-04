"""Minute HR epochs from raw sleep-window samples, without I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from statistics import median
from typing import Literal
from app.scores.sleep import SleepSessionFeatures, long_internal_awake_bouts


# Normal observed cadence on seven owner nights was at least 20 samples/minute
# except missing minutes. Ten distinguishes a sparse minute without demanding
# perfect sensor coverage; it is a data-quality cutoff, not a Sound Sleep rule.
MIN_HR_SAMPLES_PER_MINUTE = 10


@dataclass(frozen=True)
class SleepHREpoch:
    start: datetime
    end: datetime
    sample_count: int
    minute_hr: float | None
    stage: str | None
    is_short_awakening: bool | None
    is_long_interruption: bool | None

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


def _overlaps(start: datetime, end: datetime, other) -> bool:
    return other.start < end and other.end > start


def sleep_hr_epochs(
    session: SleepSessionFeatures,
    min_samples_per_minute: int = MIN_HR_SAMPLES_PER_MINUTE,
) -> tuple[SleepHREpoch, ...]:
    """Use only valid samples inside each UTC minute and the sleep session."""
    if min_samples_per_minute < 1:
        raise ValueError("Minimum HR samples must be positive")
    raw = sorted(
        (
            sample for sample in session.heart_rate_samples
            if session.start_time <= sample.timestamp < session.end_time
            and isfinite(sample.bpm) and sample.bpm > 0
        ),
        key=lambda sample: sample.timestamp,
    )
    long_awake = long_internal_awake_bouts(session)
    epochs = []
    cursor = session.start_time.replace(second=0, microsecond=0)
    index = 0
    while cursor < session.end_time:
        beginning = max(cursor, session.start_time)
        ending = min(cursor + timedelta(minutes=1), session.end_time)
        while index < len(raw) and raw[index].timestamp < beginning:
            index += 1
        values = []
        while index < len(raw) and raw[index].timestamp < ending:
            values.append(raw[index].bpm)
            index += 1
        covering = [
            item.stage for item in session.stages
            if item.start <= beginning and item.end >= ending
        ]
        stage = covering[0] if len(covering) == 1 else None
        short = (
            None if session.short_awakenings is None
            else any(_overlaps(beginning, ending, item) for item in session.short_awakenings)
        )
        interrupted = (
            None if long_awake is None
            else any(_overlaps(beginning, ending, item) for item in long_awake)
        )
        epochs.append(
            SleepHREpoch(
                start=beginning,
                end=ending,
                sample_count=len(values),
                minute_hr=median(values) if len(values) >= min_samples_per_minute else None,
                stage=stage,
                is_short_awakening=short,
                is_long_interruption=interrupted,
            )
        )
        cursor += timedelta(minutes=1)
    return tuple(epochs)


@dataclass(frozen=True)
class SoundSleepParameters:
    low_hr_model: Literal["robust", "percentile"]
    low_hr_parameter: float  # alpha for robust, percentile q for percentile.
    steady_hr_beta: float


@dataclass(frozen=True)
class SoundSleepEstimate:
    minutes: float | None
    eligible_minutes: float
    unknown_minutes: float
    method: str


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def sound_sleep_candidate(
    epochs: tuple[SleepHREpoch, ...], params: SoundSleepParameters
) -> SoundSleepEstimate:
    """Evaluate an explicitly supplied experimental HR rule; never choose a default."""
    if params.low_hr_model not in {"robust", "percentile"}:
        raise ValueError("Unknown low-HR model")
    if params.low_hr_model == "percentile" and not 0 <= params.low_hr_parameter <= 100:
        raise ValueError("Percentile must be between 0 and 100")
    if not isfinite(params.low_hr_parameter) or not isfinite(params.steady_hr_beta) or params.steady_hr_beta < 0:
        raise ValueError("Invalid Sound Sleep parameter")
    asleep = [epoch for epoch in epochs if epoch.stage in {"light", "deep", "rem"}]
    method = f"hr_classifier_v1_{params.low_hr_model}"
    eligible = sum(epoch.minutes for epoch in asleep)
    if not asleep:
        return SoundSleepEstimate(None, 0, 0, method)
    unknown = sum(
        epoch.minutes for index, epoch in enumerate(epochs)
        if epoch.stage in {"light", "deep", "rem"}
        and (
            epoch.minute_hr is None
            or epoch.is_short_awakening is None
            or epoch.is_long_interruption is None
            or any(item.minute_hr is None for item in epochs[max(0, index - 2):index + 3])
        )
    )
    if unknown:
        return SoundSleepEstimate(None, eligible, unknown, method)
    values = [epoch.minute_hr for epoch in asleep]
    nightly_median = median(values)
    nightly_mad = median(abs(value - nightly_median) for value in values)
    low_limit = (
        nightly_median + params.low_hr_parameter * 1.4826 * nightly_mad
        if params.low_hr_model == "robust"
        else _percentile(values, params.low_hr_parameter)
    )
    minutes = 0.0
    for index, epoch in enumerate(epochs):
        if epoch.stage not in {"light", "deep", "rem"}:
            continue
        window = [item.minute_hr for item in epochs[max(0, index - 2):index + 3]]
        rolling_median = median(window)
        rolling_mad = median(abs(value - rolling_median) for value in window)
        if (
            not epoch.is_short_awakening
            and not epoch.is_long_interruption
            and epoch.minute_hr <= low_limit
            and rolling_mad <= params.steady_hr_beta
        ):
            minutes += epoch.minutes
    return SoundSleepEstimate(minutes, eligible, 0, method)


def sound_calibration_mae(
    nights: tuple[tuple[tuple[SleepHREpoch, ...], float], ...],
    params: SoundSleepParameters,
) -> float | None:
    """Research helper requiring independently verified Sound Sleep targets."""
    errors = []
    for epochs, observed_minutes in nights:
        predicted = sound_sleep_candidate(epochs, params).minutes
        if predicted is None:
            return None
        errors.append(abs(predicted - observed_minutes))
    return sum(errors) / len(errors) if errors else None
