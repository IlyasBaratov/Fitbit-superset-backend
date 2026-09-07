import json
import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
import pytest
from app.core.config import WorkerSettings
from app.core.exceptions import AuthenticationError
from app.providers.fitbit.auth import FitbitTokenManager
from app.providers.google_calendar.auth import GoogleCalendarTokenManager

@pytest.fixture
def token_settings(monkeypatch, tmp_path):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    return replace(WorkerSettings.from_env(), token_file_path=str(tmp_path / "token.json"), client_id="id", client_secret="secret", google_client_id="id", google_client_secret="secret")


@pytest.fixture
def calendar_settings(token_settings, tmp_path):
    return replace(token_settings, calendar_token_file_path=str(tmp_path / "google_calendar.token"), calendar_client_id="calendar-id", calendar_client_secret="calendar-client-secret")


def test_fitbit_rotation(token_settings):
    from pathlib import Path
    path = Path(token_settings.token_file_path)
    path.write_text(json.dumps({"refresh_token": "old"}))
    session = Mock()
    session.post.return_value.status_code = 200
    session.post.return_value.json.return_value = {"access_token": "access", "refresh_token": "rotated", "expires_in": 3600}
    manager = FitbitTokenManager(token_settings, session)
    assert manager.refresh() == "access"
    assert manager.get_access_token() == "access"
    assert json.loads(path.read_text())["refresh_token"] == "rotated"
    assert session.post.call_args.kwargs["timeout"] == token_settings.request_timeout_seconds


def test_missing_token_never_prompts(token_settings, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("stdin"))
    with pytest.raises(AuthenticationError, match="TOKEN_FILE_PATH"):
        FitbitTokenManager(token_settings, Mock()).get_access_token()


def test_provider_mismatch(token_settings):
    from pathlib import Path
    Path(token_settings.token_file_path).write_text(json.dumps({"provider": "google", "refresh_token": "r"}))
    session = Mock()
    with pytest.raises(AuthenticationError, match="provider"):
        FitbitTokenManager(token_settings, session).refresh()
    session.post.assert_not_called()


def test_calendar_refresh_uses_its_own_file_and_credentials(calendar_settings):
    calendar_path = Path(calendar_settings.calendar_token_file_path)
    health_path = Path(calendar_settings.token_file_path)
    health_token = {"provider": "google", "refresh_token": "health-refresh"}
    health_path.write_text(json.dumps(health_token))
    calendar_path.write_text(json.dumps({"provider": "google_calendar", "refresh_token": "calendar-refresh"}))
    session = Mock()
    session.post.return_value.status_code = 200
    session.post.return_value.json.return_value = {"access_token": "calendar-access"}
    manager = GoogleCalendarTokenManager(calendar_settings, session)
    assert manager.refresh() == "calendar-access"
    saved = json.loads(calendar_path.read_text())
    assert saved["provider"] == "google_calendar"
    assert saved["refresh_token"] == "calendar-refresh"
    assert saved["access_token"] == "calendar-access"
    assert session.post.call_args.kwargs["data"]["client_id"] == "calendar-id"
    assert session.post.call_args.kwargs["data"]["client_secret"] == "calendar-client-secret"
    assert json.loads(health_path.read_text()) == health_token


def test_calendar_rejects_a_health_token_file(calendar_settings):
    Path(calendar_settings.calendar_token_file_path).write_text(json.dumps({"provider": "google", "refresh_token": "health-refresh"}))
    session = Mock()
    with pytest.raises(AuthenticationError, match="provider"):
        GoogleCalendarTokenManager(calendar_settings, session).get_access_token()
    session.post.assert_not_called()


def test_calendar_failure_never_echoes_secrets(calendar_settings):
    Path(calendar_settings.calendar_token_file_path).write_text(json.dumps({"provider": "google_calendar", "refresh_token": "calendar-refresh-secret"}))
    session = Mock()
    session.post.return_value.status_code = 400
    session.post.return_value.text = "calendar-refresh-secret calendar-client-secret"
    with pytest.raises(AuthenticationError) as error:
        GoogleCalendarTokenManager(calendar_settings, session).refresh()
    assert "calendar-refresh-secret" not in str(error.value)
    assert "calendar-client-secret" not in str(error.value)


def test_calendar_token_reloads_after_reconnect(calendar_settings):
    path = Path(calendar_settings.calendar_token_file_path)
    path.write_text(json.dumps({"provider": "google_calendar", "refresh_token": "first", "access_token": "first-access"}))
    session = Mock()
    manager = GoogleCalendarTokenManager(calendar_settings, session)
    assert manager.get_access_token() == "first-access"
    path.write_text(json.dumps({"provider": "google_calendar", "refresh_token": "second", "access_token": "second-access"}))
    changed = path.stat().st_mtime_ns + 1_000_000_000
    os.utime(path, ns=(changed, changed))
    assert manager.get_access_token() == "second-access"
    session.post.assert_not_called()


def test_google_retains_refresh_token_and_sanitizes_errors(token_settings):
    from pathlib import Path
    from app.providers.google_health.auth import GoogleTokenManager
    path = Path(token_settings.token_file_path)
    path.write_text(json.dumps({"provider": "google", "refresh_token": "original-secret"}))
    session = Mock()
    session.post.return_value.status_code = 200
    session.post.return_value.json.return_value = {"access_token": "new-access"}
    manager = GoogleTokenManager(token_settings, session)
    assert manager.refresh() == "new-access"
    assert json.loads(path.read_text())["refresh_token"] == "original-secret"
    session.post.return_value.status_code = 400
    session.post.return_value.text = "original-secret"
    with pytest.raises(AuthenticationError) as error:
        manager.refresh()
    assert "original-secret" not in str(error.value)
    assert json.loads(path.read_text())["access_token"] == "new-access"
