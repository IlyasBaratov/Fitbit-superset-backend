"""Research-only fitting of Sound Sleep HR rules to owner-observed minutes.

This module has no storage access and is never called by the score API.
"""

from dataclasses import dataclass
from statistics import median

from app.scores.sleep_hr import (
    SleepHREpoch,
    SoundSleepParameters,
    _percentile,
    sound_sleep_candidate,
)


@dataclass(frozen=True)
class SoundCalibrationNight:
    wake_date: str
    epochs: tuple[SleepHREpoch, ...]
    observed_minutes: float


@dataclass(frozen=True)
class SoundCalibrationFit:
    parameters: SoundSleepParameters
    sample_count: int
    excluded_dates: tuple[str, ...]
    mae: float
    median_absolute_error: float
    maximum_absolute_error: float
    signed_mean_error: float
    predictions: tuple[tuple[str, float, float], ...]


def _features(night: SoundCalibrationNight):
    epochs = night.epochs
    # Preserve the production classifier's missing-data rule when selecting rows.
    if sound_sleep_candidate(epochs, SoundSleepParameters("robust", 0, 0)).minutes is None:
        return None
    asleep = [epoch.minute_hr for epoch in epochs if epoch.stage in {"light", "deep", "rem"}]
    nightly_median = median(asleep)
    nightly_mad = median(abs(value - nightly_median) for value in asleep)
    eligible = []
    for index, epoch in enumerate(epochs):
        if epoch.stage not in {"light", "deep", "rem"}:
            continue
        window = [item.minute_hr for item in epochs[max(0, index - 2):index + 3]]
        center = median(window)
        rolling_mad = median(abs(value - center) for value in window)
        if not epoch.is_short_awakening and not epoch.is_long_interruption:
            eligible.append((epoch.minute_hr, rolling_mad, epoch.minutes))
    return asleep, nightly_median, 1.4826 * nightly_mad, eligible


def fit_sound_sleep_candidates(
    nights: tuple[SoundCalibrationNight, ...],
    *,
    alphas: tuple[float, ...],
    percentiles: tuple[float, ...],
    betas: tuple[float, ...],
) -> SoundCalibrationFit:
    """Grid-search documented models; use only nights with complete raw epochs.

    Equal MAE prefers the simpler robust rule, then the smallest beta and
    smallest low-HR parameter. These tie breaks are deterministic, not evidence
    that the selected parameters reflect Google's classifier.
    """
    if not nights or not betas or not (alphas or percentiles):
        raise ValueError("Calibration requires observations and a parameter grid")
    prepared = [(night, _features(night)) for night in nights]
    usable = [(night, features) for night, features in prepared if features is not None]
    excluded = tuple(night.wake_date for night, features in prepared if features is None)
    if not usable:
        raise ValueError("No complete raw HR nights to calibrate")
    best = None
    for model, lows in (("robust", alphas), ("percentile", percentiles)):
        for low in lows:
            limits = [
                center + low * scale if model == "robust" else _percentile(asleep, low)
                for _, (asleep, center, scale, _) in usable
            ]
            for beta in betas:
                predictions = tuple(
                    (
                        night.wake_date,
                        sum(minutes for hr, mad, minutes in features[3]
                            if hr <= limit and mad <= beta),
                        night.observed_minutes,
                    )
                    for (night, features), limit in zip(usable, limits)
                )
                errors = [predicted - observed for _, predicted, observed in predictions]
                absolute = [abs(error) for error in errors]
                mae = sum(absolute) / len(absolute)
                rank = (mae, 0 if model == "robust" else 1, beta, low)
                if best is None or rank < best[0]:
                    best = (rank, SoundSleepParameters(model, low, beta), predictions, errors, absolute)
    _, parameters, predictions, errors, absolute = best
    return SoundCalibrationFit(
        parameters=parameters,
        sample_count=len(usable),
        excluded_dates=excluded,
        mae=sum(absolute) / len(absolute),
        median_absolute_error=median(absolute),
        maximum_absolute_error=max(absolute),
        signed_mean_error=sum(errors) / len(errors),
        predictions=predictions,
    )
