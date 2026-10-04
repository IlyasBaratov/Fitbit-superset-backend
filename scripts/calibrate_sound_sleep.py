"""Fit experimental Sound Sleep rules against local raw HR and owner app labels.

Run ``python -m scripts.calibrate_sound_sleep`` from the repository root with
the usual API/Influx environment (INFLUXDB_HOST should be reachable).
The script prints aggregate fit results only; it never exports raw HR samples.
"""

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.core.config import Settings
from app.scores.sleep import HeartRateSample, aware_utc, normalize_sleep_days
from app.scores.sleep_hr import sleep_hr_epochs, sound_sleep_candidate
from app.scores.sleep_hr_calibration import SoundCalibrationNight, fit_sound_sleep_candidates
from app.storage.influx.queries import InfluxService


FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/sleep_score_google_calibration.json"


def main():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    labels = fixture["nights"]
    dates = [date.fromisoformat(row["wake_date"]) for row in labels]
    settings = Settings.from_env()
    repository = InfluxService(settings)
    try:
        start = datetime.combine(min(dates) - timedelta(days=2), datetime.min.time(), timezone.utc)
        end = datetime.combine(max(dates) + timedelta(days=2), datetime.min.time(), timezone.utc)
        selected = normalize_sleep_days(
            repository.query("Sleep Summary", start, end),
            repository.query("Sleep Levels", start, end),
            repository.query("Sleep Short Awakenings", start, end),
            settings.timezone, settings.sleep_goal_minutes,
        )
        nights = []
        missing_sessions = []
        for row in labels:
            wake_date = date.fromisoformat(row["wake_date"])
            choice = selected.get(wake_date)
            if choice is None or choice.session is None:
                missing_sessions.append(row["wake_date"])
                continue
            session = choice.session
            raw = repository.query_raw_sleep_heart_rate(session.start_time, session.end_time)
            samples = tuple(
                HeartRateSample(aware_utc(point["time"]), float(point["value"]))
                for point in raw
            )
            epochs = sleep_hr_epochs(replace(session, heart_rate_samples=samples))
            nights.append(SoundCalibrationNight(
                row["wake_date"], epochs, float(row["observed_app_sound_sleep_minutes"])
            ))
        alphas = tuple(index / 20 for index in range(-40, 41))
        percentiles = tuple(range(101))
        betas = tuple(index / 4 for index in range(41))
        fit = fit_sound_sleep_candidates(
            tuple(nights), alphas=alphas, percentiles=percentiles, betas=betas
        )
        print("Selected parameters:", fit.parameters)
        print("Complete fitting nights:", fit.sample_count)
        print("Incomplete HR/wake dates:", ", ".join(fit.excluded_dates) or "none")
        print("Missing session dates:", ", ".join(missing_sessions) or "none")
        print("In-sample MAE/median/max/signed mean (minutes):",
              fit.mae, fit.median_absolute_error, fit.maximum_absolute_error,
              fit.signed_mean_error)
        for wake_date, predicted, observed in fit.predictions:
            print(wake_date, "predicted", predicted, "observed", observed)
        for night in nights:
            predicted = sound_sleep_candidate(night.epochs, fit.parameters).minutes
            if predicted is not None:
                assert predicted == next(value for day, value, _ in fit.predictions
                                         if day == night.wake_date)
    finally:
        repository.close()


if __name__ == "__main__":
    main()
