from typing import Any, Mapping
from pytz.tzinfo import BaseTzInfo

"""Pure Google health mappings, preserving the collector measurement contracts."""
import logging
from app.domain.models import HealthPoint
from app.providers.google_health.parsing import extract_first_numeric

logger = logging.getLogger(__name__)


def map_hrv(
    data: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    records = []
    points = data.get("daily-heart-rate-variability", [])
    inserted_count = 0
    for data_point, ts in points:
        hrv_fields = data_point.get("dailyHeartRateVariability", {})
        rmssd = extract_first_numeric(
            hrv_fields.get("averageHeartRateVariabilityMilliseconds")
        )
        deep_rmssd = extract_first_numeric(
            hrv_fields.get("deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds")
        )
        non_rem_hr = extract_first_numeric(
            hrv_fields.get("nonRemHeartRateBeatsPerMinute")
        )
        entropy = extract_first_numeric(hrv_fields.get("entropy"))
        if rmssd is None and deep_rmssd is None:
            continue
        fields = {}
        if rmssd is not None:
            fields["dailyRmssd"] = rmssd
        if deep_rmssd is not None:
            fields["deepRmssd"] = deep_rmssd
        if non_rem_hr is not None:
            fields["nonRemHeartRateBpm"] = non_rem_hr
        if entropy is not None:
            fields["entropy"] = entropy
        records.append(
            {
                "measurement": "HRV",
                "time": ts,
                "tags": {"Device": device_name},
                "fields": fields,
            }
        )
        inserted_count += 1
    if inserted_count:
        logger.info(
            "Recorded HRV for date %s to %s (Google mode): %s points",
            start_date_str,
            end_date_str,
            inserted_count,
        )
    else:
        logger.warning(
            "No HRV records found for date %s to %s in Google mode",
            start_date_str,
            end_date_str,
        )
    return [HealthPoint.from_record(record) for record in records]


def map_breathing(
    data: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    records = []
    points = data.get("daily-respiratory-rate", [])
    inserted_count = 0
    for data_point, ts in points:
        br_fields = data_point.get("dailyRespiratoryRate", {})
        value = extract_first_numeric(br_fields.get("breathsPerMinute"))
        if value is None:
            continue
        records.append(
            {
                "measurement": "BreathingRate",
                "time": ts,
                "tags": {"Device": device_name},
                "fields": {"value": float(value)},
            }
        )
        inserted_count += 1
    if inserted_count:
        logger.info(
            "Recorded BR for date %s to %s (Google mode): %s points",
            start_date_str,
            end_date_str,
            inserted_count,
        )
    else:
        logger.warning(
            "No Breathing Rate records found for date %s to %s in Google mode",
            start_date_str,
            end_date_str,
        )
    return [HealthPoint.from_record(record) for record in records]


def map_temperature(
    data: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    records = []
    points = data.get("daily-sleep-temperature-derivations", [])
    inserted_count = 0
    for data_point, ts in points:
        temp_fields = data_point.get("dailySleepTemperatureDerivations", {})
        nightly = extract_first_numeric(temp_fields.get("nightlyTemperatureCelsius"))
        baseline = extract_first_numeric(temp_fields.get("baselineTemperatureCelsius"))
        relative = (
            round(nightly - baseline, 4)
            if nightly is not None and baseline is not None
            else None
        )
        stddev = extract_first_numeric(
            temp_fields.get("relativeNightlyStddev30dCelsius")
        )
        if relative is None:
            continue
        fields = {"RelativeValue": relative}
        if stddev is not None:
            fields["stddev30d"] = stddev
        if nightly is not None:
            fields["nightlyTemperatureCelsius"] = nightly
        if baseline is not None:
            fields["baselineTemperatureCelsius"] = baseline
        records.append(
            {
                "measurement": "Skin Temperature Variation",
                "time": ts,
                "tags": {"Device": device_name},
                "fields": fields,
            }
        )
        inserted_count += 1
    if inserted_count:
        logger.info(
            "Recorded Skin Temperature Variation for date %s to %s (Google mode): %s points",
            start_date_str,
            end_date_str,
            inserted_count,
        )
    else:
        logger.warning(
            "No Skin Temp records found for date %s to %s in Google mode",
            start_date_str,
            end_date_str,
        )
    return [HealthPoint.from_record(record) for record in records]


def map_oxygen(
    data: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    records = []
    points = data.get("oxygen-saturation", [])
    inserted_count = 0
    for data_point, ts in points:
        spo2_fields = data_point.get("oxygenSaturation", {})
        value = extract_first_numeric(
            spo2_fields.get("percentage")
        ) or extract_first_numeric(spo2_fields)
        if value is None:
            continue
        records.append(
            {
                "measurement": "SPO2_Intraday",
                "time": ts,
                "tags": {"Device": device_name},
                "fields": {"value": float(value)},
            }
        )
        inserted_count += 1
    if inserted_count:
        logger.info(
            "Recorded SPO2 intraday for date %s to %s (Google mode): %s points",
            start_date_str,
            end_date_str,
            inserted_count,
        )
    else:
        logger.warning(
            "No SPO2 intraday records found for date %s to %s in Google mode",
            start_date_str,
            end_date_str,
        )
    return [HealthPoint.from_record(record) for record in records]
