"""Google Calendar endpoint definitions; callers never construct calendar URLs."""

import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)

MAX_PAGES = 50
PAGE_SIZE = 250


class GoogleCalendarClient:
    def __init__(self, settings, transport):
        self.settings, self.transport = settings, transport

    def _events_url(self, calendar_id):
        base = self.settings.calendar_api_base_url.rstrip("/")
        return f"{base}/calendars/{quote(calendar_id, safe='')}/events"

    def list_events(self, calendar_id, time_min, time_max):
        """Every single occurrence, deleted ones included, in [time_min, time_max)."""
        url = self._events_url(calendar_id)
        events = []
        page_token = None
        for _ in range(MAX_PAGES):
            params = {
                "singleEvents": "true",
                "showDeleted": "true",
                "orderBy": "startTime",
                "maxResults": PAGE_SIZE,
                "timeMin": time_min,
                "timeMax": time_max,
            }
            if page_token:
                params["pageToken"] = page_token
            page = self.transport.request(url, params=params)
            if not isinstance(page, dict):
                logger.warning(
                    "Calendar page unavailable for %s; keeping %d events",
                    calendar_id,
                    len(events),
                )
                break
            events.extend(page.get("items", []))
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        else:
            logger.warning(
                "Calendar pagination stopped at %d pages for %s", MAX_PAGES, calendar_id
            )
        return events
