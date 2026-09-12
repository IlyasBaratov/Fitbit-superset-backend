"""Pure Google Calendar event mapping, no I/O and no attendee identities stored."""

from __future__ import annotations
from datetime import datetime
from typing import Any, Mapping, Sequence
from pytz.tzinfo import BaseTzInfo
from app.domain.models import HealthPoint
from app.domain.normalization import (
    local_date_boundary_utc,
    sanitize_fields,
    utc_timestamp,
)

MEASUREMENT = "Calendar Events"
SUMMARY_MAX_LENGTH = 200
# Google omits these keys when the event carries their default value.
DEFAULT_STATUS = "confirmed"
DEFAULT_EVENT_TYPE = "default"
DEFAULT_TRANSPARENCY = "opaque"


def map_events(
    items: Sequence[Mapping[str, Any]],
    calendar_id: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    """One point per event instance, timestamped at its start (all-day: local midnight)."""
    zone = local_timezone.zone
    records = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        event_id = str(item.get("id") or "").strip()
        interval = _interval(item, zone)
        if not event_id or interval is None:
            continue
        start_utc, end_utc, is_all_day = interval
        attendees, response_status = _attendee_summary(item.get("attendees"))
        organizer = item.get("organizer")
        records.append(
            {
                "measurement": MEASUREMENT,
                "time": start_utc,
                "tags": {"CalendarId": str(calendar_id), "EventId": event_id},
                "fields": sanitize_fields(
                    {
                        "summary": _clean_text(item.get("summary")),
                        "startTime": start_utc,
                        "endTime": end_utc,
                        "duration_seconds": _duration_seconds(start_utc, end_utc),
                        "status": str(item.get("status") or DEFAULT_STATUS),
                        "eventType": str(item.get("eventType") or DEFAULT_EVENT_TYPE),
                        "transparency": str(
                            item.get("transparency") or DEFAULT_TRANSPARENCY
                        ),
                        "attendees": attendees,
                        "isOrganizer": bool(
                            isinstance(organizer, dict) and organizer.get("self")
                        ),
                        "responseStatus": response_status,
                        "recurringEventId": str(item.get("recurringEventId") or ""),
                        "updated": str(item.get("updated") or ""),
                        "isAllDay": is_all_day,
                    }
                ),
            }
        )
    return [HealthPoint.from_record(record) for record in records]


def _interval(item: dict, zone: str) -> tuple[str, str | None, bool] | None:
    """Cancelled instances carry no `start`, only the `originalStartTime` they replaced."""
    start = item.get("start")
    if not isinstance(start, dict) or not (start.get("date") or start.get("dateTime")):
        start = item.get("originalStartTime")
    end = item.get("end")
    if not isinstance(start, dict):
        return None
    if not isinstance(end, dict):
        end = {}
    try:
        if start.get("date"):
            return (
                local_date_boundary_utc(str(start["date"]), zone),
                local_date_boundary_utc(str(end["date"]), zone)
                if end.get("date")
                else None,
                True,
            )
        if start.get("dateTime"):
            return (
                utc_timestamp(str(start["dateTime"]), zone),
                utc_timestamp(str(end["dateTime"]), zone)
                if end.get("dateTime")
                else None,
                False,
            )
    except (TypeError, ValueError, KeyError):
        return None
    return None


def _duration_seconds(start_utc: str, end_utc: str | None) -> int | None:
    if not end_utc:
        return None
    seconds = (
        datetime.fromisoformat(end_utc) - datetime.fromisoformat(start_utc)
    ).total_seconds()
    return int(seconds) if seconds >= 0 else None


def _attendee_summary(attendees: Any) -> tuple[int, str]:
    """Counts other attendees only; addresses and names are never stored (D9)."""
    if not isinstance(attendees, list):
        return 0, ""
    others, response_status = 0, ""
    for attendee in attendees:
        if not isinstance(attendee, dict):
            continue
        if attendee.get("self"):
            response_status = str(attendee.get("responseStatus") or "")
        else:
            others += 1
    return others, response_status


def _clean_text(value: Any) -> str:
    printable = "".join(
        character if character.isprintable() else " " for character in str(value or "")
    )
    return " ".join(printable.split())[:SUMMARY_MAX_LENGTH]
