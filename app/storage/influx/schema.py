from __future__ import annotations
import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any
import pytz
from app.domain.measurements import COMMON_TAG_KEYS, FIELD_TYPES
from app.domain.normalization import sanitize_fields, utc_timestamp


def coerce_fields(measurement: str, fields: dict[str, Any], field_types=None) -> dict[str, Any]:
    schema = (FIELD_TYPES if field_types is None else field_types).get(measurement, {})
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


def prepare_point(point: dict[str, Any], common_tags: dict[str, str], local_timezone: str, field_types=None) -> dict[str, Any] | None:
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

    fields = coerce_fields(measurement, dict(point.get("fields") or {}), field_types)
    if not fields:
        return None
    return {"measurement": measurement, "time": timestamp, "tags": tags, "fields": fields}


def prepare_points(points: list[dict[str, Any]], common_tags: dict[str, str], local_timezone: str, field_types=None) -> list[dict[str, Any]]:
    prepared = []
    for point in points:
        normalized = prepare_point(point, common_tags, local_timezone, field_types)
        if normalized is not None:
            prepared.append(normalized)
    return prepared
