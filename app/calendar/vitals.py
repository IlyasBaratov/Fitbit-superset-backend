"""Pure per-event vitals over stored calendar rows and intraday buckets (D7, D8)."""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Mapping, Sequence
from app.ai.analytics import number, percent

# ponytail: shorter events carry too few buckets to read a heart-rate response from.
MIN_EVENT_MINUTES = 10
# ponytail: a sustained walking pace; above it the heart rate is movement, not the meeting.
MOVEMENT_STEPS_PER_MINUTE = 20
# ponytail: minimum share of an event that heart-rate buckets must cover.
MIN_COVERAGE_PCT = 50
# ponytail: minutes of context read before and after an event.
CONTEXT_MINUTES = 30

# The read layer refuses more rows than this, so buckets stay coarse enough (D6).
MAX_BUCKET_ROWS = 20000
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
Row = Mapping[str, Any]


def bucket_minutes(days: int) -> int:
    """Bucket width keeping a whole period of intraday samples under the row cap."""
    return max(1, math.ceil(int(days) * 1440 / MAX_BUCKET_ROWS))


def usable_events(rows: Sequence[Row]) -> list[dict]:
    """Newest row per event (D5), keeping only events whose vitals can mean something."""
    newest: dict[str, dict] = {}
    for row in rows or []:
        if not isinstance(row, dict) or event_window(row) is None:
            continue
        key = str(row.get("EventId") or row.get("time") or "")
        current = newest.get(key)
        if current is None or _updated(row) >= _updated(current):
            newest[key] = row
    kept = [row for row in newest.values() if _is_readable(row)]
    return sorted(kept, key=lambda row: event_window(row)[0])


def event_window(row: Row) -> tuple[datetime, datetime] | None:
    """Stored event start and end in UTC, or `None` when either is unusable."""
    return _span(row, ("duration_seconds",))


def event_vitals(
    event: Row,
    hr_buckets: Sequence[Row],
    step_buckets: Sequence[Row],
    workouts: Sequence[Row],
    resting_hr: float | None,
    bucket_minutes: int = 1,
) -> tuple[dict | None, list[str]]:
    """Heart-rate response to one event, or `None` when the buckets do not cover it."""
    window = event_window(event)
    if window is None:
        return None, ["Event has no usable start and end."]
    start, end = window
    minutes = (end - start).total_seconds() / 60
    width = max(1, int(bucket_minutes or 1))
    expected = max(1, math.ceil(round(minutes / width, 6)))
    inside = _buckets(hr_buckets, start, end, width)
    covered = sum(1 for row in inside if row["count"] > 0)
    coverage = round(min(covered / expected, 1.0) * 100, 4)
    if coverage < MIN_COVERAGE_PCT:
        return None, [
            f"Heart rate covers {coverage:g}% of the event, "
            f"below the {MIN_COVERAGE_PCT}% minimum."
        ]

    notes = []
    mean_hr = _weighted_mean(inside)
    maxima = [row["max"] for row in inside if number(row["max"])]
    steps_rows = _buckets(step_buckets, start, end, width)
    steps = round(sum(row["sum"] for row in steps_rows), 4) if steps_rows else None
    rate = round(steps / minutes, 4) if steps is not None and minutes > 0 else None
    movement = bool(
        (rate is not None and rate > MOVEMENT_STEPS_PER_MINUTE)
        or _overlaps_workout(workouts, start, end)
    )
    if movement:
        notes.append("Movement during the event confounds the heart-rate reading.")
    if not number(resting_hr):
        notes.append("Resting heart rate is unknown, so elevation is not reported.")
    context = timedelta(minutes=CONTEXT_MINUTES)
    pre = _weighted_mean(_buckets(hr_buckets, start - context, start, width))
    post = _weighted_mean(_buckets(hr_buckets, end, end + context, width))
    return {
        "mean_hr": mean_hr,
        "max_hr": max(maxima) if maxima else None,
        "sample_count": int(sum(row["count"] for row in inside)),
        "coverage_pct": coverage,
        "hr_vs_resting_pct": percent(mean_hr, resting_hr),
        "steps": steps,
        "steps_per_minute": rate,
        "movement_confounded": movement,
        "pre30_mean_hr": pre,
        "post30_mean_hr": post,
        "recovery_delta": round(post - mean_hr, 4)
        if number(post) and number(mean_hr)
        else None,
    }, notes


def _is_readable(row: Row) -> bool:
    """Cancelled, all-day, free-time and very short events carry no usable response."""
    start, end = event_window(row)
    return (
        _text(row, "status") != "cancelled"
        and not _flag(row.get("isAllDay"))
        and _text(row, "transparency") != "transparent"
        and end - start >= timedelta(minutes=MIN_EVENT_MINUTES)
    )


def _buckets(rows: Sequence[Row], start: datetime, end: datetime, width: int) -> list[dict]:
    """A bucket belongs to the window that contains its midpoint."""
    half = timedelta(minutes=width / 2)
    selected = []
    for row in rows or []:
        if not isinstance(row, dict) or not number(row.get("sum")) or not number(row.get("count")):
            continue
        moment = _moment(row.get("time"))
        if moment is not None and start <= moment + half < end:
            selected.append({"sum": row["sum"], "count": row["count"], "max": row.get("max")})
    return selected


def _weighted_mean(rows: Sequence[Row]) -> float | None:
    count = sum(row["count"] for row in rows)
    return round(sum(row["sum"] for row in rows) / count, 4) if count > 0 else None


def _overlaps_workout(workouts: Sequence[Row], start: datetime, end: datetime) -> bool:
    for row in workouts or []:
        if not isinstance(row, dict):
            continue
        span = _span(row, ("duration", "ActiveDuration"))
        if span is not None and span[0] < end and span[1] > start:
            return True
    return False


def _span(row: Row, duration_keys: tuple[str, ...]) -> tuple[datetime, datetime] | None:
    start = _moment(row.get("startTime") or row.get("time"))
    if start is None:
        return None
    end = _moment(row.get("endTime"))
    for key in duration_keys:
        if end is None and number(row.get(key)):
            end = start + timedelta(seconds=float(row[key]))
    return (start, end) if end is not None and end > start else None


def _moment(value: Any) -> datetime | None:
    """Stored timestamps always carry an offset; anything else is unusable."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _updated(row: Row) -> datetime:
    return _moment(row.get("updated")) or EPOCH


def _flag(value: Any) -> bool:
    return str(value).strip().lower() == "true"


def _text(row: Row, key: str) -> str:
    return str(row.get(key) or "").strip().lower()
