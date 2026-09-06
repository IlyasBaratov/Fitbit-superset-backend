from dataclasses import replace
from unittest.mock import Mock
import pytz
from app.core.config import WorkerSettings
from app.providers.google_health.provider import GoogleHealthProvider


def provider(monkeypatch):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    client = Mock()
    client.get_google_datapoints_for_date_range.return_value = []
    client.request_google_data_points_list.return_value = {}
    return GoogleHealthProvider(replace(WorkerSettings.from_env(), health_api_provider="google"), client, pytz.utc, "Watch"), client


def test_vitals_body_and_google_specific_fields(monkeypatch):
    api, client = provider(monkeypatch)
    ts = "2026-08-20T12:00:00Z"
    samples = {
      "daily-heart-rate-variability": [({"dailyHeartRateVariability": {"averageHeartRateVariabilityMilliseconds": 42, "entropy": 2, "nonRemHeartRateBeatsPerMinute": 55}}, ts)],
      "daily-respiratory-rate": [({"dailyRespiratoryRate": {"breathsPerMinute": 16}}, ts)],
      "daily-sleep-temperature-derivations": [({"dailySleepTemperatureDerivations": {"nightlyTemperatureCelsius": 35, "baselineTemperatureCelsius": 34, "relativeNightlyStddev30dCelsius": 0.2}}, ts)],
      "oxygen-saturation": [({"oxygenSaturation": {"percentage": 98}}, ts)],
      "weight": [({"weight": {"sampleTime": {"physicalTime": ts}, "weightGrams": 80000}}, ts)]}
    client.get_google_datapoints_for_date_range.side_effect = lambda kind, *_: samples.get(kind, [])
    client.request_google_data_points_list.return_value = {"dataPoints": [{"height": {"sampleTime": {"physicalTime": "2026-08-01T00:00:00Z"}, "heightMillimeters": 1840}}]}
    points = {point.measurement: point for point in api.fetch_daily_group("30d", "2026-08-20", "2026-08-20")}
    assert set(points) == {"HRV", "BreathingRate", "Skin Temperature Variation", "SPO2_Intraday", "height", "weight", "bmi"}
    assert points["HRV"].fields["entropy"] == 2
    assert points["weight"].fields["value"] == 80
    assert points["bmi"].fields["value"] == 23.63
    assert points["Skin Temperature Variation"].fields["RelativeValue"] == 1


def test_daily_rollup_measurements(monkeypatch):
    api, client = provider(monkeypatch)
    values = {"active-zone-minutes": {"activeZoneMinutes": {"sumInFatBurnHeartZone": 10, "sumInCardioHeartZone": 5, "totalActiveZoneMinutes": 20}}, "steps": {"steps": {"countSum": 1000}}, "total-calories": {"totalCalories": {"kcalSum": 2000}}, "distance": {"distance": {"millimetersSum": 1500000}}, "sedentary-period": {"sedentaryPeriod": {"durationSum": "3600s"}}}
    client.request_google_data_points_daily_rollup.side_effect = lambda kind, _: {"rollupDataPoints": [values[kind]]}
    points = {p.measurement: p for p in api.fetch_daily_group("365d", "2026-08-20", "2026-08-20")}
    assert points["distance"].fields["value"] == 1.5
    assert points["Total Steps"].fields["value"] == 1000.0
    assert points["Activity Minutes"].fields["minutesSedentary"] == 60
    assert points["HR zones"].fields["TotalActiveZoneMinutes"] == 20
