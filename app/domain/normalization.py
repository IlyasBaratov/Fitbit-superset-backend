from __future__ import annotations
import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any
import pytz
from app.domain.measurements import SLEEP_STAGE_MAPPING


def build_common_tags(
    user_id: str, provider: str, device_name: str, device_id: str
) -> dict[str, str]:
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
    local_midnight = pytz.timezone(local_timezone).localize(
        datetime(parsed_date.year, parsed_date.month, parsed_date.day)
    )
    return local_midnight.astimezone(timezone.utc).isoformat()


def point_identity(
    point: dict[str, Any],
) -> tuple[str, tuple[tuple[str, str], ...], str]:
    return (
        str(point["measurement"]),
        tuple(
            sorted(
                (str(key), str(value)) for key, value in point.get("tags", {}).items()
            )
        ),
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


def sleep_efficiency(
    minutes_asleep: Any, minutes_in_bed: Any, provider_value: Any = None
) -> int | None:
    if provider_value is not None:
        return int(round(float(provider_value)))
    if minutes_asleep is None or minutes_in_bed is None:
        return None
    in_bed = int(minutes_in_bed)
    if in_bed <= 0:
        return None
    return round(int(minutes_asleep) / in_bed * 100)


def sleep_stage(value: Any) -> tuple[int, str]:
    return SLEEP_STAGE_MAPPING.get(
        str(value or "UNKNOWN").strip().upper(), (4, "unknown")
    )


def stable_resource_id(resource_name: Any) -> str | None:
    text = str(resource_name or "").strip()
    return text.rsplit("/", 1)[-1] if text else None


def metadata_signature(fields: dict[str, Any], common_tags: dict[str, str]) -> str:
    payload = json.dumps(
        {"fields": sanitize_fields(fields), "tags": common_tags},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
