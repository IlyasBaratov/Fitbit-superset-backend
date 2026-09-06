from app.domain.models import HealthPoint
from app.domain.normalization import build_common_tags
from app.storage.influx.schema import prepare_point


def test_point_normalization_retains_unknown_fields_and_detaches_record():
    source = {"measurement": "HRV", "time": "2026-08-20T00:00:00", "fields": {"dailyRmssd": "42", "additionalMetric": 5, "missing": None}}
    point = HealthPoint.from_record(source)
    source["fields"]["dailyRmssd"] = "100"
    result = prepare_point(point.as_record(), build_common_tags("u", "google", "Watch", "d"), "UTC")
    assert result["fields"] == {"dailyRmssd": 42.0, "additionalMetric": 5}
    assert result["time"] == "2026-08-20T00:00:00+00:00"
