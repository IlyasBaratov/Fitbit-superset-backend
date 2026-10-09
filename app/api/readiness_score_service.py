"""Stored health reads and provenance-aware Readiness response composition."""

from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
import json
import math
from pathlib import Path

import pytz
from pydantic import ValidationError

from app.api.health_service import resolve_interval
from app.api.schemas.scores import ReadinessScoreDay, ReadinessScoreResponse
from app.core.exceptions import DataUnavailable, QueryLimitExceeded
from app.errors import APIError
from app.scores.readiness import READINESS_MODEL_VERSION, readiness_v03
from app.scores.sleep import aware_utc, normalize_sleep_days


OBSERVED_PATH = Path(__file__).resolve().parents[1] / "scores" / "data" / "readiness_observed_v1.json"
CAVEATS = [
    "Historical dates explicitly labeled as observed_google_health are real owner-provided Google Health readiness facts.",
    "Unobserved dates are calculated by the experimental readiness-emulator-v0.3 from stored HRV, resting heart rate and recent sleep duration.",
    "Calculated scores are not Google's or Fitbit's proprietary algorithm and are not a medical assessment.",
]


def load_observed_readiness() -> dict[date, int]:
    """Validate the versioned owner observation dataset; labels never enter model inputs."""
    document = json.loads(OBSERVED_PATH.read_text(encoding="utf-8"))
    if document.get("version") != "readiness-observed-v1":
        raise ValueError("Invalid observation dataset version")
    observations = document.get("observations")
    if not isinstance(observations, list):
        raise ValueError("Invalid observation dataset")
    values: dict[date, int] = {}
    for row in observations:
        if not isinstance(row, dict):
            raise ValueError("Invalid observation record")
        day = date.fromisoformat(row["date"])
        score = row["score"]
        if (
            day in values or isinstance(score, bool) or not isinstance(score, int)
            or not 1 <= score <= 100
            or row.get("source") != "google_health_owner_observation"
            or row.get("observed") is not True
        ):
            raise ValueError("Invalid observation record")
        values[day] = score
    return values


def _valid_value(value, *, positive: bool) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or (parsed <= 0 if positive else parsed < 0):
        return None
    return parsed


def _latest_daily(rows, field: str, zone) -> dict[date, float]:
    latest: dict[date, tuple[datetime, float]] = {}
    for row in rows:
        moment = aware_utc(row["time"])
        value = _valid_value(row.get(field), positive=True)
        if value is None:
            continue
        day = moment.astimezone(zone).date()
        if day not in latest or moment > latest[day][0]:
            latest[day] = (moment, value)
    return {day: item[1] for day, item in latest.items()}


def _main_sleep_minutes(rows, zone_name: str, goal: float, end: datetime) -> dict[date, float]:
    # Filter invalid duration fields, then reuse Sleep Score's processed-main-session ranking.
    valid = [row for row in rows if _valid_value(row.get("minutesAsleep"), positive=False) is not None]
    choices = normalize_sleep_days(valid, [], [], zone_name, goal)
    return {
        day: selection.session.minutes_asleep
        for day, selection in choices.items()
        if selection.session is not None and selection.session.end_time <= end
    }


class ReadinessScoreReadService:
    def __init__(self, settings, repository, clock=None):
        self.settings, self.repository = settings, repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def read(self, period: str | None = None) -> ReadinessScoreResponse:
        start, end, days = resolve_interval(self.settings, self.clock, period)
        zone = pytz.timezone(self.settings.timezone)
        first = start.astimezone(zone).date()
        context_date = first - timedelta(days=30)
        context_start = zone.localize(datetime.combine(context_date, time.min)).astimezone(
            timezone.utc
        )
        try:
            observations = load_observed_readiness()
            hrv_rows = self.repository.query("HRV", context_start, end)
            rhr_rows = self.repository.query("RestingHR", context_start, end)
            sleep_rows = self.repository.query("Sleep Summary", context_start, end)
            hrv = _latest_daily(hrv_rows, "dailyRmssd", zone)
            rhr = _latest_daily(rhr_rows, "value", zone)
            sleep = _main_sleep_minutes(
                sleep_rows, self.settings.timezone, self.settings.sleep_goal_minutes, end
            )
            output = []
            for offset in range(days):
                day = first + timedelta(days=offset)
                result = readiness_v03(day, hrv, rhr, sleep, self.settings.sleep_goal_minutes)
                observed = observations.get(day)
                if observed is not None:
                    public_score = observed
                    source, confidence = "observed_google_health", "observed_fact"
                elif result.calculated_score is not None:
                    public_score = result.calculated_score
                    source = "calculated_v0.3"
                    confidence = (
                        "experimental_partial" if any(flag in result.flags for flag in (
                            "partial_hrv_balance_window", "partial_sleep_window"
                        )) else "experimental"
                    )
                else:
                    public_score = None
                    source, confidence = "insufficient", "insufficient"
                output.append(ReadinessScoreDay(
                    date=day, score=public_score, source=source, confidence=confidence,
                    observed_score=observed,
                    calculated_score=result.calculated_score,
                    calculated_raw_score=result.calculated_raw_score,
                    calculation_insufficient_data=result.calculation_insufficient_data,
                    hrv_baseline_days=result.hrv_baseline_days,
                    rhr_baseline_days=result.rhr_baseline_days,
                    components=asdict(result.components), flags=list(result.flags),
                ))
            return ReadinessScoreResponse(
                start=start, end=end, timezone=self.settings.timezone,
                model_version=READINESS_MODEL_VERSION, days=output, caveats=CAVEATS,
            )
        except QueryLimitExceeded:
            raise APIError(
                "HEALTH_QUERY_TOO_LARGE",
                "Requested data exceeds the safe query limit; use a shorter period.", 422,
            ) from None
        except (DataUnavailable, ValidationError, KeyError, ValueError, TypeError, OSError):
            raise APIError(
                "DATA_SERVICE_UNAVAILABLE", "Health data is temporarily unavailable.", 503
            ) from None
