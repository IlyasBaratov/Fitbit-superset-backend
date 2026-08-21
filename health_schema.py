"""Schema normalization helpers for Fitbit/Google Health InfluxDB points."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any

import pytz


COMMON_TAG_KEYS = ("UserId", "Provider", "Device", "DeviceId")
SLEEP_STAGE_MAPPING = {
    "DEEP": (0, "deep"),
    "LIGHT": (1, "light"),
    "REM": (2, "rem"),
    "AWAKE": (3, "awake"),
    "WAKE": (3, "awake"),
    "ASLEEP": (1, "light"),
    "RESTLESS": (2, "rem"),
    "UNKNOWN": (4, "unknown"),
}

# RestingHR and Total Steps are floats because the existing production InfluxDB
# measurements already use float fields. InfluxDB 1.x cannot change a field's
# type in place without rewriting historical data.
FIELD_TYPES: dict[str, dict[str, type]] = {
    "HeartRate_Intraday": {"value": int},
    "RestingHR": {"value": float},
    "HRV": {
        "dailyRmssd": float,
        "deepRmssd": float,
        "nonRemHeartRateBpm": float,
        "entropy": float,
    },
    "HR zones": {
        "Normal": int,
        "Fat Burn": int,
        "Cardio": int,
        "Peak": int,
        "TotalActiveZoneMinutes": int,
    },
    "Steps_Intraday": {"value": int},
    "Total Steps": {"value": float},
    "Activity Minutes": {
        "minutesSedentary": int,
        "minutesLightlyActive": int,
        "minutesFairlyActive": int,
        "minutesVeryActive": int,
        "minutesActiveZone": int,
    },
    "Activity Records": {
        "ActivityId": str,
        "ActiveDuration": int,
        "duration": int,
        "AverageHeartRate": int,
        "calories": int,
        "distance": float,
        "steps": int,
        "startTime": str,
        "endTime": str,
    },
    "calories": {"value": float},
    "distance": {"value": float},
    "GPS": {
        "ActivityId": str,
        "lat": float,
        "lon": float,
        "altitude": float,
        "distance": float,
        "heart_rate": int,
        "speed_kph": float,
    },
    "Sleep Summary": {
        "SleepSessionId": str,
        "efficiency": int,
        "minutesAfterWakeup": int,
        "minutesAsleep": int,
        "minutesAwake": int,
        "minutesDeep": int,
        "minutesInBed": int,
        "minutesLight": int,
        "minutesREM": int,
        "minutesToFallAsleep": int,
        "startTime": str,
        "endTime": str,
    },
    "Sleep Levels": {
        "SleepSessionId": str,
        "level": int,
        "stageName": str,
        "duration_seconds": int,
    },
    "SPO2": {"avg": float, "min": float, "max": float},
    "SPO2_Intraday": {"value": float},
    "BreathingRate": {"value": float},
    "Skin Temperature Variation": {
        "RelativeValue": float,
        "nightlyTemperatureCelsius": float,
        "baselineTemperatureCelsius": float,
        "stddev30d": float,
    },
    "weight": {"value": float, "weightKg": float, "weightLbs": float},
    "height": {
        "value": float,
        "heightCm": float,
        "heightMeters": float,
        "heightMillimeters": int,
    },
    "bmi": {
        "value": float,
        "weightKg": float,
        "heightMeters": float,
        "isCalculated": bool,
    },
    "DeviceBatteryLevel": {"value": float},
    "Device Metadata": {
        "deviceName": str,
        "deviceModel": str,
        "timezone": str,
        "lastSyncTime": str,
        "batteryPercent": float,
        "firmwareVersion": str,
        "connectionStatus": str,
    },
}


def build_common_tags(user_id: str, provider: str, device_name: str, device_id: str) -> dict[str, str]:
    values = {
        "UserId": str(user_id).strip(),
        "Provider": str(provider).strip().lower(),
        "Device": str(device_name).strip(),
        "DeviceId": str(device_id).strip(),
    }
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise ValueError(f"Missing required common tags: {', '.join(missing)}")
    return values


def sanitize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in fields.items() if value is not None}


def coerce_fields(measurement: str, fields: dict[str, Any]) -> dict[str, Any]:
    schema = FIELD_TYPES.get(measurement, {})
    coerced: dict[str, Any] = {}
    for key, value in sanitize_fields(fields).items():
        expected_type = schema.get(key)
        if expected_type is None:
            coerced[key] = value
            continue
        try:
            if expected_type is bool:
                if isinstance(value, str):
                    coerced[key] = value.strip().lower() in {"true", "1", "yes"}
                else:
                    coerced[key] = bool(value)
            elif expected_type is str:
                text = str(value).strip()
                if text:
                    coerced[key] = text
            else:
                coerced[key] = expected_type(value)
        except (TypeError, ValueError):
            continue
    return coerced


def utc_timestamp(value: str | datetime, local_timezone: str = "UTC") -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            raise ValueError("Timestamp cannot be empty")
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = pytz.timezone(local_timezone).localize(parsed)
    return parsed.astimezone(timezone.utc).isoformat()


def local_date_boundary_utc(value: str | date, local_timezone: str) -> str:
    parsed_date = date.fromisoformat(value) if isinstance(value, str) else value
    local_midnight = pytz.timezone(local_timezone).localize(datetime(parsed_date.year, parsed_date.month, parsed_date.day))
    return local_midnight.astimezone(timezone.utc).isoformat()


def prepare_point(point: dict[str, Any], common_tags: dict[str, str], local_timezone: str) -> dict[str, Any] | None:
    measurement = str(point.get("measurement") or "").strip()
    if not measurement or "time" not in point:
        return None
    try:
        timestamp = utc_timestamp(point["time"], local_timezone)
    except (TypeError, ValueError, KeyError):
        return None

    tags = dict(point.get("tags") or {})
    tags.update(common_tags)
    if "isMainSleep" in tags:
        tags["isMainSleep"] = str(tags["isMainSleep"]).strip().lower()
    tags = {key: str(value).strip() for key, value in tags.items() if value is not None and str(value).strip()}
    if any(not tags.get(key) for key in COMMON_TAG_KEYS):
        return None

    fields = coerce_fields(measurement, dict(point.get("fields") or {}))
    if not fields:
        return None
    return {"measurement": measurement, "time": timestamp, "tags": tags, "fields": fields}


def prepare_points(points: list[dict[str, Any]], common_tags: dict[str, str], local_timezone: str) -> list[dict[str, Any]]:
    prepared = []
    for point in points:
        normalized = prepare_point(point, common_tags, local_timezone)
        if normalized is not None:
            prepared.append(normalized)
    return prepared


def point_identity(point: dict[str, Any]) -> tuple[str, tuple[tuple[str, str], ...], str]:
    return (
        str(point["measurement"]),
        tuple(sorted((str(key), str(value)) for key, value in point.get("tags", {}).items())),
        str(point["time"]),
    )


def weight_values(weight_grams: Any) -> dict[str, float]:
    kilograms = float(weight_grams) / 1000.0
    pounds = kilograms * 2.2046226218
    return {"value": kilograms, "weightKg": kilograms, "weightLbs": pounds}


def height_values(height_millimeters: Any) -> dict[str, float | int]:
    millimeters = int(float(height_millimeters))
    return {
        "value": millimeters / 10.0,
        "heightCm": millimeters / 10.0,
        "heightMeters": millimeters / 1000.0,
        "heightMillimeters": millimeters,
    }


def calculate_bmi(weight_kg: Any, height_meters: Any) -> float | None:
    if weight_kg is None or height_meters is None:
        return None
    weight = float(weight_kg)
    height = float(height_meters)
    if weight <= 0 or height <= 0:
        return None
    return round(weight / (height**2), 2)


def distance_meters_to_km(value: Any) -> float:
    return float(value) / 1000.0


def normalize_duration_seconds(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, dict):
        seconds = value.get("seconds")
        nanos = value.get("nanos", 0)
        if seconds is None:
            return None
        return int(float(seconds) + float(nanos) / 1_000_000_000)
    if isinstance(value, str):
        text = value.strip().lower()
        if text.endswith("ms"):
            return int(float(text[:-2]) / 1000.0)
        if text.endswith("s"):
            return int(float(text[:-1]))
        return int(float(text))
    return int(float(value))


def sleep_efficiency(minutes_asleep: Any, minutes_in_bed: Any, provider_value: Any = None) -> int | None:
    if provider_value is not None:
        return int(round(float(provider_value)))
    if minutes_asleep is None or minutes_in_bed is None:
        return None
    in_bed = int(minutes_in_bed)
    if in_bed <= 0:
        return None
    return round(int(minutes_asleep) / in_bed * 100)


def sleep_stage(value: Any) -> tuple[int, str]:
    return SLEEP_STAGE_MAPPING.get(str(value or "UNKNOWN").strip().upper(), (4, "unknown"))


def stable_resource_id(resource_name: Any) -> str | None:
    text = str(resource_name or "").strip()
    return text.rsplit("/", 1)[-1] if text else None


def parse_google_exercise(data_point: dict[str, Any]) -> tuple[str | None, dict[str, Any], str]:
    exercise = data_point.get("exercise") or {}
    metrics = exercise.get("metricsSummary") or {}
    interval = exercise.get("interval") or {}
    start_time = interval.get("startTime")
    end_time = interval.get("endTime")
    activity_name = exercise.get("displayName") or exercise.get("exerciseType") or "Unknown-Activity"
    distance_meters = _first_numeric(metrics.get("distanceMeters"))
    fields = sanitize_fields(
        {
            "ActivityId": stable_resource_id(data_point.get("name")),
            "ActiveDuration": normalize_duration_seconds(exercise.get("activeDuration")),
            "duration": normalize_duration_seconds(exercise.get("activeDuration")),
            "AverageHeartRate": _first_numeric(metrics.get("averageHeartRateBeatsPerMinute")),
            "calories": _first_numeric(metrics.get("caloriesKcal")),
            "distance": distance_meters_to_km(distance_meters) if distance_meters is not None else None,
            "steps": _first_numeric(metrics.get("steps")),
            "startTime": start_time,
            "endTime": end_time,
        }
    )
    return start_time, fields, str(activity_name)


def parse_google_height(data_point: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    payload = data_point.get("height") or {}
    timestamp = (payload.get("sampleTime") or {}).get("physicalTime")
    millimeters = _first_numeric(payload.get("heightMillimeters"))
    return timestamp, height_values(millimeters) if millimeters is not None else {}


def parse_google_weight(data_point: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    payload = data_point.get("weight") or {}
    timestamp = (payload.get("sampleTime") or {}).get("physicalTime")
    grams = _first_numeric(payload.get("weightGrams"))
    return timestamp, weight_values(grams) if grams is not None else {}


def metadata_signature(fields: dict[str, Any], common_tags: dict[str, str]) -> str:
    payload = json.dumps(
        {"fields": sanitize_fields(fields), "tags": common_tags},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _first_numeric(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    if isinstance(value, dict):
        for nested in value.values():
            found = _first_numeric(nested)
            if found is not None:
                return found
    if isinstance(value, list):
        for nested in value:
            found = _first_numeric(nested)
            if found is not None:
                return found
    return None
