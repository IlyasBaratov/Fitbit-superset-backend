from typing import Any, Mapping
from pytz.tzinfo import BaseTzInfo

"""Pure Fitbit payload mappings preserving historical measurements."""
from datetime import datetime
import logging
import pytz
from app.domain.models import HealthPoint

logger = logging.getLogger(__name__)


def map_hrv(
    payloads: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    records = []
    hrv_data_list = payloads.get("hrv", {}).get("hrv")
    if hrv_data_list != None:
        for data in hrv_data_list:
            log_time = datetime.fromisoformat(data["dateTime"] + "T" + "00:00:00")
            utc_time = (
                local_timezone.localize(log_time).astimezone(pytz.utc).isoformat()
            )
            records.append(
                {
                    "measurement": "HRV",
                    "time": utc_time,
                    "tags": {"Device": device_name},
                    "fields": {
                        "dailyRmssd": float(data["value"]["dailyRmssd"])
                        if data["value"]["dailyRmssd"]
                        else None,
                        "deepRmssd": float(data["value"]["deepRmssd"])
                        if data["value"]["deepRmssd"]
                        else None,
                    },
                }
            )
        logger.info("Recorded HRV for date " + start_date_str + " to " + end_date_str)
    else:
        logger.error(
            "Recording failed HRV for date " + start_date_str + " to " + end_date_str
        )
    return [HealthPoint.from_record(record) for record in records]


def map_breathing(
    payloads: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    records = []
    br_response = payloads.get("breathing", {})
    br_data_list = br_response.get("br") if br_response else None
    if br_data_list != None:
        for data in br_data_list:
            log_time = datetime.fromisoformat(data["dateTime"] + "T" + "00:00:00")
            utc_time = (
                local_timezone.localize(log_time).astimezone(pytz.utc).isoformat()
            )
            records.append(
                {
                    "measurement": "BreathingRate",
                    "time": utc_time,
                    "tags": {"Device": device_name},
                    "fields": {"value": float(data["value"]["breathingRate"])},
                }
            )
        logger.info("Recorded BR for date " + start_date_str + " to " + end_date_str)
    else:
        logger.warning(
            "Records not found : BR for date " + start_date_str + " to " + end_date_str
        )
    return [HealthPoint.from_record(record) for record in records]


def map_temperature(
    payloads: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    records = []
    skin_temp_data_list = payloads.get("skin_temperature", {}).get("tempSkin")
    if skin_temp_data_list != None:
        for temp_record in skin_temp_data_list:
            log_time = datetime.fromisoformat(
                temp_record["dateTime"] + "T" + "00:00:00"
            )
            utc_time = (
                local_timezone.localize(log_time).astimezone(pytz.utc).isoformat()
            )
            records.append(
                {
                    "measurement": "Skin Temperature Variation",
                    "time": utc_time,
                    "tags": {"Device": device_name},
                    "fields": {
                        "RelativeValue": float(temp_record["value"]["nightlyRelative"])
                    },
                }
            )
        logger.info(
            "Recorded Skin Temperature Variation for date "
            + start_date_str
            + " to "
            + end_date_str
        )
    else:
        logger.error(
            "Recording failed : Skin Temperature Variation for date "
            + start_date_str
            + " to "
            + end_date_str
        )
    return [HealthPoint.from_record(record) for record in records]


def map_oxygen(
    payloads: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    records = []
    spo2_data_list = payloads.get("spo2_intraday", [])
    if spo2_data_list != None:
        for days in spo2_data_list:
            data = days["minutes"]
            for record in data:
                log_time = datetime.fromisoformat(record["minute"])
                utc_time = (
                    local_timezone.localize(log_time).astimezone(pytz.utc).isoformat()
                )
                records.append(
                    {
                        "measurement": "SPO2_Intraday",
                        "time": utc_time,
                        "tags": {"Device": device_name},
                        "fields": {"value": float(record["value"])},
                    }
                )
        logger.info(
            "Recorded SPO2 intraday for date " + start_date_str + " to " + end_date_str
        )
    else:
        logger.error(
            "Recording failed : SPO2 intraday for date "
            + start_date_str
            + " to "
            + end_date_str
        )
    return [HealthPoint.from_record(record) for record in records]


def map_body(
    payloads: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    records = []
    weight_data_list = payloads.get("weight", {}).get("weight")
    if weight_data_list != None:
        for entry in weight_data_list:
            log_time = datetime.fromisoformat(entry["date"] + "T" + entry["time"])
            utc_time = (
                local_timezone.localize(log_time).astimezone(pytz.utc).isoformat()
            )
            records.append(
                {
                    "measurement": "weight",
                    "time": utc_time,
                    "tags": {"Device": device_name},
                    "fields": {"value": float(entry["weight"])},
                }
            )
            records.append(
                {
                    "measurement": "bmi",
                    "time": utc_time,
                    "tags": {"Device": device_name},
                    "fields": {"value": float(entry["bmi"])},
                }
            )
        logger.info(
            "Recorded weight and BMI for date " + start_date_str + " to " + end_date_str
        )
    else:
        logger.error(
            "Recording failed : weight and BMI for date "
            + start_date_str
            + " to "
            + end_date_str
        )
    return [HealthPoint.from_record(record) for record in records]
