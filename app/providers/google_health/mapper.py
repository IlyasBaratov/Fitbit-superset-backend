from __future__ import annotations
import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any
import pytz
from app.domain.normalization import sanitize_fields, stable_resource_id, normalize_duration_seconds, distance_meters_to_km, height_values, weight_values


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
