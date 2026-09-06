from typing import Any, Mapping
from pytz.tzinfo import BaseTzInfo

"""Pure Fitbit payload mappings preserving historical measurements."""
from datetime import datetime
import logging
import pytz
from app.domain.models import HealthPoint
from app.domain.normalization import sanitize_fields, sleep_stage

logger = logging.getLogger(__name__)


def map_sleep(
    payloads: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    records = []
    sleep_data = payloads.get("sleep", {}).get("sleep")
    if sleep_data != None:
        for record in sleep_data:
            log_time = datetime.fromisoformat(record["startTime"])
            utc_time = (
                local_timezone.localize(log_time).astimezone(pytz.utc).isoformat()
            )
            sleep_session_id = (
                str(record.get("logId")) if record.get("logId") is not None else None
            )
            is_main_sleep = str(bool(record.get("isMainSleep"))).lower()
            try:
                minutesLight = record["levels"]["summary"]["light"]["minutes"]
                minutesREM = record["levels"]["summary"]["rem"]["minutes"]
                minutesDeep = record["levels"]["summary"]["deep"]["minutes"]
            except KeyError:
                minutesLight = record["levels"]["summary"]["asleep"]["minutes"]
                minutesREM = record["levels"]["summary"]["restless"]["minutes"]
                minutesDeep = 0
            records.append(
                {
                    "measurement": "Sleep Summary",
                    "time": utc_time,
                    "tags": {"Device": device_name, "isMainSleep": is_main_sleep},
                    "fields": sanitize_fields(
                        {
                            "SleepSessionId": sleep_session_id,
                            "efficiency": record["efficiency"],
                            "minutesAfterWakeup": record["minutesAfterWakeup"],
                            "minutesAsleep": record["minutesAsleep"],
                            "minutesToFallAsleep": record["minutesToFallAsleep"],
                            "minutesInBed": record["timeInBed"],
                            "minutesAwake": record["minutesAwake"],
                            "minutesLight": minutesLight,
                            "minutesREM": minutesREM,
                            "minutesDeep": minutesDeep,
                            "startTime": record.get("startTime"),
                            "endTime": record.get("endTime"),
                        }
                    ),
                }
            )
            for stage in record["levels"]["data"]:
                log_time = datetime.fromisoformat(stage["dateTime"])
                utc_time = (
                    local_timezone.localize(log_time).astimezone(pytz.utc).isoformat()
                )
                level, stage_name = sleep_stage(stage.get("level"))
                records.append(
                    {
                        "measurement": "Sleep Levels",
                        "time": utc_time,
                        "tags": {"Device": device_name, "isMainSleep": is_main_sleep},
                        "fields": {
                            "SleepSessionId": sleep_session_id,
                            "level": level,
                            "stageName": stage_name,
                            "duration_seconds": stage.get("seconds"),
                        },
                    }
                )
            wake_time = datetime.fromisoformat(record["endTime"])
            utc_wake_time = (
                local_timezone.localize(wake_time).astimezone(pytz.utc).isoformat()
            )
            records.append(
                {
                    "measurement": "Sleep Levels",
                    "time": utc_wake_time,
                    "tags": {"Device": device_name, "isMainSleep": is_main_sleep},
                    "fields": {
                        "SleepSessionId": sleep_session_id,
                        "level": 3,
                        "stageName": "awake",
                    },
                }
            )
        logger.info(
            "Recorded Sleep data for date " + start_date_str + " to " + end_date_str
        )
    else:
        logger.error(
            "Recording failed : Sleep data for date "
            + start_date_str
            + " to "
            + end_date_str
        )
    return [HealthPoint.from_record(record) for record in records]
