"""Minute HR epochs from raw sleep-window samples, without I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from statistics import median
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
