"""Google OAuth refresh using the existing token file format."""

from app.providers.auth import FileTokenManager
from app.core.exceptions import AuthenticationError


class GoogleTokenManager(FileTokenManager):
    provider = "google"

    def _request_refresh(self):
        cfg = self.settings
        if (
            not cfg.google_client_id
            or not cfg.google_client_secret
            or cfg.google_client_id == "your_application_client_ID"
        ):
            raise AuthenticationError(
                "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required (CLIENT_ID/CLIENT_SECRET remain fallbacks)"
            )
        data = {
            "client_id": cfg.google_client_id,
            "client_secret": cfg.google_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }
        response = self.session.post(
            cfg.google_oauth_token_url,
            data=data,
            timeout=cfg.request_timeout_seconds,
        )
        if response.status_code != 200:
            return response

        # Google Health rejects an access token containing unrelated scopes such
        # as cloud-platform, even when all required Health scopes are present.
        granted = response.json().get("scope", "").split()
        health_scopes = [
            scope
            for scope in granted
            if scope.startswith("https://www.googleapis.com/auth/googlehealth.")
            and scope.endswith(".readonly")
        ]
        if health_scopes and len(health_scopes) != len(granted):
            return self.session.post(
                cfg.google_oauth_token_url,
                data={**data, "scope": " ".join(health_scopes)},
                timeout=cfg.request_timeout_seconds,
            )
        return response
