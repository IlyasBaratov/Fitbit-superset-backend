"""Provider-independent sleep-session inputs for the experimental score engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from math import floor, isfinite
import pytz


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()


@dataclass(frozen=True)
class SleepStageInterval(Interval):
    stage: str


@dataclass(frozen=True)
class HeartRateSample:
    timestamp: datetime
    bpm: float


@dataclass(frozen=True)
class SleepSessionFeatures:
    wake_date: date
    session_id: str
    start_time: datetime
    end_time: datetime
    minutes_asleep: float | None
    minutes_in_bed: float | None
    sleep_goal_minutes: float
    stages: tuple[SleepStageInterval, ...]
    short_awakenings: tuple[Interval, ...] | None
    short_awakening_seconds: float | None
    short_awakening_count: int | None
    heart_rate_samples: tuple[HeartRateSample, ...] = ()
    age: int | None = None
    gender: str | None = None
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class SleepDaySelection:
    wake_date: date
    session: SleepSessionFeatures | None
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class TimeToSoundSleep:
    minutes: float | None
    method: str | None
    flags: tuple[str, ...] = ()


SLEEP_SCORE_MODEL_VERSION = "sleep-score-emulator-v0.1"
DURATION_SHORTFALL_WEIGHT = 0.163
TIME_TO_SOUND_SLEEP_WEIGHT = 0.606
RESTLESSNESS_WEIGHT = 0.123
INTERRUPTION_WEIGHT = 0.124


@dataclass(frozen=True)
class SleepScoreResult:
    raw_score: float | None
    score: int | None
    insufficient_data: bool
    confidence: str
    components: dict[str, dict[str, float | int | str | None]]
    flags: tuple[str, ...]


def aware_utc(value: datetime | str) -> datetime:
    """Reject ambiguous stored times instead of guessing their timezone."""
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Sleep timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _stages(rows: list[Mapping[str, Any]], session_id: str) -> tuple[SleepStageInterval, ...]:
    intervals = []
    for row in rows:
        if row.get("SleepSessionId") != session_id:
            continue
        duration = _number(row.get("duration_seconds"))
        if duration is None or duration <= 0:
            continue  # Existing end-of-session marker has no duration.
        try:
            start = aware_utc(row["time"])
        except (KeyError, TypeError, ValueError):
            continue
        intervals.append(
            SleepStageInterval(
                start,
                start + timedelta(seconds=duration),
                str(row.get("stageName") or "unknown").lower(),
            )
        )
    return tuple(sorted(intervals, key=lambda item: (item.start, item.end)))


def _awakenings(
    rows: list[Mapping[str, Any]], session_id: str, summary: Mapping[str, Any]
) -> tuple[Interval, ...] | None:
    intervals = []
    for row in rows:
        if row.get("SleepSessionId") != session_id:
            continue
        try:
            start, end = aware_utc(row["time"]), aware_utc(row["endTime"])
        except (KeyError, TypeError, ValueError):
            continue
        if end > start:
            intervals.append(Interval(start, end))
    if intervals:
        return tuple(sorted(intervals, key=lambda item: (item.start, item.end)))
    if summary.get("shortAwakeningSeconds") == 0 and summary.get("shortAwakeningCount") == 0:
        return ()
    return None


def normalize_sleep_days(
    summaries: list[Mapping[str, Any]],
    stages: list[Mapping[str, Any]],
    awakenings: list[Mapping[str, Any]],
    local_timezone: str,
    sleep_goal_minutes: float,
    age: int | None = None,
    gender: str | None = None,
) -> dict[date, SleepDaySelection]:
    """Select a single processed main session per local wake date."""
    zone = pytz.timezone(local_timezone)
    grouped: dict[date, list[tuple[Mapping[str, Any], datetime, datetime]]] = {}
    for row in summaries:
        try:
            start, end = aware_utc(row["startTime"]), aware_utc(row["endTime"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            continue
        grouped.setdefault(end.astimezone(zone).date(), []).append((row, start, end))

    result = {}
    for wake_date, candidates in grouped.items():
        main = [
            candidate
            for candidate in candidates
            if str(candidate[0].get("isMainSleep", "")).lower() == "true"
        ]
        if not main:
            result[wake_date] = SleepDaySelection(wake_date, None, ("no_main_sleep",))
            continue
        main.sort(
            key=lambda candidate: (
                candidate[0].get("isProcessed") is True,
                candidate[2] - candidate[1],
                candidate[2],
            ),
            reverse=True,
        )
        row, start, end = main[0]
        flags = ["multiple_main_sleep_sessions"] if len(main) > 1 else []
        session_id = str(row.get("SleepSessionId") or "")
        if not session_id:
            flags.append("missing_sleep_session_id")
        short = _awakenings(awakenings, session_id, row) if session_id else None
        seconds = _number(row.get("shortAwakeningSeconds"))
        if short is not None and seconds is not None and abs(sum(x.seconds for x in short) - seconds) > 1:
            flags.append("short_awakening_total_mismatch")
        session = SleepSessionFeatures(
            wake_date=wake_date,
            session_id=session_id,
            start_time=start,
            end_time=end,
            minutes_asleep=_number(row.get("minutesAsleep")),
            minutes_in_bed=_number(row.get("minutesInBed")),
            sleep_goal_minutes=sleep_goal_minutes,
            stages=_stages(stages, session_id) if session_id else (),
            short_awakenings=short,
            short_awakening_seconds=seconds,
            short_awakening_count=row.get("shortAwakeningCount"),
            age=age,
            gender=gender,
            flags=tuple(flags),
        )
        result[wake_date] = SleepDaySelection(wake_date, session, tuple(flags))
    return result


ASLEEP_STAGES = frozenset({"light", "deep", "rem"})


def sleep_efficiency_percent(session: SleepSessionFeatures) -> float | None:
    if (
        session.minutes_asleep is None
        or session.minutes_in_bed is None
        or session.minutes_in_bed <= 0
        or session.minutes_asleep < 0
    ):
        return None
    return 100 * session.minutes_asleep / session.minutes_in_bed


def restlessness_minutes(session: SleepSessionFeatures) -> float | None:
    seconds = session.short_awakening_seconds
    intervals = session.short_awakenings
    if seconds is not None:
        if seconds < 0:
            return None
        if intervals is not None and abs(sum(item.seconds for item in intervals) - seconds) > 1:
            return None
        return seconds / 60
    if intervals is not None:
        return sum(item.seconds for item in intervals) / 60
    return None


def long_internal_awake_bouts(
    session: SleepSessionFeatures,
) -> tuple[SleepStageInterval, ...] | None:
    asleep = [item for item in session.stages if item.stage in ASLEEP_STAGES]
    if not asleep:
        return None
    return tuple(
        item
        for item in session.stages
        if item.stage == "awake"
        and item.seconds > 5 * 60
        and any(sleep.end <= item.start for sleep in asleep)
        and any(sleep.start >= item.end for sleep in asleep)
    )


def interruption_minutes(session: SleepSessionFeatures) -> float | None:
    bouts = long_internal_awake_bouts(session)
    return None if bouts is None else sum(item.seconds for item in bouts) / 60


def full_awakenings_count(session: SleepSessionFeatures) -> int | None:
    bouts = long_internal_awake_bouts(session)
    return None if bouts is None else len(bouts)


LIGHT_STABLE_MINUTES = 20  # Provisional candidate duration, not a Google threshold.


def time_to_sound_sleep(
    session: SleepSessionFeatures,
    stable_light_qualifier: Callable[[SleepStageInterval, SleepSessionFeatures], bool] | None = None,
    fallback_flag: str = "tts_stable_light_unvalidated",
) -> TimeToSoundSleep:
    """First Deep, REM, or qualified stable Light start since the sleep attempt."""
    candidates: list[tuple[datetime, str]] = []
    for stage_name in ("deep", "rem"):
        first = min(
            (item.start for item in session.stages if item.stage == stage_name),
            default=None,
        )
        if first is not None:
            candidates.append((first, f"first_{stage_name}"))
    if stable_light_qualifier is not None:
        long_awake = long_internal_awake_bouts(session) or ()
        for item in session.stages:
            if (
                item.stage == "light"
                and item.seconds >= LIGHT_STABLE_MINUTES * 60
                and not any(bout.start < item.end and bout.end > item.start for bout in long_awake)
                and stable_light_qualifier(item, session)
            ):
                candidates.append((item.start, "stable_light"))
    flags = (fallback_flag,) if stable_light_qualifier is None else ()
    if not candidates:
        return TimeToSoundSleep(None, None, flags + ("no_sound_sleep_candidate",))
    start, method = min(candidates, key=lambda candidate: candidate[0])
    if start < session.start_time or start >= session.end_time:
        return TimeToSoundSleep(None, None, flags + ("sound_start_outside_session",))
    return TimeToSoundSleep((start - session.start_time).total_seconds() / 60, method, flags)


def score_v01_raw(
    duration_shortfall_minutes: float,
    time_to_sound_sleep_minutes: float,
    restlessness_minutes_value: float,
    interruption_minutes_value: float,
) -> float:
    """Fixed empirical formula; arguments must be derived sleep features."""
    values = (
        duration_shortfall_minutes, time_to_sound_sleep_minutes,
        restlessness_minutes_value, interruption_minutes_value,
    )
    if any(not isfinite(value) or value < 0 for value in values):
        raise ValueError("Sleep score inputs must be finite nonnegative values")
    return max(0.0, min(100.0,
        100
        - DURATION_SHORTFALL_WEIGHT * duration_shortfall_minutes
        - TIME_TO_SOUND_SLEEP_WEIGHT * time_to_sound_sleep_minutes
        - RESTLESSNESS_WEIGHT * restlessness_minutes_value
        - INTERRUPTION_WEIGHT * interruption_minutes_value,
    ))


def score_sleep_session(
    session: SleepSessionFeatures,
    tts: TimeToSoundSleep,
    sound_sleep_minutes: float | None = None,
    sound_sleep_method: str = "unavailable_uncalibrated_hr_classifier",
) -> SleepScoreResult:
    """Apply only the four fixed empirical v0.1 terms, without I/O or LLMs."""
    asleep = session.minutes_asleep
    goal = session.sleep_goal_minutes
    shortfall = (
        max(0.0, goal - asleep)
        if asleep is not None and isfinite(asleep) and asleep >= 0
        and isfinite(goal) and goal > 0
        else None
    )
    restless = restlessness_minutes(session)
    interruption = interruption_minutes(session)
    awakenings = full_awakenings_count(session)
    efficiency = sleep_efficiency_percent(session)
    duration_penalty = None if shortfall is None else DURATION_SHORTFALL_WEIGHT * shortfall
    tts_penalty = None if tts.minutes is None else TIME_TO_SOUND_SLEEP_WEIGHT * tts.minutes
    restlessness_penalty = None if restless is None else RESTLESSNESS_WEIGHT * restless
    interruption_penalty = None if interruption is None else INTERRUPTION_WEIGHT * interruption
    components = {
        "duration": {"minutes_asleep": asleep, "goal_minutes": goal,
                     "shortfall_minutes": shortfall, "penalty": duration_penalty,
                     "method": "goal_shortfall"},
        "time_to_sound_sleep": {"minutes": tts.minutes, "method": tts.method,
                                "penalty": tts_penalty},
        "sound_sleep": {"minutes": sound_sleep_minutes, "method": sound_sleep_method,
                        "penalty": None},
        "restlessness": {"minutes": restless, "method": "short_awakening_seconds_or_intervals",
                         "penalty": restlessness_penalty},
        "interruptions": {"minutes": interruption, "method": "internal_awake_over_5_minutes",
                          "penalty": interruption_penalty},
        "full_awakenings": {"count": awakenings, "method": "internal_awake_over_5_minutes",
                            "penalty": None},
        "sleep_efficiency": {"percent": efficiency, "method": "100_asleep_over_in_bed",
                             "penalty": None},
    }
    flags = list(dict.fromkeys(("experimental_formula", *session.flags, *tts.flags)))
    if sound_sleep_minutes is None:
        flags.append("sound_sleep_unavailable_uncalibrated")
    for name, value in (
        ("sleep_duration", shortfall),
        ("time_to_sound_sleep", tts.minutes),
        ("restlessness", restless),
        ("interruptions", interruption),
    ):
        if value is None or not isfinite(value) or value < 0:
            flags.append(f"missing_{name}")
    if any(flag.startswith("missing_") for flag in flags):
        return SleepScoreResult(None, None, True, "insufficient", components, tuple(flags))
    raw = score_v01_raw(shortfall, tts.minutes, restless, interruption)
    score = floor(raw + 0.5)
    confidence = "experimental_approximate" if "tts_approximation_no_hr" in flags else "experimental"
    return SleepScoreResult(raw, score, False, confidence, components, tuple(flags))
