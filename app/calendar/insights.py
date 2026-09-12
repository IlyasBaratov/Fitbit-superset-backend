"""Deterministic meeting load, recurring series and how they line up with metrics (D7, D8)."""

from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime, timedelta
import statistics
from typing import Any, Mapping, Sequence
import pytz
from app.ai.analytics import average, number, percent
from app.calendar.vitals import event_window

# ponytail: an event with somebody else on it is a meeting; a solo block is not.
MIN_MEETING_ATTENDEES = 1
# ponytail: events this close together leave no gap to come down between them.
BACK_TO_BACK_GAP_MINUTES = 5
# ponytail: fewer paired days than this makes a Pearson r noise, not a signal.
MIN_CORRELATION_DAYS = 10
# ponytail: a tercile thinner than this is a couple of bad nights, not a pattern.
MIN_TERCILE_DAYS = 4
# ponytail: a series read fewer times than this is one bad morning, not a habit.
MIN_SERIES_OCCURRENCES = 3
# ponytail: how many single events are worth naming before the list turns into a log.
TOP_EVENT_COUNT = 5
# Local hours where a morning turns into an afternoon and an afternoon into an evening.
AFTERNOON_HOUR = 12
EVENING_HOUR = 17
PARTS_OF_DAY = ("morning", "afternoon", "evening")

# Daily metrics a meeting load can plausibly move (D7).
METRICS = (
    "resting_hr",
    "hrv_rmssd",
    "sleep_hours",
    "sleep_efficiency",
    "steps",
    "active_minutes",
    "breathing_rate",
    "skin_temperature_deviation",
)
# Sleep, HRV and resting heart rate are read the morning after the load they follow.
SHIFTS = {"same_day": 0, "next_day": 1}

Row = Mapping[str, Any]


def daily_load(events: Sequence[Row] | None, zone: str) -> dict[str, dict]:
    """Meeting load per local calendar day, keyed by ISO date like `analyze()` series."""
    local = pytz.timezone(zone)
    days: dict[date, list] = defaultdict(list)
    for row in events or []:
        window = event_window(row) if isinstance(row, dict) else None
        if window is None:
            continue
        start, end = (moment.astimezone(local) for moment in window)
        days[start.date()].append((start, end, _attendees(row)))
    return {
        day.isoformat(): _load(sorted(spans, key=lambda span: (span[0], span[1])))
        for day, spans in sorted(days.items())
    }


def daily_series(metrics: Mapping[str, Row] | None) -> dict[str, dict]:
    """The daily series `analyze()` already computed, never re-derived here."""
    series = {}
    for name in METRICS:
        daily = ((metrics or {}).get(name) or {}).get("daily") or {}
        if daily:
            series[name] = daily
    return series


def correlate(load: Mapping[str, Row], daily_metrics: Mapping[str, Row]) -> dict[str, dict]:
    """Pearson r of meeting minutes against each metric, same day and the next."""
    return _per_metric(load, daily_metrics, _correlation)


def tercile_comparison(
    load: Mapping[str, Row], daily_metrics: Mapping[str, Row]
) -> dict[str, dict]:
    """Each metric on the busiest third of days against the quietest third."""
    return _per_metric(load, daily_metrics, _terciles)


def series_summary(events: Sequence[Row] | None) -> list[dict]:
    """Repeating meetings, ranked by the elevation the ones read often enough carry."""
    groups: dict[tuple, list] = defaultdict(list)
    for row in _readable(events):
        groups[_series_key(row)].append(row)
    return sorted((_series(rows) for rows in groups.values()), key=_series_rank)


def time_of_day(events: Sequence[Row] | None, zone: str) -> dict[str, dict]:
    """Mean elevation of the events starting in each part of the local day."""
    local = pytz.timezone(zone)
    parts: dict[str, list] = {name: [] for name in PARTS_OF_DAY}
    for row in _readable(events):
        elevation = _elevation(row)
        if number(elevation):
            hour = event_window(row)[0].astimezone(local).hour
            parts[_part_of_day(hour)].append(elevation)
    return {
        name: {"mean_hr_vs_resting_pct": average(values), "n": len(values)}
        for name, values in parts.items()
    }


def top_events(events: Sequence[Row] | None, limit: int = TOP_EVENT_COUNT) -> list[dict]:
    """The steepest single events whose reading movement did not spoil (D7)."""
    rows = [
        _top_event(row)
        for row in _readable(events)
        if number(_elevation(row)) and (row["vitals"].get("movement_confounded") is not True)
    ]
    rows.sort(key=lambda row: (-row["hr_vs_resting_pct"], row["start"]))
    return rows[: max(0, int(limit))]


def _readable(events: Sequence[Row] | None):
    """Event rows carrying a usable window, each with its vitals dict or `None`."""
    for row in events or []:
        if isinstance(row, dict) and event_window(row) is not None:
            vitals = row.get("vitals")
            yield {**row, "vitals": vitals if isinstance(vitals, dict) else None}


def _series_key(row: Row) -> tuple[str, str]:
    """Instances of one recurrence first, then a repeated title, else the event alone."""
    recurring = str(row.get("recurringEventId") or "").strip()
    if recurring:
        return ("recurrence", recurring)
    title = " ".join(str(row.get("summary") or "").lower().split())
    return ("title", title) if title else ("event", str(row.get("EventId") or ""))


def _series(rows) -> dict:
    ordered = sorted(rows, key=lambda row: event_window(row)[0])
    measured = [row["vitals"] for row in ordered if row["vitals"] is not None]
    return {
        "title": next((title for title in map(_title, ordered) if title), ""),
        "occurrences": len(ordered),
        "with_vitals": len(measured),
        "mean_hr_vs_resting_pct": average([v.get("hr_vs_resting_pct") for v in measured]),
        "mean_recovery_delta": average([v.get("recovery_delta") for v in measured]),
        "confounded_count": sum(1 for v in measured if v.get("movement_confounded") is True),
    }


def _series_rank(group) -> tuple:
    """Series read often enough rank by elevation; the rest trail by how often they recur."""
    elevation = group["mean_hr_vs_resting_pct"]
    if group["with_vitals"] >= MIN_SERIES_OCCURRENCES and number(elevation):
        return (0, -float(elevation), group["title"])
    return (1, -float(group["occurrences"]), group["title"])


def _top_event(row: Row) -> dict:
    start, end = event_window(row)
    vitals = row["vitals"]
    return {
        "event_id": str(row.get("EventId") or ""),
        "title": _title(row),
        "start": start,
        "duration_minutes": round((end - start).total_seconds() / 60, 4),
        "attendees": _attendees(row),
        "mean_hr": vitals.get("mean_hr") if number(vitals.get("mean_hr")) else None,
        "hr_vs_resting_pct": vitals["hr_vs_resting_pct"],
        "recovery_delta": vitals.get("recovery_delta")
        if number(vitals.get("recovery_delta"))
        else None,
    }


def _elevation(row: Row):
    return (row["vitals"] or {}).get("hr_vs_resting_pct")


def _part_of_day(hour: int) -> str:
    if hour < AFTERNOON_HOUR:
        return "morning"
    return "afternoon" if hour < EVENING_HOUR else "evening"


def _title(row: Row) -> str:
    return " ".join(str(row.get("summary") or "").split())


def _per_metric(load, daily_metrics, summarize):
    return {
        name: {
            shift: summarize(_pairs(load, series, offset))
            for shift, offset in SHIFTS.items()
        }
        for name, series in (daily_metrics or {}).items()
        if name in METRICS and series
    }


def _pairs(load, series, offset: int) -> list[tuple[float, float]]:
    """Meeting minutes paired with the metric `offset` days later."""
    pairs = []
    for day, entry in (load or {}).items():
        minutes = entry.get("meeting_minutes") if isinstance(entry, dict) else None
        target = _shift(day, offset)
        value = series.get(target) if target is not None else None
        if number(minutes) and number(value):
            pairs.append((float(minutes), float(value)))
    return pairs


def _correlation(pairs) -> dict:
    if len(pairs) < MIN_CORRELATION_DAYS:
        return {"r": None, "n": len(pairs), "insufficient_data": True}
    try:
        # A metric that never moves has no correlation to report.
        value = round(statistics.correlation([m for m, _ in pairs], [v for _, v in pairs]), 4)
    except statistics.StatisticsError:
        value = None
    return {"r": value, "n": len(pairs), "insufficient_data": False}


def _terciles(pairs) -> dict:
    size = len(pairs) // 3
    if size < MIN_TERCILE_DAYS:
        return _tercile_row(size, [], [])
    ordered = sorted(pairs)
    return _tercile_row(size, ordered[:size], ordered[-size:])


def _tercile_row(size: int, bottom, top) -> dict:
    low, high = average([value for _, value in bottom]), average([value for _, value in top])
    return {
        "days": size,
        "top_third_mean": high,
        "bottom_third_mean": low,
        "top_third_meeting_minutes": average([minutes for minutes, _ in top]),
        "bottom_third_meeting_minutes": average([minutes for minutes, _ in bottom]),
        "difference": round(high - low, 4) if number(high) and number(low) else None,
        "percent": percent(high, low),
        "insufficient_data": not (bottom and top),
    }


def _load(spans) -> dict:
    gap = timedelta(minutes=BACK_TO_BACK_GAP_MINUTES)
    meetings = [span for span in spans if span[2] >= MIN_MEETING_ATTENDEES]
    return {
        "event_count": len(spans),
        "meeting_count": len(meetings),
        "meeting_minutes": _minutes(meetings),
        "event_minutes": _minutes(spans),
        "back_to_back_count": sum(
            1 for before, after in zip(spans, spans[1:]) if after[0] - before[1] <= gap
        ),
        "first_event_hour": _hour(spans[0][0]),
        "last_event_hour": _hour(spans[-1][0]),
    }


def _minutes(spans) -> float:
    return round(sum((end - start).total_seconds() / 60 for start, end, _ in spans), 4)


def _hour(moment: datetime) -> float:
    return round(moment.hour + moment.minute / 60 + moment.second / 3600, 4)


def _attendees(row: Row) -> int:
    """Events without a stored count are personal blocks, not meetings."""
    return int(row["attendees"]) if number(row.get("attendees")) else 0


def _shift(day: str, offset: int) -> str | None:
    try:
        return (date.fromisoformat(str(day)) + timedelta(days=offset)).isoformat()
    except ValueError:
        return None
