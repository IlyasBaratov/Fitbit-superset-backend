import json
from dataclasses import replace
from unittest.mock import Mock
import pytest
from app.core.config import WorkerSettings
from app.core.exceptions import AuthenticationError
from app.providers.fitbit.auth import FitbitTokenManager

@pytest.fixture
def token_settings(monkeypatch, tmp_path):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    return replace(WorkerSettings.from_env(), token_file_path=str(tmp_path / "token.json"), client_id="id", client_secret="secret", google_client_id="id", google_client_secret="secret")


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
