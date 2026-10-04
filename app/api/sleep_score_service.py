"""Storage reads and response composition for deterministic sleep scoring."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import pytz
from pydantic import ValidationError
from app.api.health_service import resolve_interval
from app.api.schemas.scores import SleepScoreDay, SleepScoreResponse
from app.core.exceptions import DataUnavailable, QueryLimitExceeded
from app.errors import APIError
from app.scores.sleep import (
    HeartRateSample,
    SLEEP_SCORE_MODEL_VERSION,
    aware_utc,
    normalize_sleep_days,
    score_sleep_session,
    time_to_sound_sleep,
)
from app.scores.sleep_hr import sleep_hr_epochs


CAVEATS = [
    "This is an experimental emulator, not the proprietary Google/Fitbit Sleep Score.",
    "Only seven owner nights were used for the v0.1 empirical coefficients; in-sample error is not validated accuracy.",
    "Sound Sleep and Full Awakenings have no independent v0.1 score weight.",
    "Sound Sleep and HR-qualified Stable Light are unavailable until classifier thresholds are validated.",
]
COMPONENT_NAMES = (
    "duration", "time_to_sound_sleep", "sound_sleep", "restlessness",
    "interruptions", "full_awakenings", "sleep_efficiency",
)


def _empty_day(day, flags):
    return SleepScoreDay(
        date=day, score=None, raw_score=None, sleep_efficiency=None,
        insufficient_data=True, confidence="insufficient",
        components={name: {} for name in COMPONENT_NAMES},
        flags=list(flags),
    )


class SleepScoreReadService:
    def __init__(self, settings, repository, clock=None):
        self.settings, self.repository = settings, repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def read(self, period: str | None = None) -> SleepScoreResponse:
        start, end, days = resolve_interval(self.settings, self.clock, period)
        zone = pytz.timezone(self.settings.timezone)
        first = start.astimezone(zone).date()
        try:
            # A sleep ending on the first requested day may start the prior day.
            context_start = start - timedelta(days=1)
            summaries = self.repository.query("Sleep Summary", context_start, end)
            stages = self.repository.query("Sleep Levels", context_start, end)
            awakenings = self.repository.query("Sleep Short Awakenings", context_start, end)
            selected = normalize_sleep_days(
                summaries, stages, awakenings, self.settings.timezone,
                self.settings.sleep_goal_minutes, self.settings.sleep_profile_age,
                self.settings.sleep_profile_gender,
            )
            output = []
            for offset in range(days):
                wake_date = first + timedelta(days=offset)
                choice = selected.get(wake_date)
                if choice is None:
                    output.append(_empty_day(wake_date, ("missing_main_sleep_session",)))
                    continue
                if choice.session is None:
                    output.append(_empty_day(wake_date, choice.flags))
                    continue
                session = choice.session
                hr_flags = []
                if session.end_time > end:
                    output.append(_empty_day(wake_date, ("sleep_session_not_finished",)))
                    continue
                if session.end_time - session.start_time > timedelta(days=1):
                    hr_flags.append("sleep_session_exceeds_hr_query_window")
                    hr_rows = []
                else:
                    try:
                        hr_rows = self.repository.query_raw_sleep_heart_rate(
                            session.start_time, session.end_time
                        )
                    except QueryLimitExceeded:
                        hr_rows = []
                        hr_flags.append("sleep_hr_query_limit_exceeded")
                samples = []
                for row in hr_rows:
                    try:
                        moment = aware_utc(row["time"])
                        bpm = float(row["value"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    samples.append(HeartRateSample(moment, bpm))
                session = replace(session, heart_rate_samples=tuple(samples))
                epochs = sleep_hr_epochs(session)
                coverage = sum(epoch.minutes for epoch in epochs if epoch.minute_hr is not None)
                sparse = sum(epoch.minutes for epoch in epochs if epoch.minute_hr is None)
                if not samples:
                    hr_flags.append("high_resolution_hr_unavailable")
                tts = time_to_sound_sleep(
                    session,
                    fallback_flag=("tts_approximation_no_hr" if not samples
                                   else "tts_stable_light_unvalidated"),
                )
                result = score_sleep_session(session, tts)
                components = result.components
                components["sound_sleep"]["hr_coverage_minutes"] = coverage
                components["sound_sleep"]["hr_sparse_minutes"] = sparse
                output.append(SleepScoreDay(
                    date=wake_date, score=result.score, raw_score=result.raw_score,
                    sleep_efficiency=components["sleep_efficiency"]["percent"],
                    insufficient_data=result.insufficient_data,
                    confidence=result.confidence, components=components,
                    flags=list(dict.fromkeys((*result.flags, *hr_flags))),
                ))
            return SleepScoreResponse(
                start=start, end=end, timezone=self.settings.timezone,
                model_version=SLEEP_SCORE_MODEL_VERSION, days=output,
                caveats=CAVEATS,
            )
        except QueryLimitExceeded:
            raise APIError(
                "HEALTH_QUERY_TOO_LARGE",
                "Requested data exceeds the safe query limit; use a shorter period.",
                422,
            ) from None
        except (DataUnavailable, ValidationError, KeyError, ValueError, TypeError):
            raise APIError(
                "DATA_SERVICE_UNAVAILABLE", "Health data is temporarily unavailable.", 503
            ) from None
