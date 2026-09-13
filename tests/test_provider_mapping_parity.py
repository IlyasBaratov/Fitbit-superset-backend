"""Compare synthetic fixtures with outputs captured from pre-refactor f8999cc."""
from dataclasses import replace
from pathlib import Path
import json
from unittest.mock import Mock
import pytest
import pytz
from app.core.config import WorkerSettings
from app.domain.normalization import build_common_tags
from app.storage.influx.schema import prepare_points
from app.providers.fitbit.provider import FitbitProvider
from app.providers.google_health.provider import GoogleHealthProvider


@pytest.mark.parametrize("kind", ["fitbit", "google"])
def test_original_worker_measurement_parity(monkeypatch, kind):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    fixture = json.loads((Path(__file__).parent / "fixtures" / (kind + "_mapping_contract.json")).read_text())
    data, day = fixture["payloads"], fixture["date"]
    cfg = replace(WorkerSettings.from_env(), health_api_provider=kind, user_id="u", device_id="d", devicename="Watch")
    client = Mock()
    if kind == "google":
        client.get_google_datapoints_for_date.side_effect = lambda key, *_: data["range"].get(key, [])
        client.get_google_datapoints_for_date_range.side_effect = lambda key, *_: data["range"].get(key, [])
        client.get_google_session_datapoints_for_date_range.side_effect = lambda key, *_: data["range"].get(key, [])
        client.request_google_data_points_list.side_effect = lambda key, **_: data["list"].get(key, {})
        client.request_google_data_points_daily_rollup.side_effect = lambda key, *_: data["rollup"].get(key, {})
        provider = GoogleHealthProvider(cfg, client, pytz.utc)
    else:
        for key, value in data.items():
            if ":" not in key:
                getattr(client, key).return_value = value
        client.intraday.side_effect = lambda key, *_: data["intraday:" + key]
        client.activity_series.side_effect = lambda key, *_: data["activity_series:" + key]
        client.tcx.return_value = Mock(text=data["tcx_xml"])
        provider = FitbitProvider(cfg, client, pytz.utc)
    points = provider.fetch_intraday(day)
    for group in ("30d", "100d", "365d", "none"):
        points.extend(provider.fetch_daily_group(group, day, day))
    points.extend(provider.fetch_workouts(day))
    points.extend(provider.fetch_battery())
    actual = prepare_points([p.as_record() for p in points], build_common_tags("u", kind, "Watch", "d"), "UTC")
    canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
    assert canonical(actual) == canonical(fixture["expected"])


def test_empty_fitbit_activity_results(monkeypatch):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    client = Mock()
    client.activity_series.return_value = {}
    client.heart_summary.return_value = {}
    client.active_zone_minutes.return_value = {}
    api = FitbitProvider(WorkerSettings.from_env(), client, pytz.utc)
    assert api.fetch_daily_group("365d", "2026-08-20", "2026-08-20") == []
