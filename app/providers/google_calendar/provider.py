"""Calendar fetch orchestration; an unconnected calendar never stops health collection."""

from datetime import date, timedelta
import logging
import requests
from app.core.exceptions import AuthenticationError, ProviderError
from app.domain.models import HealthPoint
from app.domain.normalization import local_date_boundary_utc
from app.providers.http import log_metric_http_error
from app.providers.google_calendar.mapper import map_events

logger = logging.getLogger(__name__)


class GoogleCalendarProvider:
    def __init__(self, settings, client, timezone):
        self.settings, self.client, self.timezone = settings, client, timezone
        self._connected = None

    def _available(self, calendar_id, call, *args):
        name = "calendar " + str(calendar_id)
        try:
            return call(*args)
        except requests.HTTPError as error:
            log_metric_http_error(name, error)
            return None
        except ProviderError:
            logger.warning("%s unavailable after provider retries", name)
            return None

    def fetch_events(self, start_date: str, end_date: str) -> list[HealthPoint]:
        """Whole local days [start_date, end_date] as the half-open UTC window Google expects."""
        try:
            points = self._collect(start_date, end_date)
        except AuthenticationError:
            self._note_connection(False)
            return []
        self._note_connection(True)
        return points

    def _collect(self, start_date, end_date):
        zone = self.timezone.zone
        time_min = local_date_boundary_utc(start_date, zone)
        time_max = local_date_boundary_utc(
            date.fromisoformat(str(end_date)) + timedelta(days=1), zone
        )
        points = []
        for calendar_id in self.settings.calendar_ids:
            items = self._available(
                calendar_id, self.client.list_events, calendar_id, time_min, time_max
            )
            if items is None:
                continue
            points.extend(map_events(items, calendar_id, self.timezone))
        return points

    def _note_connection(self, connected: bool) -> None:
        """One line per state change; a job running every 15 minutes must not repeat itself."""
        if self._connected is connected:
            return
        self._connected = connected
        if connected:
            logger.info("Google Calendar connected")
        else:
            logger.warning(
                "Google Calendar is not connected; skipping calendar sync until it is"
            )

    def refresh_credentials(self) -> str:
        return self.client.transport.token_manager.refresh()

    def close(self) -> None:
        try:
            self.client.transport.close()
        finally:
            self.client.transport.token_manager.close()
