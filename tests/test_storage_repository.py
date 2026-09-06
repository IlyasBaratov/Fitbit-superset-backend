from dataclasses import replace
from unittest.mock import Mock
import pytest
from app.core.config import WorkerSettings
from app.core.exceptions import StorageError
from app.domain.models import HealthPoint
from app.domain.measurements import FIELD_TYPES
from app.storage.influx.repository import InfluxHealthRepository


def config(monkeypatch, version="1", dry=False):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    return replace(WorkerSettings.from_env(), influxdb_version=version, dry_run_mode=dry)


def test_schema_isolation_and_write(monkeypatch):
    client = Mock()
    client.query.return_value.get_points.return_value = [{"fieldKey": "value", "fieldType": "integer"}]
    repo = InfluxHealthRepository(config(monkeypatch), dict(UserId="u", Provider="google", Device="D", DeviceId="d"), "UTC", client)
    assert repo.field_types["RestingHR"]["value"] is int
    assert FIELD_TYPES["RestingHR"]["value"] is float
    point = HealthPoint("RestingHR", "2026-08-01", {"value": 60.5})
    assert repo.write([point])
    assert client.write_points.call_args.args[0][0]["fields"] == {"value": 60}
    client.write_points.return_value = False
    with pytest.raises(StorageError):
        repo.write([point])


@pytest.mark.parametrize("version", ["2", "3"])
def test_alternate_influx_versions(monkeypatch, version):
    client = Mock()
    repo = InfluxHealthRepository(config(monkeypatch, version), dict(UserId="u", Provider="fitbit", Device="D", DeviceId="d"), "UTC", client)
    assert repo.write([HealthPoint("weight", "2026-08-01", {"value": 80})])
    target = client.write_api.return_value if version == "2" else client
    assert target.write.call_count == 1
    repo.close()
    client.close.assert_called_once()


def test_dry_run_does_not_initialize_or_write(monkeypatch):
    client = Mock()
    repo = InfluxHealthRepository(config(monkeypatch, dry=True), {}, "UTC", client)
    assert repo.write([]) is False
    assert not client.mock_calls
