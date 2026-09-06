import logging
from app.core.logging import SecretFilter
from app.core.exceptions import ConfigurationError
from app.core.config import WorkerSettings
import pytest


def test_secret_filter_redacts_interpolated_values():
    record = logging.LogRecord("test", 20, "", 1, "credential=%s", ("secret",), None)
    assert SecretFilter(["secret"]).filter(record)
    assert record.getMessage() == "credential=[REDACTED]"


def test_invalid_provider_configuration(monkeypatch):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    monkeypatch.setenv("HEALTH_API_PROVIDER", "unknown")
    with pytest.raises(ConfigurationError):
        WorkerSettings.from_env()
