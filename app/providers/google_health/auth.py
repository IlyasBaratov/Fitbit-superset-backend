"""Google OAuth refresh using the existing token file format."""
from app.providers.auth import FileTokenManager
from app.core.exceptions import AuthenticationError

class GoogleTokenManager(FileTokenManager):
    provider = "google"

    def _request_refresh(self):
        cfg = self.settings
        if not cfg.google_client_id or not cfg.google_client_secret or cfg.google_client_id == "your_application_client_ID":
            raise AuthenticationError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required (CLIENT_ID/CLIENT_SECRET remain fallbacks)")
        return self.session.post(cfg.google_oauth_token_url,
            data={"client_id": cfg.google_client_id, "client_secret": cfg.google_client_secret,
                  "grant_type": "refresh_token", "refresh_token": self._refresh_token},
            timeout=cfg.request_timeout_seconds)
