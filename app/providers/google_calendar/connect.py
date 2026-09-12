"""Calendar OAuth connect helpers; no I/O beyond the injected session."""

from datetime import datetime, timezone
import urllib.parse
import requests
from app.core.exceptions import AuthenticationError

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"


def authorization_url(client_id, redirect_uri, state) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{AUTHORIZATION_ENDPOINT}?{query}"


def exchange_code(session, client_id, client_secret, redirect_uri, code, timeout):
    try:
        response = session.post(
            TOKEN_ENDPOINT,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
            timeout=timeout,
        )
        if response.status_code != 200:
            raise AuthenticationError(
                f"google_calendar authorization exchange failed (HTTP {response.status_code})"
            )
        payload = response.json()
        if not isinstance(payload.get("access_token"), str) or not isinstance(
            payload.get("refresh_token"), str
        ):
            raise AuthenticationError(
                "google_calendar authorization returned no refresh token; re-authorize with a consent prompt"
            )
        return payload
    except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
        if isinstance(exc, AuthenticationError):
            raise
        raise AuthenticationError(
            "google_calendar authorization exchange failed; check the client credentials and redirect URI"
        ) from None


def token_record(payload) -> dict:
    record = {
        "provider": "google_calendar",
        "access_token": payload["access_token"],
        "refresh_token": payload["refresh_token"],
        "saved_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    if payload.get("expires_in") is not None:
        record["expires_in"] = int(payload["expires_in"])
    return record


def revoke(session, token, timeout) -> bool:
    """Best effort: a failed revocation still lets the caller drop the token file."""
    try:
        return (
            session.post(
                REVOKE_ENDPOINT, data={"token": token}, timeout=timeout
            ).status_code
            == 200
        )
    except (requests.RequestException, AttributeError):
        return False
