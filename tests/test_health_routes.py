from datetime import datetime, timezone
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.core.exceptions import DataUnavailable, QueryLimitExceeded
from app.api.main import create_app
from app.storage.influx.queries import InfluxService

@pytest.fixture
def setup():
    cfg = Settings(api_token="t" * 40, gemini_key="test", model="test")
    db, gemini = Mock(), Mock()
    db.query.return_value = []
    db.latest_device_observation.return_value = None
    clock = lambda: datetime(2026, 3, 9, 12, tzinfo=timezone.utc)
    return cfg, db, gemini, clock

@pytest.mark.parametrize("endpoint", ["heart-rate", "sleep", "activity", "workouts", "spo2", "body", "ecg", "irn", "calendar"])
def test_health_route_auth_empty_results_and_identity(setup, endpoint):
    cfg, db, gemini, clock = setup
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        url = "/api/health/" + endpoint
        assert client.get(url).status_code == 401
        headers = {"Authorization": "Bearer " + cfg.api_token}
        result = client.get(url, headers=headers)
        assert result.status_code == 200
        assert all(series["rows"] == [] for series in result.json()["series"])
        assert client.get(url + "?UserId=other", headers=headers).status_code == 422
        assert client.get(url + "?period=91d", headers=headers).status_code == 422
        assert client.get(url + "?period=0d", headers=headers).status_code == 422
    gemini.generate.assert_not_called()


def test_hourly_fields_dst_interval_and_safe_errors(setup):
    cfg, db, gemini, clock = setup
    row = {"time": "2026-03-08T08:00:00Z", "sum": 120.0, "count": 2, "min": 50.0, "max": 70.0}
    db.query.side_effect = lambda measurement, *_: [row] if measurement == "HeartRate_Intraday" else []
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        headers = {"Authorization": "Bearer " + cfg.api_token}
        response = client.get("/api/health/heart-rate?period=2d", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["start"] == "2026-03-08T08:00:00Z"
        assert data["series"][0]["resolution"] == "hourly"
        assert data["series"][0]["rows"][0]["fields"]["count"] == 2
        assert db.query.call_args.args[1] == datetime(2026, 3, 8, 8, tzinfo=timezone.utc)
        for error, status in ((DataUnavailable("secret"), 503), (QueryLimitExceeded("secret"), 422)):
            db.query.side_effect = error
            result = client.get("/api/health/body", headers=headers)
            assert result.status_code == status
            assert "secret" not in result.text


def test_devices_latest_observations_and_scoped_sql(setup):
    cfg, db, gemini, clock = setup
    db.latest_device_observation.side_effect = lambda measurement: {"time": "2026-08-20T10:00:00Z", "deviceName": "Watch"} if measurement == "Device Metadata" else None
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        headers = {"Authorization": "Bearer " + cfg.api_token}
        assert client.get("/api/devices").status_code == 401
        result = client.get("/api/devices", headers=headers)
        assert result.status_code == 200
        assert len(result.json()["observations"]) == 1
        assert client.get("/api/devices?device_id=other", headers=headers).status_code == 422
    influx = Mock()
    influx.query.return_value.get_points.return_value = []
    InfluxService(cfg, influx).latest_device_observation("Device Metadata")
    sql = influx.query.call_args.args[0]
    for tag in ("UserId", "Provider", "DeviceId"):
        assert '"' + tag + '" =' in sql
    assert "ORDER BY time DESC LIMIT 1" in sql


def test_oversized_result_is_rejected_without_partial_data(setup, monkeypatch):
    cfg, db, gemini, clock = setup
    monkeypatch.setattr("app.api.health_service.MAX_ROWS", 1)
    db.query.return_value = [{"time": "2026-03-08T08:00:00Z", "value": 1}] * 2
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        result = client.get("/api/health/body", headers={"Authorization": "Bearer " + cfg.api_token})
        assert result.status_code == 422
        assert "series" not in result.json()
