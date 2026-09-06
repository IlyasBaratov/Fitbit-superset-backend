from dataclasses import replace
from unittest.mock import Mock
import pytz
from app.core.config import WorkerSettings
from app.providers.fitbit.provider import FitbitProvider
from app.providers.fitbit.tcx import map_tcx


def provider(monkeypatch):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    return FitbitProvider(replace(WorkerSettings.from_env(), health_api_provider="fitbit"), Mock(), pytz.utc, "Watch")


def test_fitbit_intraday_and_empty_battery(monkeypatch):
    api = provider(monkeypatch)
    api.client.intraday.side_effect = lambda kind, *_: {"activities-" + kind + "-intraday": {"dataset": [{"time": "10:00:00", "value": 60}]}}
    result = api.fetch_intraday("2026-08-20")
    assert [p.measurement for p in result] == ["HeartRate_Intraday", "Steps_Intraday"]
    assert result[0].fields == {"value": 60}
    api.client.devices.return_value = []
    assert api.fetch_battery() == []


def test_fitbit_vitals_mapping(monkeypatch):
    api = provider(monkeypatch)
    api.client.hrv.return_value = {"hrv": [{"dateTime": "2026-08-20", "value": {"dailyRmssd": 40, "deepRmssd": 50}}]}
    api.client.breathing.return_value = {"br": [{"dateTime": "2026-08-20", "value": {"breathingRate": 16}}]}
    api.client.skin_temperature.return_value = {"tempSkin": [{"dateTime": "2026-08-20", "value": {"nightlyRelative": 0.5}}]}
    api.client.spo2_intraday.return_value = [{"minutes": [{"minute": "2026-08-20T10:00:00", "value": 98}]}]
    api.client.weight.return_value = {"weight": [{"date": "2026-08-20", "time": "10:00:00", "weight": 80, "bmi": 23.63}]}
    points = {p.measurement: p for p in api.fetch_daily_group("30d", "2026-08-20", "2026-08-20")}
    assert set(points) == {"HRV", "BreathingRate", "Skin Temperature Variation", "SPO2_Intraday", "weight", "bmi"}
    assert points["HRV"].fields == {"dailyRmssd": 40.0, "deepRmssd": 50.0}


def test_tcx_utc_coordinates_and_speed():
    xml = '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"><Track><Trackpoint><Time>2026-08-20T10:00:00Z</Time><Position><LatitudeDegrees>1</LatitudeDegrees><LongitudeDegrees>2</LongitudeDegrees></Position><DistanceMeters>0</DistanceMeters></Trackpoint><Trackpoint><Time>2026-08-20T10:00:10Z</Time><Position><LatitudeDegrees>1</LatitudeDegrees><LongitudeDegrees>2</LongitudeDegrees></Position><DistanceMeters>20</DistanceMeters></Trackpoint></Track></TrainingCenterDatabase>'
    points = map_tcx(xml, "run-1", "Run", pytz.timezone("America/Los_Angeles"))
    assert points[0].timestamp == "2026-08-20T10:00:00+00:00"
    assert points[1].fields["speed_kph"] == 7.2
    assert points[1].fields["ActivityId"] == "run-1"
