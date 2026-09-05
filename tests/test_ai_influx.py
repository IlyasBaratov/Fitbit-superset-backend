from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
import pytest
from app.config import Settings
from app.services.influx_service import InfluxService, DataUnavailable

@pytest.fixture
def service():
    client = Mock()
    client.query.return_value.get_points.return_value = iter([])
    return InfluxService(Settings(api_token="x"*40, gemini_key="k", model="m", user_id="a'b\\c"), client)

def test_query_scopes_and_escapes_identity(service):
    end = datetime.now(timezone.utc)
    service.query("Total Steps", end-timedelta(days=7), end)
    sql = service.client.query.call_args.args[0]
    assert '"UserId" = \'a\\\'b\\\\c\'' in sql
    assert '"Provider" = \'google\'' in sql
    assert '"DeviceId" = \'fitbit_air_001\'' in sql
    assert "LIMIT 20001" in sql and "time >=" in sql and "time <" in sql

def test_intraday_aggregates_before_transfer(service):
    end = datetime.now(timezone.utc)
    service.query("HeartRate_Intraday", end-timedelta(days=30), end)
    sql = service.client.query.call_args.args[0]
    assert 'COUNT("value")' in sql and 'GROUP BY time(1h)' in sql

@pytest.mark.parametrize("measurement,days", [("anything", 7), ("GPS", 7), ("Total Steps", 191), ("Total Steps", 0)])
def test_rejects_unbounded_or_unapproved_queries(service, measurement, days):
    end = datetime.now(timezone.utc)
    with pytest.raises(ValueError):
        service.query(measurement, end-timedelta(days=days), end)
    service.client.query.assert_not_called()

def test_database_errors_are_redacted(service):
    service.client.query.side_effect = RuntimeError("secret")
    end = datetime.now(timezone.utc)
    with pytest.raises(DataUnavailable, match="retrieved"):
        service.query("HRV", end-timedelta(days=1), end)

def test_row_limit_fails_without_silent_truncation(service):
    service.client.query.return_value.get_points.return_value = iter([{}] * 20001)
    end = datetime.now(timezone.utc)
    with pytest.raises(DataUnavailable, match="safe query limit"):
        service.query("HRV", end-timedelta(days=1), end)
