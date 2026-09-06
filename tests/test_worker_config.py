from dataclasses import FrozenInstanceError
import pytest
from app.core.config import WorkerSettings


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
