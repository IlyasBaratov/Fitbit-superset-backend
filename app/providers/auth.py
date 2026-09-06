"""Token-file compatibility and per-instance OAuth lifecycle."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import requests
from app.core.exceptions import AuthenticationError


class FileTokenManager:
    provider = ""

    def __init__(self, settings, session=None):
        self.settings = settings
        self.session = session or requests.Session()
        self._owns_session = session is None
        self._access_token = None
        self._refresh_token = None

    def load(self) -> None:
        try:
            tokens = json.loads(
                Path(self.settings.token_file_path).read_text(encoding="utf-8")
            )
            provider = (tokens.get("provider") or "fitbit").lower()
            if provider != self.provider:
                raise AuthenticationError(
                    "Token file provider does not match HEALTH_API_PROVIDER"
                )
            refresh = tokens.get("refresh_token")
            if not isinstance(refresh, str) or not refresh.strip():
                raise AuthenticationError("Token file requires a refresh_token")
            self._refresh_token = refresh
            self._access_token = tokens.get("access_token") or None
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            if isinstance(exc, AuthenticationError):
                raise
            raise AuthenticationError(
                "Cannot load token file; configure TOKEN_FILE_PATH with valid OAuth tokens"
            ) from None

    def get_access_token(self) -> str:
        if self._refresh_token is None:
            self.load()
        return self._access_token or self.refresh()

    def refresh(self) -> str:
        if self._refresh_token is None:
            self.load()
        try:
            response = self._request_refresh()
            if response.status_code != 200:
                raise AuthenticationError(
                    f"{self.provider} token refresh failed (HTTP {response.status_code})"
                )
            payload = response.json()
            access = payload["access_token"]
            refresh = payload.get("refresh_token") or self._refresh_token
            if (
                not isinstance(access, str)
                or not access.strip()
                or not isinstance(refresh, str)
            ):
                raise AuthenticationError("OAuth returned invalid tokens")
            tokens = {
                "provider": self.provider,
                "access_token": access,
                "refresh_token": refresh,
                "saved_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            if payload.get("expires_in") is not None:
                tokens["expires_in"] = int(payload["expires_in"])
            self._save(tokens)
            self._access_token, self._refresh_token = access, refresh
            return access
        except (
            requests.RequestException,
            KeyError,
            ValueError,
            TypeError,
            OSError,
        ) as exc:
            if isinstance(exc, AuthenticationError):
                raise
            raise AuthenticationError(
                f"{self.provider} token refresh failed; check credentials and token file"
            ) from None

    def _save(self, tokens):
        path = Path(self.settings.token_file_path)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as out:
                temporary = out.name
                json.dump(tokens, out)
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def close(self) -> None:
        if self._owns_session:
            self.session.close()
