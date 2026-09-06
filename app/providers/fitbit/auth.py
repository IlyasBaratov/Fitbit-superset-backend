"""Fitbit OAuth token refresh."""

import base64
from app.providers.auth import FileTokenManager
from app.core.exceptions import AuthenticationError


class FitbitTokenManager(FileTokenManager):
    provider = "fitbit"

    def _request_refresh(self):
        cfg = self.settings
        if (
            not cfg.client_id
            or not cfg.client_secret
            or cfg.client_id == "your_application_client_ID"
        ):
            raise AuthenticationError("CLIENT_ID and CLIENT_SECRET are required")
        credentials = base64.b64encode(
            f"{cfg.client_id}:{cfg.client_secret}".encode()
        ).decode()
        return self.session.post(
            f"{cfg.fitbit_api_base_url}/oauth2/token",
            headers={
                "Authorization": "Basic " + credentials,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "refresh_token", "refresh_token": self._refresh_token},
            timeout=cfg.request_timeout_seconds,
        )
