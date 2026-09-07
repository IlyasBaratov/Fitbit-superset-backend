from dataclasses import FrozenInstanceError
import os
import pytest
from app.core.config import WorkerSettings
from app.core.exceptions import ConfigurationError


def test_worker_settings_do_not_require_ai(monkeypatch):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    monkeypatch.delenv("AI_API_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("CLIENT_SECRET", "never-print-this")
    monkeypatch.setenv("HEALTH_API_PROVIDER", "google")
    cfg = WorkerSettings.from_env()
    assert cfg.google_client_secret == "never-print-this"
    assert "never-print-this" not in repr(cfg)
    assert isinstance(cfg.influxdb_port, int)
    with pytest.raises(FrozenInstanceError):
        cfg.user_id = "other"


def test_worker_manual_range_defaults(monkeypatch):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    monkeypatch.setenv("MANUAL_START_DATE", "2026-08-01")
    monkeypatch.delenv("AUTO_DATE_RANGE", raising=False)
    assert WorkerSettings.from_env().auto_date_range is False


CALENDAR_ENV = (
    "CALENDAR_SYNC_ENABLED",
    "CALENDAR_TOKEN_FILE_PATH",
    "CALENDAR_IDS",
    "CALENDAR_CLIENT_ID",
    "CALENDAR_CLIENT_SECRET",
    "CALENDAR_SYNC_DAYS_BACK",
    "CALENDAR_SYNC_DAYS_AHEAD",
    "CALENDAR_API_BASE_URL",
)


@pytest.fixture
def calendar_env(monkeypatch):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    for name in CALENDAR_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TOKEN_FILE_PATH", "/app/tokens/fitbit.token")
    return monkeypatch


def test_calendar_settings_defaults(calendar_env):
    cfg = WorkerSettings.from_env()
    assert cfg.calendar_sync_enabled is False
    assert cfg.calendar_token_file_path == os.path.join(
        "/app/tokens", "google_calendar.token"
    )
    assert cfg.calendar_ids == ("primary",)
    assert cfg.calendar_sync_days_back == 7
    assert cfg.calendar_sync_days_ahead == 1
    assert cfg.calendar_api_base_url == "https://www.googleapis.com/calendar/v3"


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "Y"])
def test_calendar_sync_enabled_truthy_values(calendar_env, value):
    calendar_env.setenv("CALENDAR_SYNC_ENABLED", value)
    assert WorkerSettings.from_env().calendar_sync_enabled is True


@pytest.mark.parametrize("value", ["false", "0", "no", ""])
def test_calendar_sync_enabled_falsy_values(calendar_env, value):
    calendar_env.setenv("CALENDAR_SYNC_ENABLED", value)
    assert WorkerSettings.from_env().calendar_sync_enabled is False


def test_calendar_ids_parse_comma_list_and_strip_empties(calendar_env):
    calendar_env.setenv("CALENDAR_IDS", " primary , ,work@example.com,, ")
    assert WorkerSettings.from_env().calendar_ids == ("primary", "work@example.com")


def test_calendar_ids_fall_back_to_primary_when_blank(calendar_env):
    calendar_env.setenv("CALENDAR_IDS", " , ")
    assert WorkerSettings.from_env().calendar_ids == ("primary",)


def test_calendar_credentials_fall_back_to_google(calendar_env):
    calendar_env.setenv("GOOGLE_CLIENT_ID", "google-id")
    calendar_env.setenv("GOOGLE_CLIENT_SECRET", "google-secret")
    cfg = WorkerSettings.from_env()
    assert cfg.calendar_client_id == "google-id"
    assert cfg.calendar_client_secret == "google-secret"


def test_calendar_credentials_override_google(calendar_env):
    calendar_env.setenv("GOOGLE_CLIENT_ID", "google-id")
    calendar_env.setenv("GOOGLE_CLIENT_SECRET", "google-secret")
    calendar_env.setenv("CALENDAR_CLIENT_ID", "calendar-id")
    calendar_env.setenv("CALENDAR_CLIENT_SECRET", "calendar-secret")
    cfg = WorkerSettings.from_env()
    assert cfg.calendar_client_id == "calendar-id"
    assert cfg.calendar_client_secret == "calendar-secret"
    assert "calendar-secret" not in repr(cfg)


@pytest.mark.parametrize(
    "name", ("CALENDAR_SYNC_DAYS_BACK", "CALENDAR_SYNC_DAYS_AHEAD")
)
def test_negative_calendar_day_counts_are_rejected(calendar_env, name):
    calendar_env.setenv(name, "-1")
    with pytest.raises(ConfigurationError):
        WorkerSettings.from_env()


def test_calendar_secret_is_filtered_from_worker_logs(monkeypatch):
    from app.worker import main as worker_main

    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    monkeypatch.setenv("CALENDAR_CLIENT_SECRET", "calendar-secret")
    captured = {}
    monkeypatch.setattr(
        worker_main,
        "configure_logging",
        lambda *_, **kwargs: captured.update(kwargs),
    )
    monkeypatch.setattr(worker_main, "run", lambda *_: None)
    assert worker_main.main() == 0
    assert "calendar-secret" in captured["secrets"]
