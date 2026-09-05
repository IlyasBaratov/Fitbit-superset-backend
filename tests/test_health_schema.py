from datetime import datetime, timezone

import pytest

from health_schema import (
    build_common_tags,
    calculate_bmi,
    distance_meters_to_km,
    height_values,
    local_date_boundary_utc,
    metadata_signature,
    normalize_duration_seconds,
    parse_google_exercise,
    parse_google_height,
    point_identity,
    prepare_point,
    sanitize_fields,
    sleep_efficiency,
    sleep_stage,
    utc_timestamp,
    weight_values,
)


COMMON_TAGS = build_common_tags("user_001", "google", "Charge5", "device_001")


def test_common_tag_generation():
    assert COMMON_TAGS == {
        "UserId": "user_001",
        "Provider": "google",
        "Device": "Charge5",
        "DeviceId": "device_001",
    }


def test_common_tags_reject_missing_identifier():
    with pytest.raises(ValueError):
        build_common_tags("", "google", "Charge5", "device_001")


def test_null_field_removal_preserves_false_and_zero():
    assert sanitize_fields({"missing": None, "zero": 0, "false": False}) == {"zero": 0, "false": False}


def test_weight_unit_conversion_uses_kilograms_as_value():
    values = weight_values(80_000)
    assert values["value"] == 80
    assert values["weightKg"] == 80
    assert values["weightLbs"] == pytest.approx(176.369809744)


def test_height_conversion():
    assert height_values(1840) == {
        "value": 184.0,
        "heightCm": 184.0,
        "heightMeters": 1.84,
        "heightMillimeters": 1840,
    }


def test_bmi_calculation_and_invalid_height():
    assert calculate_bmi(80, 1.84) == 23.63
    assert calculate_bmi(80, 0) is None


def test_exercise_distance_and_duration_normalization():
    point = {
        "name": "users/123/dataTypes/exercise/dataPoints/activity-42",
        "exercise": {
            "displayName": "Run",
            "activeDuration": "3600s",
            "interval": {"startTime": "2026-08-20T10:00:00Z", "endTime": "2026-08-20T11:00:00Z"},
            "metricsSummary": {"distanceMeters": 5000, "steps": 6000, "caloriesKcal": 450},
        },
    }
    timestamp, fields, name = parse_google_exercise(point)
    assert timestamp == "2026-08-20T10:00:00Z"
    assert name == "Run"
    assert fields["ActivityId"] == "activity-42"
    assert fields["duration"] == 3600
    assert fields["distance"] == 5.0


def test_duration_formats():
    assert normalize_duration_seconds("1500ms") == 1
    assert normalize_duration_seconds({"seconds": "12", "nanos": 500_000_000}) == 12
    assert distance_meters_to_km(1250) == 1.25


def test_sleep_stage_mapping():
    assert sleep_stage("DEEP") == (0, "deep")
    assert sleep_stage("unsupported") == (4, "unknown")


def test_sleep_efficiency_calculation():
    assert sleep_efficiency(420, 480) == 88
    assert sleep_efficiency(420, 0) is None
    assert sleep_efficiency(420, 480, 91.2) == 91


def test_utc_timestamp_conversion():
    assert utc_timestamp("2026-08-20T10:00:00-07:00") == "2026-08-20T17:00:00+00:00"
    assert utc_timestamp(datetime(2026, 8, 20, 17, tzinfo=timezone.utc)) == "2026-08-20T17:00:00+00:00"


def test_daily_local_boundary_handles_dst():
    assert local_date_boundary_utc("2026-01-15", "America/Los_Angeles") == "2026-01-15T08:00:00+00:00"
    assert local_date_boundary_utc("2026-07-15", "America/Los_Angeles") == "2026-07-15T07:00:00+00:00"


def test_duplicate_point_identity_is_stable():
    point = {"measurement": "height", "time": "2026-08-20T10:00:00Z", "tags": COMMON_TAGS, "fields": {"value": 184.0}}
    reordered = {**point, "tags": dict(reversed(list(COMMON_TAGS.items())))}
    assert point_identity(point) == point_identity(reordered)


def test_missing_metric_fields_skip_point():
    assert prepare_point({"measurement": "HRV", "time": "2026-08-20T00:00:00Z", "fields": {}}, COMMON_TAGS, "UTC") is None


def test_influx_field_type_consistency_for_legacy_fields():
    resting = prepare_point({"measurement": "RestingHR", "time": "2026-08-20T00:00:00Z", "fields": {"value": 57}}, COMMON_TAGS, "UTC")
    steps = prepare_point({"measurement": "Total Steps", "time": "2026-08-20T00:00:00Z", "fields": {"value": 12000}}, COMMON_TAGS, "UTC")
    assert isinstance(resting["fields"]["value"], float)
    assert isinstance(steps["fields"]["value"], float)


def test_height_measurement_persistence_payload():
    timestamp, fields = parse_google_height({"height": {"sampleTime": {"physicalTime": "2026-08-20T01:02:03Z"}, "heightMillimeters": 1840}})
    point = prepare_point({"measurement": "height", "time": timestamp, "fields": fields}, COMMON_TAGS, "UTC")
    assert point["fields"]["heightMeters"] == 1.84
    assert point["time"] == "2026-08-20T01:02:03+00:00"


def test_device_metadata_signature_changes_only_with_content():
    first = metadata_signature({"deviceName": "Charge5", "timezone": "UTC"}, COMMON_TAGS)
    same = metadata_signature({"timezone": "UTC", "deviceName": "Charge5"}, COMMON_TAGS)
    changed = metadata_signature({"deviceName": "Charge6", "timezone": "UTC"}, COMMON_TAGS)
    assert first == same
    assert first != changed
