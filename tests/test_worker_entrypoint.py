from dataclasses import replace
from unittest.mock import Mock
import pytest
from app.core.config import WorkerSettings
from app.core.exceptions import ConfigurationError
from app.worker.main import run


def test_missing_manual_dates_fail_before_network(monkeypatch):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    provider = Mock()
    monkeypatch.setattr("app.worker.main.create_provider", provider)
    cfg = replace(WorkerSettings.from_env(), auto_date_range=False, manual_start_date=None, manual_end_date=None)
    with pytest.raises(ConfigurationError):
        run(cfg)
    provider.assert_not_called()


def test_resources_close_when_scheduling_fails(monkeypatch):
    import pytz
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    provider, repository = Mock(), Mock()
    provider.device_name, provider.timezone = "Watch", pytz.utc
    monkeypatch.setattr("app.worker.main.create_provider", lambda _: provider)
    monkeypatch.setattr("app.worker.main.InfluxHealthRepository", lambda *_: repository)
    scheduler = Mock()
    scheduler.run.side_effect = RuntimeError("test")
    monkeypatch.setattr("app.worker.main.IngestionScheduler", lambda *_, **__: scheduler)
    with pytest.raises(RuntimeError):
        run(replace(WorkerSettings.from_env(), auto_date_range=True))
    provider.close.assert_called_once()
    repository.close.assert_called_once()


def test_calendar_resources_are_built_and_closed(monkeypatch):
    import pytz
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    provider, calendar = Mock(), Mock()
    provider.device_name, provider.timezone = "Watch", pytz.utc
    repositories = []
    monkeypatch.setattr("app.worker.main.create_provider", lambda _: provider)
    monkeypatch.setattr("app.worker.main.create_calendar_provider", lambda *_: calendar)
    def repository(settings, tags, zone):
        repositories.append((Mock(), tags))
        return repositories[-1][0]
    monkeypatch.setattr("app.worker.main.InfluxHealthRepository", repository)
    services = []
    monkeypatch.setattr("app.worker.main.IngestionService", lambda *args: services.append(args) or Mock())
    scheduler = Mock()
    scheduler.run.side_effect = RuntimeError("test")
    monkeypatch.setattr("app.worker.main.IngestionScheduler", lambda *_, **__: scheduler)
    settings = replace(WorkerSettings.from_env(), auto_date_range=True, calendar_sync_enabled=True)
    with pytest.raises(RuntimeError):
        run(settings)
    assert [tags for _, tags in repositories][1] == {
        "UserId": settings.user_id,
        "Provider": "google_calendar",
        "Device": "Google Calendar",
        "DeviceId": "google_calendar",
    }
    assert services[0][3:] == (calendar, repositories[1][0])
    for closeable in (provider, calendar, repositories[0][0], repositories[1][0]):
        closeable.close.assert_called_once()


def test_calendar_resources_are_absent_when_sync_is_disabled(monkeypatch):
    import pytz
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    provider, repository = Mock(), Mock()
    provider.device_name, provider.timezone = "Watch", pytz.utc
    monkeypatch.setattr("app.worker.main.create_provider", lambda _: provider)
    monkeypatch.setattr("app.worker.main.InfluxHealthRepository", lambda *_: repository)
    services = []
    monkeypatch.setattr("app.worker.main.IngestionService", lambda *args: services.append(args) or Mock())
    scheduler = Mock()
    scheduler.run.side_effect = RuntimeError("test")
    monkeypatch.setattr("app.worker.main.IngestionScheduler", lambda *_, **__: scheduler)
    with pytest.raises(RuntimeError):
        run(replace(WorkerSettings.from_env(), auto_date_range=True, calendar_sync_enabled=False))
    assert services[0][3:] == (None, None)
