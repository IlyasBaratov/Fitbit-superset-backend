"""Google sleep and overnight raw HR survive the actual storage write path."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytz

from app.ingestion.metadata import DeviceMetadataState
from app.ingestion.service import IngestionService
from app.providers.google_health.provider import GoogleHealthProvider
from app.storage.influx.repository import InfluxHealthRepository


def test_google_overnight_sleep_persists_short_intervals_and_raw_hr(tmp_path):
    sleep_start = "2026-10-05T05:00:00Z"  # Oct 4, 22:00 local
    sleep_end = "2026-10-05T14:00:00Z"  # Oct 5, 07:00 local
    awakening_start = "2026-10-05T05:30:00Z"
    awakening_end = "2026-10-05T05:31:00Z"
    google = Mock()
    google.get_google_datapoints_for_date_range.return_value = [({
        "name": "users/me/dataTypes/sleep/dataPoints/overnight",
        "sleep": {
            "interval": {"startTime": sleep_start, "endTime": sleep_end},
            "metadata": {"mainSleep": True, "processed": True},
            "summary": {"minutesAsleep": 500, "minutesInSleepPeriod": 540},
            "shortAwakenings": [{"startTime": awakening_start,
                                  "endTime": awakening_end}],
            "stages": [{"startTime": sleep_start, "endTime": sleep_end,
                        "type": "LIGHT"}],
        },
    }, sleep_start)]
    samples_by_local_date = {
        "2026-10-04": "2026-10-05T05:10:03Z",
        "2026-10-05": "2026-10-05T13:50:07Z",
    }
    google.get_google_datapoints_for_date.side_effect = (
        lambda kind, day: [({
            "heartRate": {"sampleTime": {"physicalTime": samples_by_local_date[day]},
                          "beatsPerMinute": 61}
        }, samples_by_local_date[day])]
        if kind == "heart-rate" else []
    )
    zone = pytz.timezone("America/Los_Angeles")
    provider = GoogleHealthProvider(SimpleNamespace(devicename="Watch"), google, zone)
    influx = Mock()
    influx.query.return_value.get_points.return_value = iter(())
    influx.write_points.return_value = True
    settings = SimpleNamespace(dry_run_mode=False, influxdb_version="1")
    tags = {"UserId": "owner", "Provider": "google", "Device": "Watch",
            "DeviceId": "device"}
    repository = InfluxHealthRepository(settings, tags, zone.zone, influx)
    service = IngestionService(provider, repository, DeviceMetadataState(tmp_path / "state", tags))

    assert service.sync_daily_group("100d", "2026-10-04", "2026-10-05") is True
    assert service.sync_intraday("2026-10-04") is True
    assert service.sync_intraday("2026-10-05") is True
    persisted = [point for call in influx.write_points.call_args_list
                 for point in call.args[0]]
    summaries = [point for point in persisted if point["measurement"] == "Sleep Summary"]
    awakenings = [point for point in persisted
                  if point["measurement"] == "Sleep Short Awakenings"]
    heart_rate = [point for point in persisted
                  if point["measurement"] == "HeartRate_Intraday"]
    assert summaries[0]["fields"]["shortAwakeningSeconds"] == 60
    assert awakenings[0]["fields"]["SleepSessionId"] == "overnight"
    assert awakenings[0]["time"] == "2026-10-05T05:30:00+00:00"
    assert awakenings[0]["fields"]["endTime"] == "2026-10-05T05:31:00+00:00"
    assert [point["time"] for point in heart_rate] == [
        "2026-10-05T05:10:03+00:00", "2026-10-05T13:50:07+00:00",
    ]
    assert all(point["fields"] == {"value": 61} for point in heart_rate)
    assert all(point["tags"]["UserId"] == "owner" for point in persisted)
