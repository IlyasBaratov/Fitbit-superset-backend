from dataclasses import replace
from unittest.mock import Mock
import pytest
import pytz
from app.core.config import WorkerSettings
from app.providers.factory import create_calendar_provider, create_provider
from app.providers.fitbit.provider import FitbitProvider
from app.providers.google_calendar.provider import GoogleCalendarProvider
from app.providers.google_health.provider import GoogleHealthProvider


@pytest.mark.parametrize("kind,expected", [("fitbit", FitbitProvider), ("google", GoogleHealthProvider)])
def test_factory_selects_provider_and_owns_identity(monkeypatch, kind, expected):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    cfg = replace(WorkerSettings.from_env(), health_api_provider=kind, local_timezone="Automatic", devicename="Your_Device_Name")
    token, transport, client = Mock(), Mock(), Mock()
    transport.token_manager = token
    client.transport = transport
    client.get_timezone_name.return_value = "UTC"
    client.discover_google_device_metadata.return_value = {"deviceName": "Discovered watch", "deviceModel": "Model"}
    selected_auth, other_auth = Mock(return_value=token), Mock(side_effect=AssertionError("wrong provider"))
    selected_client = Mock(return_value=client)
    monkeypatch.setattr("app.providers.factory.ProviderHTTPClient", lambda *_: transport)
    monkeypatch.setattr("app.providers.factory." + ("FitbitTokenManager" if kind == "fitbit" else "GoogleTokenManager"), selected_auth)
    monkeypatch.setattr("app.providers.factory." + ("GoogleTokenManager" if kind == "fitbit" else "FitbitTokenManager"), other_auth)
    monkeypatch.setattr("app.providers.factory." + ("FitbitClient" if kind == "fitbit" else "GoogleHealthClient"), selected_client)
    provider = create_provider(cfg)
    assert isinstance(provider, expected)
    assert provider.timezone.zone == "UTC"
    if kind == "google":
        assert provider.device_name == "Discovered watch"
    token.refresh.assert_called_once()
    provider.close()
    transport.close.assert_called_once()
    token.close.assert_called_once()


def calendar_settings(monkeypatch, **overrides):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    return replace(WorkerSettings.from_env(), **overrides)


def test_calendar_provider_is_absent_while_the_sync_is_disabled(monkeypatch):
    cfg = calendar_settings(monkeypatch, calendar_sync_enabled=False)
    monkeypatch.setattr("app.providers.factory.GoogleCalendarTokenManager", Mock(side_effect=AssertionError("token manager built")))

    assert create_calendar_provider(cfg, pytz.utc) is None


def test_calendar_provider_is_built_without_refreshing_at_startup(monkeypatch):
    cfg = calendar_settings(monkeypatch, calendar_sync_enabled=True, calendar_ids=("primary",))
    token, transport = Mock(), Mock()
    transport.token_manager = token
    monkeypatch.setattr("app.providers.factory.GoogleCalendarTokenManager", Mock(return_value=token))
    monkeypatch.setattr("app.providers.factory.ProviderHTTPClient", lambda *_: transport)

    provider = create_calendar_provider(cfg, pytz.timezone("Europe/Berlin"))
    assert isinstance(provider, GoogleCalendarProvider)
    assert provider.timezone.zone == "Europe/Berlin"
    assert provider.client.transport is transport
    token.refresh.assert_not_called()
    token.load.assert_not_called()
    provider.close()
    transport.close.assert_called_once()
    token.close.assert_called_once()
