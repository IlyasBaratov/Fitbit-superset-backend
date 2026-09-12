import json
import socket
import urllib.parse
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
import pytest
import requests
from app.core.config import WorkerSettings
from app.core.exceptions import AuthenticationError
from app.providers.google_calendar.connect import (
    SCOPE,
    authorization_url,
    exchange_code,
    revoke,
    token_record,
)
from scripts.google_calendar_authorize import callback_handler, save_token

REDIRECT_URI = "http://localhost:8765/"


@pytest.fixture
def calendar_settings(monkeypatch, tmp_path):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    return replace(
        WorkerSettings.from_env(),
        token_file_path=str(tmp_path / "token.json"),
        calendar_token_file_path=str(tmp_path / "tokens" / "google_calendar.token"),
        calendar_client_id="calendar-id",
        calendar_client_secret="calendar-client-secret",
    )


def _exchange_session(payload, status=200):
    session = Mock()
    session.post.return_value.status_code = status
    session.post.return_value.json.return_value = payload
    return session


def _drive(handler_class, path):
    client, server = socket.socketpair()
    try:
        client.sendall(f"GET {path} HTTP/1.0\r\n\r\n".encode("utf-8"))
        handler_class(server, ("127.0.0.1", 44444), Mock())
        client.settimeout(5)
        return client.recv(65536).decode("utf-8", "replace")
    finally:
        client.close()
        server.close()


def test_authorization_url_asks_for_offline_read_only_access():
    url = authorization_url("client", REDIRECT_URI, "nonce")
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://accounts.google.com/o/oauth2/v2/auth"
    assert query["client_id"] == ["client"]
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert query["response_type"] == ["code"]
    assert query["scope"] == [SCOPE] == ["https://www.googleapis.com/auth/calendar.events.readonly"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["state"] == ["nonce"]


def test_exchange_code_posts_the_authorization_grant():
    session = _exchange_session({"access_token": "a", "refresh_token": "r"})
    assert exchange_code(session, "id", "secret", REDIRECT_URI, "the-code", 30) == {"access_token": "a", "refresh_token": "r"}
    sent = session.post.call_args
    assert sent.args[0] == "https://oauth2.googleapis.com/token"
    assert sent.kwargs["data"] == {"client_id": "id", "client_secret": "secret", "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI, "code": "the-code"}
    assert sent.kwargs["timeout"] == 30


def test_exchange_code_failure_never_echoes_the_response():
    session = _exchange_session({"error_description": "client-secret leaked"}, status=400)
    session.post.return_value.text = "id secret the-code"
    with pytest.raises(AuthenticationError) as error:
        exchange_code(session, "id", "secret", REDIRECT_URI, "the-code", 30)
    assert "HTTP 400" in str(error.value)
    for phrase in ("secret", "the-code", "leaked"):
        assert phrase not in str(error.value)


def test_exchange_code_requires_a_refresh_token():
    session = _exchange_session({"access_token": "a"})
    with pytest.raises(AuthenticationError, match="refresh token"):
        exchange_code(session, "id", "secret", REDIRECT_URI, "code", 30)


def test_exchange_code_survives_a_network_failure():
    session = Mock()
    session.post.side_effect = requests.ConnectionError("boom")
    with pytest.raises(AuthenticationError, match="client credentials"):
        exchange_code(session, "id", "secret", REDIRECT_URI, "code", 30)


def test_token_record_matches_the_token_file_shape():
    record = token_record({"access_token": "a", "refresh_token": "r", "expires_in": "3600", "scope": "ignored"})
    assert record["provider"] == "google_calendar"
    assert record["access_token"] == "a"
    assert record["refresh_token"] == "r"
    assert record["expires_in"] == 3600
    assert record["saved_at_utc"].endswith("+00:00")
    assert set(record) == {"provider", "access_token", "refresh_token", "expires_in", "saved_at_utc"}


def test_revoke_is_best_effort():
    session = Mock()
    session.post.return_value.status_code = 200
    assert revoke(session, "refresh", 30) is True
    assert session.post.call_args.args[0] == "https://oauth2.googleapis.com/revoke"
    assert session.post.call_args.kwargs["data"] == {"token": "refresh"}
    session.post.side_effect = requests.ConnectionError("boom")
    assert revoke(session, "refresh", 30) is False


def test_callback_writes_the_calendar_token_file(calendar_settings):
    session = _exchange_session({"access_token": "calendar-access", "refresh_token": "calendar-refresh", "expires_in": 3599})
    handler = callback_handler("nonce", lambda code: save_token(calendar_settings, session, REDIRECT_URI, code))
    response = _drive(handler, "/?state=nonce&code=granted")
    assert response.startswith("HTTP/1.0 200")
    assert "connected" in response
    assert "calendar-access" not in response and "calendar-refresh" not in response
    saved = json.loads(Path(calendar_settings.calendar_token_file_path).read_text(encoding="utf-8"))
    assert saved["provider"] == "google_calendar"
    assert saved["refresh_token"] == "calendar-refresh"
    assert session.post.call_args.kwargs["data"]["code"] == "granted"
    assert not Path(calendar_settings.token_file_path).exists()


@pytest.mark.parametrize("path", ["/?state=wrong&code=granted", "/?code=granted", "/?state=nonce", "/?state=nonce&error=access_denied"])
def test_callback_rejects_anything_but_the_expected_state(calendar_settings, path):
    def complete(_code):
        raise AssertionError("the authorization code must not be exchanged")

    response = _drive(callback_handler("nonce", complete), path)
    assert response.startswith("HTTP/1.0 400")
    assert not Path(calendar_settings.calendar_token_file_path).exists()


def test_callback_reports_a_failed_exchange_without_writing(calendar_settings):
    session = _exchange_session({"error": "invalid_grant"}, status=400)
    handler = callback_handler("nonce", lambda code: save_token(calendar_settings, session, REDIRECT_URI, code))
    response = _drive(handler, "/?state=nonce&code=granted")
    assert response.startswith("HTTP/1.0 400")
    assert not Path(calendar_settings.calendar_token_file_path).exists()
