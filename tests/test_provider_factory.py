from dataclasses import replace
from unittest.mock import Mock
import pytest
from app.core.config import WorkerSettings
from app.providers.factory import create_provider
from app.providers.fitbit.provider import FitbitProvider
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
