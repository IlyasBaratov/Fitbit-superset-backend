"""Single-use nonce store and orchestration for the calendar OAuth flow (D13).

The API runs one uvicorn worker, so pending nonces live in this process only.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import secrets
import requests
from app.core.exceptions import AuthenticationError
from app.errors import APIError
from app.providers.google_calendar.auth import GoogleCalendarTokenManager
from app.providers.google_calendar.connect import (
    authorization_url,
    exchange_code,
    token_record,
)

STATE_TTL_SECONDS = 600
MAX_PENDING_STATES = 10
EXCHANGE_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class CalendarTokenSettings:
    """The slice of collector configuration the calendar token manager reads."""

    token_file_path: str = ""
    calendar_token_file_path: str = ""
    calendar_client_id: str = ""
    calendar_client_secret: str = field(default="", repr=False)
    google_client_id: str = ""
    google_client_secret: str = field(default="", repr=False)
    google_oauth_token_url: str = "https://oauth2.googleapis.com/token"
    request_timeout_seconds: int = EXCHANGE_TIMEOUT_SECONDS


class CalendarConnectService:
    """Hands out single-use authorization nonces and stores the granted token."""

    def __init__(self, settings, session=None, clock=None):
        self.settings = settings
        self.session = session or requests.Session()
        self._owns_session = session is None
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._pending = {}

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.calendar_client_id
            and self.settings.calendar_client_secret
            and self.settings.calendar_token_file_path
        )

    def begin(self) -> dict:
        self._require_configuration()
        self._expire()
        while len(self._pending) >= MAX_PENDING_STATES:
            self._pending.pop(next(iter(self._pending)))
        state = secrets.token_urlsafe(32)
        self._pending[state] = self.clock().timestamp() + STATE_TTL_SECONDS
        return {
            "authorization_url": authorization_url(
                self.settings.calendar_client_id,
                self.settings.calendar_redirect_uri,
                state,
            ),
            "expires_in": STATE_TTL_SECONDS,
        }

    def complete(self, state, code, error="") -> None:
        self._require_configuration()
        self._expire()
        if error or not state or not code or self._pending.pop(state, None) is None:
            raise self._rejected()
        try:
            payload = exchange_code(
                self.session,
                self.settings.calendar_client_id,
                self.settings.calendar_client_secret,
                self.settings.calendar_redirect_uri,
                code,
                EXCHANGE_TIMEOUT_SECONDS,
            )
        except AuthenticationError:
            raise self._rejected() from None
        self._store(token_record(payload))

    def close(self) -> None:
        if self._owns_session:
            self.session.close()

    def _store(self, record):
        manager = GoogleCalendarTokenManager(self._token_settings(), self.session)
        Path(manager.settings.token_file_path).parent.mkdir(parents=True, exist_ok=True)
        manager._save(record)

    def _token_settings(self):
        return CalendarTokenSettings(
            calendar_token_file_path=self.settings.calendar_token_file_path,
            calendar_client_id=self.settings.calendar_client_id,
            calendar_client_secret=self.settings.calendar_client_secret,
        )

    def _expire(self):
        now = self.clock().timestamp()
        for state in [
            state for state, deadline in self._pending.items() if deadline <= now
        ]:
            del self._pending[state]

    def _require_configuration(self):
        if not self.configured:
            raise APIError(
                "CALENDAR_NOT_CONFIGURED",
                "Google Calendar connection is not configured on this server.",
                503,
            )

    @staticmethod
    def _rejected():
        return APIError(
            "CALENDAR_CONNECT_REJECTED",
            "The authorization response was rejected; start again at /api/calendar/connect.",
            400,
        )
