"""Select data locally and expose only aggregated, non-identifying context."""
from collections import defaultdict
from datetime import date
import re
from app.ai.analytics import Window, analyze, average, number
from app.calendar.insights import MIN_CORRELATION_DAYS

GROUPS = {
    "sleep": {"Sleep Summary", "Sleep Levels", "RestingHR", "HRV", "BreathingRate", "SPO2", "Skin Temperature Variation"},
    "activity": {"Total Steps", "Steps_Intraday", "Activity Minutes", "calories", "distance", "HR zones"},
    "workouts": {"Activity Records", "HR zones", "HeartRate_Intraday", "Sleep Summary", "HRV", "RestingHR"},
    "recovery": {"HRV", "RestingHR", "Sleep Summary", "SPO2", "BreathingRate", "Skin Temperature Variation", "Activity Records"},
    "cardiovascular": {"RestingHR", "HeartRate_Intraday", "HRV", "SPO2", "SPO2_Intraday", "BreathingRate"},
    "body": {"weight", "height", "bmi"},
    "calendar": {"Calendar Events", "HeartRate_Intraday", "Steps_Intraday", "RestingHR", "HRV", "Sleep Summary"},
}
KEYWORDS = {
    "sleep": r"sleep|bedtime|wake|insomnia|rem\b",
    "activity": r"step|walk|sedentary|active|activity|calorie|distance",
    "workouts": r"workout|exercise|training|running|cycling|swim",
    "recovery": r"recover|tired|fatigue|hrv|temperature|rest day|lighter",
    "cardiovascular": r"heart|pulse|oxygen|spo2|breath",
    "body": r"weight|height|bmi|body mass",
    "calendar": r"meeting|calendar|event|appointment|busy day|schedule",
}
PRIMARY = {
    "sleep": {"Sleep Summary", "Sleep Levels"}, "activity": GROUPS["activity"],
    "workouts": {"Activity Records"}, "recovery": {"HRV", "RestingHR", "Sleep Summary", "SPO2", "BreathingRate", "Skin Temperature Variation"},
    "cardiovascular": GROUPS["cardiovascular"], "body": GROUPS["body"],
    "calendar": {"Calendar Events"},
}
# ponytail: a title is a label for the model, not a transcript of the person's day.
TITLE_LIMIT = 80
# ponytail: five recurring meetings is a shortlist; ten is a calendar export.
CALENDAR_SERIES_COUNT = 5
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def classify(question):
    selected = [name for name, pattern in KEYWORDS.items() if re.search(pattern, question, re.I)]
    return selected or list(GROUPS)


def measurements(focus):
    return set().union(*(GROUPS[name] for name in focus))


def calendar_context(insights, include_titles=True):
    """Aggregates of the deterministic insights: no event ids, no per-event rows (D9)."""
    if not insights or not insights.get("days_with_events"):
        return None
    return {
        "load": _calendar_load(insights.get("daily_load") or [], insights["days_with_events"]),
        "correlations": _calendar_correlations(insights.get("correlations") or {}),
        "series": _calendar_series(insights.get("series") or [], include_titles),
        "time_of_day": {name: dict(part or {}) for name, part in (insights.get("time_of_day") or {}).items()},
        "caveats": [str(caveat) for caveat in insights.get("caveats") or []],
    }


def _calendar_load(rows, days_with_events):
    """Meeting load averaged over the days the insights report, never over silent days."""
    if not rows:
        return None
    return {
        "days_with_events": days_with_events,
        "days_summarized": len(rows),
        "mean_event_count": average([row.get("event_count") for row in rows]),
        "mean_meeting_count": average([row.get("meeting_count") for row in rows]),
        "mean_meeting_minutes": average([row.get("meeting_minutes") for row in rows]),
        "mean_back_to_back_count": average([row.get("back_to_back_count") for row in rows]),
        "busiest_weekday": _busiest_weekday(rows),
        "coverage_note": f"Averages cover the {len(rows)} most recent days that had events, not every day of the period.",
    }


def _busiest_weekday(rows):
    """The weekday whose days carry the most meeting minutes on average, if any do."""
    weekdays = defaultdict(list)
    for row in rows:
        day = _iso_date(row.get("date"))
        if day is not None and number(row.get("meeting_minutes")):
            weekdays[day.weekday()].append(row["meeting_minutes"])
    ranked = [(index, average(values)) for index, values in weekdays.items()]
    ranked = [(index, mean) for index, mean in ranked if number(mean) and mean > 0]
    return WEEKDAYS[min(ranked, key=lambda item: (-item[1], item[0]))[0]] if ranked else None


def _iso_date(value):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _calendar_correlations(correlations):
    """Only metrics with enough paired days behind them are worth reporting (C3.1)."""
    reported = {}
    for name, shifts in correlations.items():
        kept = {
            shift: {"r": entry["r"], "n": entry["n"]}
            for shift, entry in (shifts or {}).items()
            if number((entry or {}).get("r")) and (entry.get("n") or 0) >= MIN_CORRELATION_DAYS
        }
        if kept:
            reported[name] = kept
    return reported


def _calendar_series(series, include_titles):
    """Recurring meetings; `label` is the stored title only while titles are allowed."""
    rows = []
    for position, group in enumerate(series[:CALENDAR_SERIES_COUNT], start=1):
        title = " ".join(str(group.get("title") or "").split())[:TITLE_LIMIT] if include_titles else ""
        rows.append({
            "label": title or f"series-{position}",
            "occurrences": group.get("occurrences"),
            "with_vitals": group.get("with_vitals"),
            "mean_hr_vs_resting_pct": group.get("mean_hr_vs_resting_pct"),
            "mean_recovery_delta": group.get("mean_recovery_delta"),
            "confounded_count": group.get("confounded_count"),
        })
    return rows


def build_context(data, window, focus, calendar=None, include_titles=True):
    analytics = analyze(data, window)
    requested = measurements(focus)
    # Availability means usable numeric evidence in the requested period, not historical rows alone.
    metrics = {name: metric for name, metric in analytics["metrics"].items() if metric["observed_days"] > 0}
    available = set()
    for metric in metrics.values():
        metric["sources"] = [source for source in metric["sources"] if data.get(source)]
        available.update(metric["sources"])
    if analytics["workouts"] and analytics["workouts"]["count"]:
        available.add("Activity Records")
    calendar_section = calendar_context(calendar, include_titles)
    if calendar_section:
        # Readable events are the calendar's own evidence; it has no analytics metric (D4).
        available.add("Calendar Events")
    context = {
        "analysis_period": {"start": window.start_date.isoformat(), "end": window.today.isoformat(), "days": window.days,
                            "timezone": str(window.zone), "today_is_partial": True},
        "data_quality": {"available": sorted(available), "missing": sorted(requested-available),
                         "partial": sorted({source for m in metrics.values() if m["observed_days"] < window.days for source in m["sources"]}),
                         "notes": ["Missing days are excluded from averages; today is excluded from baseline averages.",
                                   "Absence of a measurement is not evidence of a normal value.",
                                   "Sleep stages reflect stored provider labels; older classic Fitbit sleep may map restless to REM."]},
    }
    for name, metric in metrics.items():
        if len(metric["daily"]) > 14:
            metric["daily"] = dict(list(metric["daily"].items())[-14:])
            metric["daily_detail_note"] = "Latest 14 observed days shown; period statistics cover the full requested range."
        category = metric.pop("category")
        context.setdefault(category, {})[name] = metric
    if "sleep" in context:
        context["sleep"]["consistency"] = analytics["sleep_consistency"]
    if analytics["workouts"] and analytics["workouts"]["count"]:
        # No account, device, session, activity IDs, or precise timestamps are exposed.
        context.setdefault("workouts", {})["summary"] = analytics["workouts"]
    if calendar_section:
        context["calendar"] = calendar_section
    evidence = sorted(name for name in metrics)
    if "summary" in context.get("workouts", {}):
        evidence.append("workout_summary")
    if "sleep" in context and any(v is not None for v in analytics["sleep_consistency"].values()):
        evidence.append("sleep_consistency")
    if calendar_section and calendar_section["load"]:
        evidence.append("calendar_load")
    if calendar_section and calendar_section["series"]:
        evidence.append("calendar_series")
    context["evidence_keys"] = evidence
    sufficient = bool(available & set().union(*(PRIMARY[name] for name in focus)))
    return context, sufficient
