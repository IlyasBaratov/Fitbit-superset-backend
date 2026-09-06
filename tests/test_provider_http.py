from dataclasses import replace
from unittest.mock import Mock
import pytest
import requests
from app.core.config import WorkerSettings
from app.core.exceptions import ProviderError
from app.providers.http import ProviderHTTPClient


def response(status, headers=None):
    value = Mock(status_code=status, headers=headers or {})
    value.json.return_value = {"ok": True}
    if status >= 400:
        value.raise_for_status.side_effect = requests.HTTPError(response=value)
    return value


def setup(monkeypatch):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    settings = replace(WorkerSettings.from_env(), health_api_provider="fitbit", request_max_retries=2)
    token = Mock()
    token.get_access_token.return_value = "secret"
    session, sleep = Mock(), Mock()
    return ProviderHTTPClient(settings, token, session, sleep), session, token, sleep


def test_refresh_and_rate_limit(monkeypatch):
    client, session, token, sleep = setup(monkeypatch)
    session.request.side_effect = [response(401), response(429, {"Retry-After": "2"}), response(200)]
    assert client.request("https://example.test/data") == {"ok": True}
    token.refresh.assert_called_once()
    sleep.assert_called_once_with(2)
    assert session.request.call_args.kwargs["timeout"] == 30


def test_network_exhaustion(monkeypatch):
    client, session, token, sleep = setup(monkeypatch)
    session.request.side_effect = requests.Timeout("secret")
    with pytest.raises(ProviderError, match="budget"):
        client.request("https://example.test/data")
    assert session.request.call_count == 3


def test_permanent_error_is_not_retried(monkeypatch):
    client, session, token, sleep = setup(monkeypatch)
    session.request.return_value = response(403)
    with pytest.raises(requests.HTTPError):
        client.request("https://example.test/data")
    assert session.request.call_count == 1


def test_server_failures_are_bounded(monkeypatch):
    client, session, token, sleep = setup(monkeypatch)
    session.request.return_value = response(503)
    assert client.request("https://example.test/data") is None
    assert session.request.call_count == 3
