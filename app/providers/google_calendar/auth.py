"""Calendar OAuth refresh against a separate token file."""

from dataclasses import replace
from pathlib import Path
from app.providers.google_health.auth import GoogleTokenManager


class GoogleCalendarTokenManager(GoogleTokenManager):
    provider = "google_calendar"

    def __init__(self, settings, session=None):
        super().__init__(
            replace(
                settings,
                token_file_path=settings.calendar_token_file_path,
                google_client_id=settings.calendar_client_id,
                google_client_secret=settings.calendar_client_secret,
            ),
            session,
        )
        self._loaded_mtime = None

    def load(self) -> None:
        super().load()
        self._loaded_mtime = self._token_file_mtime()

    def get_access_token(self) -> str:
        if (
            self._refresh_token is not None
            and self._token_file_mtime() != self._loaded_mtime
        ):
            self._access_token = self._refresh_token = None
        return super().get_access_token()

    def _save(self, tokens):
        super()._save(tokens)
        self._loaded_mtime = self._token_file_mtime()

    def _token_file_mtime(self):
        try:
            return Path(self.settings.token_file_path).stat().st_mtime_ns
        except OSError:
            return None
