import importlib
import json
from pathlib import Path
from unittest.mock import patch
from health_schema import parse_google_exercise, prepare_point, build_common_tags


def test_worker_import_does_not_start_runtime():
    with patch("requests.get", side_effect=AssertionError("network")), patch("requests.post", side_effect=AssertionError("network")), patch("builtins.input", side_effect=AssertionError("stdin")), patch("logging.basicConfig", side_effect=AssertionError("logging")):
        import main
        importlib.reload(main)


def test_provider_fixture_contracts():
    fixture = json.loads((Path(__file__).parent / "fixtures/provider_contracts.json").read_text())
    ts, fields, name = parse_google_exercise(fixture["google_exercise"])
    assert (fields["duration"], fields["distance"], name) == (60, 1.0, "Run")
    device = fixture["fitbit_device"]
    point = prepare_point({"measurement": "DeviceBatteryLevel", "time": device["dateTime"], "fields": {"value": device["batteryLevel"]}}, build_common_tags("u", "fitbit", "Watch", "d"), "UTC")
    assert point["fields"] == {"value": 75.0}
