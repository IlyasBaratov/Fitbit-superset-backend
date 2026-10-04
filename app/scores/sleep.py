"""Provider-independent sleep-session inputs for the experimental score engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping
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
