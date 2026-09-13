"""Pure mappings for Google Health ECG and irregular-rhythm sessions."""

from typing import Any, Mapping
from pytz.tzinfo import BaseTzInfo

from app.domain.models import HealthPoint
from app.domain.normalization import sanitize_fields, stable_resource_id


def _device_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    device = payload.get("medicalDeviceInfo")
    if not isinstance(device, dict):
        return {}
    return {
        "deviceModel": device.get("deviceModel"),
        "firmwareVersion": device.get("firmwareVersion"),
        "featureVersion": device.get("featureVersion"),
        "algorithmVersion": device.get("algorithmVersion"),
        "serviceVersion": device.get("serviceVersion"),
    }


def map_ecg(
    data: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    del start_date_str, end_date_str, local_timezone
    records = []
    for data_point, timestamp in data.get("electrocardiogram", []):
        payload = data_point.get("electrocardiogram")
        if not isinstance(payload, dict):
            continue
        interval = payload.get("interval") or {}
        samples = payload.get("waveformSamples")
        fields = sanitize_fields(
            {
                "EcgSessionId": stable_resource_id(data_point.get("name")),
                "resultClassification": payload.get("resultClassification"),
                "averageHeartRateBpm": payload.get("beatsPerMinuteAvg"),
                "samplingFrequencyHertz": payload.get("samplingFrequencyHertz"),
                "leadNumber": payload.get("leadNumber"),
                "millivoltsScalingFactor": payload.get("millivoltsScalingFactor"),
                "sampleCount": len(samples) if isinstance(samples, list) else None,
                "startTime": interval.get("startTime"),
                "endTime": interval.get("endTime"),
                **_device_fields(payload),
            }
        )
        if fields:
            records.append(
                HealthPoint("Electrocardiogram", timestamp, fields, {"Device": device_name})
            )
    return records


def map_irn(
    data: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    del start_date_str, end_date_str, local_timezone
    records = []
    for data_point, timestamp in data.get("irregular-rhythm-notification", []):
        payload = data_point.get("irregularRhythmNotification")
        if not isinstance(payload, dict):
            continue
        interval = payload.get("interval") or {}
        windows = payload.get("alertWindows")
        windows = windows if isinstance(windows, list) else []
        positive_count = sum(
            1 for window in windows if isinstance(window, dict) and window.get("positive") is True
        )
        heartbeat_count = sum(
            len(window.get("heartBeats") or [])
            for window in windows
            if isinstance(window, dict) and isinstance(window.get("heartBeats") or [], list)
        )
        fields = sanitize_fields(
            {
                "NotificationId": stable_resource_id(data_point.get("name")),
                # The data point itself is an IRN alert for a potential sign of AFib;
                # alertWindows is optional even though current alerts use positive windows.
                "potentialAtrialFibrillation": True,
                "alertWindowCount": len(windows),
                "positiveAlertWindowCount": positive_count,
                "heartBeatCount": heartbeat_count,
                "startTime": interval.get("startTime"),
                "endTime": interval.get("endTime"),
                **_device_fields(payload),
            }
        )
        if fields:
            records.append(
                HealthPoint(
                    "Irregular Rhythm Notifications",
                    timestamp,
                    fields,
                    {"Device": device_name},
                )
            )
    return records
