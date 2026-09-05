"""Select data locally and expose only aggregated, non-identifying context."""
import re
from app.services.health_analytics_service import Window, analyze

GROUPS = {
    "sleep": {"Sleep Summary", "Sleep Levels", "RestingHR", "HRV", "BreathingRate", "SPO2", "Skin Temperature Variation"},
    "activity": {"Total Steps", "Steps_Intraday", "Activity Minutes", "calories", "distance", "HR zones"},
    "workouts": {"Activity Records", "HR zones", "HeartRate_Intraday", "Sleep Summary", "HRV", "RestingHR"},
    "recovery": {"HRV", "RestingHR", "Sleep Summary", "SPO2", "BreathingRate", "Skin Temperature Variation", "Activity Records"},
    "cardiovascular": {"RestingHR", "HeartRate_Intraday", "HRV", "SPO2", "SPO2_Intraday", "BreathingRate"},
    "body": {"weight", "height", "bmi"},
}
KEYWORDS = {
    "sleep": r"sleep|bedtime|wake|insomnia|rem\b",
    "activity": r"step|walk|sedentary|active|activity|calorie|distance",
    "workouts": r"workout|exercise|training|running|cycling|swim",
    "recovery": r"recover|tired|fatigue|hrv|temperature|rest day|lighter",
    "cardiovascular": r"heart|pulse|oxygen|spo2|breath",
    "body": r"weight|height|bmi|body mass",
}
PRIMARY = {
    "sleep": {"Sleep Summary", "Sleep Levels"}, "activity": GROUPS["activity"],
    "workouts": {"Activity Records"}, "recovery": {"HRV", "RestingHR", "Sleep Summary", "SPO2", "BreathingRate", "Skin Temperature Variation"},
    "cardiovascular": GROUPS["cardiovascular"], "body": GROUPS["body"],
}


def classify(question):
    selected = [name for name, pattern in KEYWORDS.items() if re.search(pattern, question, re.I)]
    return selected or list(GROUPS)


def measurements(focus):
    return set().union(*(GROUPS[name] for name in focus))


def build_context(data, window, focus):
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
    evidence = sorted(name for name in metrics)
    if "summary" in context.get("workouts", {}):
        evidence.append("workout_summary")
    if "sleep" in context and any(v is not None for v in analytics["sleep_consistency"].values()):
        evidence.append("sleep_consistency")
    context["evidence_keys"] = evidence
    sufficient = bool(available & set().union(*(PRIMARY[name] for name in focus)))
    return context, sufficient
