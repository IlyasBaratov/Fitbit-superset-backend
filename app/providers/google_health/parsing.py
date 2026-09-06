"""Pure Google payload and timestamp parsing."""

from datetime import datetime
import pytz


def extract_first_numeric(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and all(ch in "+-0123456789.eE" for ch in stripped):
            try:
                return float(stripped)
            except ValueError:
                pass
    if isinstance(value, dict):
        for nested in value.values():
            extracted = extract_first_numeric(nested)
            if extracted is not None:
                return extracted
    if isinstance(value, list):
        for nested in value:
            extracted = extract_first_numeric(nested)
            if extracted is not None:
                return extracted
    return None


def extract_numeric_fields(value, key_filter=None):
    fields = {}
    if not isinstance(value, dict):
        return fields
    for key, nested in value.items():
        if key_filter and key_filter not in key.lower():
            continue
        extracted = extract_first_numeric(nested)
        if extracted is not None:
            fields[key] = extracted
    return fields


def get_google_payload_key(data_type):
    parts = data_type.split("-")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def get_google_datapoint_payload(data_point, data_type):
    payload_key = get_google_payload_key(data_type)
    payload = data_point.get(payload_key)
    if isinstance(payload, dict):
        return payload
    return {}


def convert_google_duration_to_seconds(duration_value):
    if duration_value is None:
        return None
    if isinstance(duration_value, (int, float)):
        return float(duration_value)
    if isinstance(duration_value, str) and duration_value.endswith("s"):
        try:
            return float(duration_value[:-1])
        except ValueError:
            return None
    return None


def get_google_datapoint_date_string(data_point, data_type):
    payload = get_google_datapoint_payload(data_point, data_type)

    if isinstance(payload.get("date"), dict):
        date_value = payload["date"]
        try:
            return f"{int(date_value.get('year')):04d}-{int(date_value.get('month')):02d}-{int(date_value.get('day')):02d}"
        except (TypeError, ValueError):
            pass

    interval = payload.get("interval") if isinstance(payload, dict) else None
    if isinstance(interval, dict):
        civil_start = interval.get("civilStartTime")
        if isinstance(civil_start, dict):
            date_value = civil_start.get("date")
            if isinstance(date_value, dict):
                try:
                    return f"{int(date_value.get('year')):04d}-{int(date_value.get('month')):02d}-{int(date_value.get('day')):02d}"
                except (TypeError, ValueError):
                    pass

    return None


def parse_google_datapoint_timestamp(
    data_point, data_type=None, local_timezone=pytz.utc
):
    payload = get_google_datapoint_payload(data_point, data_type) if data_type else {}

    time_candidates = [
        data_point.get("sampleTime"),
        data_point.get("sample_time"),
        data_point.get("time"),
    ]

    if isinstance(payload, dict):
        time_candidates.extend(
            [
                payload.get("sampleTime"),
                payload.get("sample_time"),
                payload.get("time"),
            ]
        )

    sample_time = payload.get("sampleTime") if isinstance(payload, dict) else None
    if isinstance(sample_time, dict):
        time_candidates.extend(
            [
                sample_time.get("physicalTime"),
                sample_time.get("physical_time"),
            ]
        )

    interval = data_point.get("interval")
    if isinstance(interval, dict):
        time_candidates.extend(
            [
                interval.get("startTime"),
                interval.get("start_time"),
                interval.get("civilStartTime"),
                interval.get("civil_start_time"),
            ]
        )

    payload_interval = payload.get("interval") if isinstance(payload, dict) else None
    if isinstance(payload_interval, dict):
        time_candidates.extend(
            [
                payload_interval.get("startTime"),
                payload_interval.get("start_time"),
                payload_interval.get("endTime"),
                payload_interval.get("end_time"),
            ]
        )

    for candidate in time_candidates:
        if isinstance(candidate, str):
            normalized = candidate.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(normalized)
                if dt.tzinfo is None:
                    dt = local_timezone.localize(dt)
                return dt.astimezone(pytz.utc).isoformat()
            except ValueError:
                continue

    date_str = (
        get_google_datapoint_date_string(data_point, data_type) if data_type else None
    )
    if date_str:
        dt = local_timezone.localize(
            datetime.strptime(date_str + "T00:00:00", "%Y-%m-%dT%H:%M:%S")
        )
        return dt.astimezone(pytz.utc).isoformat()

    return None
