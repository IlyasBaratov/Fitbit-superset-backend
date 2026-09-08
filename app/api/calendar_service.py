"""Stored calendar events joined with the heart-rate response they sit in (D6, D7)."""

from datetime import datetime, timedelta, timezone
import pytz
from pydantic import ValidationError
from app.ai.analytics import Window, analyze, number
from app.calendar.insights import (
    correlate,
    daily_load,
    daily_series,
    series_summary,
    tercile_comparison,
    time_of_day,
    top_events,
)
from app.calendar.vitals import (
    CONTEXT_MINUTES,
    bucket_minutes,
    event_vitals,
    event_window,
    usable_events,
)
from app.core.exceptions import DataUnavailable, QueryLimitExceeded
from app.errors import APIError
from app.api.health_service import resolve_interval
from app.api.schemas.calendar import (
    CalendarEvent,
    CalendarEventsResponse,
    CalendarInsightsResponse,
    EventVitals,
)
from app.storage.influx.queries import CALENDAR

# ponytail: a resting heart rate this old is still a better baseline than none.
BASELINE_MAX_AGE_DAYS = 7
# ponytail: a fortnight of daily load is readable; a quarter of it is a log.
DAILY_LOAD_DAYS = 14
# ponytail: more recurring meetings than this and the list stops being a shortlist.
TOP_SERIES_COUNT = 10
# Sources of the daily metrics `analyze()` derives the correlated series from (C3.1).
INSIGHT_MEASUREMENTS = (
    "RestingHR",
    "HRV",
    "Sleep Summary",
    "Sleep Levels",
    "Total Steps",
    "Activity Minutes",
    "BreathingRate",
    "Skin Temperature Variation",
)
CAVEATS = (
    "Elevated heart rate is a proxy for stress, not a measurement of it (D7).",
    "Correlation is not causation: a busy day is not shown to cause the change.",
    "Movement, caffeine, illness and loose sensor contact all confound heart rate.",
)


class CalendarReadService:
    """Read-only correlation of stored events with stored vitals; no Gemini, no writes."""

    def __init__(self, settings, repository, clock=None):
        self.settings, self.repository = settings, repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def events(self, period: str | None = None) -> CalendarEventsResponse:
        start, end, days = resolve_interval(self.settings, self.clock, period)
        width = bucket_minutes(days)
        try:
            return CalendarEventsResponse(
                start=start,
                end=end,
                timezone=self.settings.timezone,
                bucket_minutes=width,
                events=self._events(start, end, width),
            )
        except QueryLimitExceeded:
            raise APIError(
                "HEALTH_QUERY_TOO_LARGE",
                "Requested data exceeds the safe query limit; use a shorter period.",
                422,
            ) from None
        except (DataUnavailable, ValidationError, KeyError, ValueError, TypeError):
            raise APIError(
                "DATA_SERVICE_UNAVAILABLE",
                "Calendar data is temporarily unavailable.",
                503,
            ) from None

    def insights(self, period: str | None = None) -> CalendarInsightsResponse:
        start, end, days = resolve_interval(self.settings, self.clock, period)
        width = bucket_minutes(days)
        try:
            return self._insights(start, end, days, width)
        except QueryLimitExceeded:
            raise APIError(
                "HEALTH_QUERY_TOO_LARGE",
                "Requested data exceeds the safe query limit; use a shorter period.",
                422,
            ) from None
        except (DataUnavailable, ValidationError, KeyError, ValueError, TypeError):
            raise APIError(
                "DATA_SERVICE_UNAVAILABLE",
                "Calendar data is temporarily unavailable.",
                503,
            ) from None

    def _insights(self, start, end, days, width):
        zone = self.settings.timezone
        rows = self._readings(start, end, width)
        load = daily_load(rows, zone)
        # A period without a single readable day has nothing to correlate metrics with.
        metrics = daily_series(self._metrics(days)) if load else {}
        return CalendarInsightsResponse(
            period={
                "start": start,
                "end": end,
                "timezone": zone,
                "days": days,
                "bucket_minutes": width,
            },
            days_with_events=len(load),
            daily_load=[
                {"date": day, **entry}
                for day, entry in list(load.items())[-DAILY_LOAD_DAYS:]
            ],
            correlations=correlate(load, metrics),
            tercile_comparison=tercile_comparison(load, metrics),
            series=series_summary(rows)[:TOP_SERIES_COUNT],
            time_of_day=time_of_day(rows, zone),
            top_events=top_events(rows),
            caveats=_caveats(rows),
        )

    def _metrics(self, days):
        """The daily series `analyze()` already computes, never re-derived here (C3.1)."""
        window = Window(days, self.settings.timezone, self.clock())
        data = self.repository.fetch(INSIGHT_MEASUREMENTS, window.query_start, window.now)
        return analyze(data, window)["metrics"]

    def _events(self, start, end, width):
        return [
            self._event(row, row["vitals"], row["notes"])
            for row in self._readings(start, end, width)
        ]

    def _readings(self, start, end, width):
        """Stored events, each carrying the vitals its buckets support (C2.2, C3.2)."""
        if start >= end:
            return []
        events = usable_events(self.repository.query(CALENDAR, start, end))
        if not events:
            return []
        # Context windows reach past the period, so the vitals reads do too.
        context = timedelta(minutes=CONTEXT_MINUTES)
        hr = self.repository.query(
            "HeartRate_Intraday", start - context, end + context, bucket=f"{width}m"
        )
        steps = self.repository.query(
            "Steps_Intraday", start - context, end + context, bucket=f"{width}m"
        )
        workouts = self.repository.query("Activity Records", start - context, end + context)
        zone = pytz.timezone(self.settings.timezone)
        baselines = self._baselines(
            self.repository.query(
                "RestingHR", start - timedelta(days=BASELINE_MAX_AGE_DAYS), end
            ),
            zone,
        )
        rows = []
        for event in events:
            vitals, notes = event_vitals(
                event,
                hr,
                steps,
                workouts,
                self._baseline(baselines, event_window(event)[0], zone),
                width,
            )
            rows.append({**event, "vitals": vitals, "notes": notes})
        return rows

    def _baselines(self, rows, zone):
        """Resting heart rate per local day, the day a calendar event is measured against."""
        return {
            self._local_date(row["time"], zone): float(row["value"])
            for row in rows or []
            if number(row.get("value"))
        }

    @staticmethod
    def _baseline(baselines, moment, zone):
        day = moment.astimezone(zone).date()
        nearest = min(
            baselines, key=lambda stored: (abs(stored - day), stored), default=None
        )
        if nearest is None or abs((nearest - day).days) > BASELINE_MAX_AGE_DAYS:
            return None
        return baselines[nearest]

    @staticmethod
    def _local_date(value, zone):
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            raise ValueError("Stored timestamp must include timezone")
        return moment.astimezone(zone).date()

    @staticmethod
    def _event(event, vitals, notes):
        start, end = event_window(event)
        return CalendarEvent(
            event_id=_text(event, "EventId"),
            calendar_id=_text(event, "CalendarId"),
            summary=_text(event, "summary"),
            start=start,
            end=end,
            duration_minutes=round((end - start).total_seconds() / 60, 4),
            attendees=int(event["attendees"]) if number(event.get("attendees")) else None,
            is_organizer=event.get("isOrganizer")
            if isinstance(event.get("isOrganizer"), bool)
            else None,
            response_status=_text(event, "responseStatus"),
            event_type=_text(event, "eventType"),
            recurring_event_id=_text(event, "recurringEventId"),
            vitals=EventVitals(**vitals) if vitals is not None else None,
            notes=notes,
        )


def _text(event, key):
    """Absent stored strings are dropped on write, so they read back as empty."""
    value = event.get(key)
    return str(value) if value is not None else ""


def _caveats(rows):
    """The fixed warnings, plus the events whose heart-rate coverage was too thin."""
    unread = sum(1 for row in rows if row["vitals"] is None)
    if not unread:
        return list(CAVEATS)
    return [
        *CAVEATS,
        f"{unread} of {len(rows)} events lack heart-rate coverage and carry no vitals.",
    ]
