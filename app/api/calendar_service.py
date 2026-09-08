"""Stored calendar events joined with the heart-rate response they sit in (D6, D7)."""

from datetime import datetime, timedelta, timezone
import pytz
from pydantic import ValidationError
from app.ai.analytics import number
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
from app.api.schemas.calendar import CalendarEvent, CalendarEventsResponse, EventVitals
from app.storage.influx.queries import CALENDAR

# ponytail: a resting heart rate this old is still a better baseline than none.
BASELINE_MAX_AGE_DAYS = 7


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

    def _events(self, start, end, width):
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
            window = event_window(event)
            vitals, notes = event_vitals(
                event,
                hr,
                steps,
                workouts,
                self._baseline(baselines, window[0], zone),
                width,
            )
            rows.append(self._event(event, window, vitals, notes))
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
    def _event(event, window, vitals, notes):
        start, end = window
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
