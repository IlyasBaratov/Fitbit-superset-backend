from typing import Any, Mapping
from pytz.tzinfo import BaseTzInfo

"""Pure Google health mappings, preserving the collector measurement contracts."""
from datetime import datetime
import logging
import pytz
from app.domain.models import HealthPoint
from app.domain.normalization import (
    sanitize_fields,
    sleep_efficiency,
    sleep_stage,
    stable_resource_id,
)

logger = logging.getLogger(__name__)


def map_sleep(
    data: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    records = []
    points = data.get("sleep", [])
    inserted_count = 0
    for data_point, ts in points:
        sleep = data_point.get("sleep", {})
        if not sleep:
            continue
        summary = sleep.get("summary", {})
        stages_summary = summary.get("stagesSummary", [])
        stages_map = {s["type"]: int(s.get("minutes", 0)) for s in stages_summary}
        minutes_asleep = int(summary.get("minutesAsleep", 0))
        minutes_awake = int(summary.get("minutesAwake", 0))
        minutes_in_period = int(summary.get("minutesInSleepPeriod", 0))
        minutes_after_wakeup = int(summary.get("minutesAfterWakeUp", 0))
        minutes_to_fall = int(summary.get("minutesToFallAsleep", 0))
        minutes_light = stages_map.get("LIGHT", 0)
        minutes_rem = stages_map.get("REM", 0)
        minutes_deep = stages_map.get("DEEP", 0)
        efficiency = sleep_efficiency(
            minutes_asleep, minutes_in_period, summary.get("efficiency")
        )
        is_main_sleep = str(
            bool(sleep.get("metadata", {}).get("processed", True))
        ).lower()
        sleep_session_id = stable_resource_id(data_point.get("name"))
        interval = sleep.get("interval", {})
        start_time_str = interval.get("startTime") or ts
        session_end_time_str = interval.get("endTime")
        records.append(
            {
                "measurement": "Sleep Summary",
                "time": start_time_str,
                "tags": {"Device": device_name, "isMainSleep": is_main_sleep},
                "fields": sanitize_fields(
                    {
                        "SleepSessionId": sleep_session_id,
                        "efficiency": efficiency,
                        "minutesAfterWakeup": minutes_after_wakeup,
                        "minutesAsleep": minutes_asleep,
                        "minutesToFallAsleep": minutes_to_fall,
                        "minutesInBed": minutes_in_period,
                        "minutesAwake": minutes_awake,
                        "minutesLight": minutes_light,
                        "minutesREM": minutes_rem,
                        "minutesDeep": minutes_deep,
                        "startTime": start_time_str,
                        "endTime": session_end_time_str,
                    }
                ),
            }
        )
        inserted_count += 1
        for stage in sleep.get("stages", []):
            stage_time_str = stage.get("startTime")
            if not stage_time_str:
                continue
            try:
                stage_dt = datetime.fromisoformat(stage_time_str.replace("Z", "+00:00"))
                stage_ts = stage_dt.astimezone(pytz.utc).isoformat()
            except ValueError:
                continue
            level, stage_name = sleep_stage(stage.get("type"))
            stage_end_time_str = stage.get("endTime")
            duration_secs = None
            if stage_end_time_str:
                try:
                    end_dt = datetime.fromisoformat(
                        stage_end_time_str.replace("Z", "+00:00")
                    )
                    duration_secs = int((end_dt - stage_dt).total_seconds())
                except ValueError:
                    pass
            records.append(
                {
                    "measurement": "Sleep Levels",
                    "time": stage_ts,
                    "tags": {"Device": device_name, "isMainSleep": is_main_sleep},
                    "fields": sanitize_fields(
                        {
                            "SleepSessionId": sleep_session_id,
                            "level": level,
                            "stageName": stage_name,
                            "duration_seconds": duration_secs,
                        }
                    ),
                }
            )
        if session_end_time_str:
            try:
                wake_dt = datetime.fromisoformat(
                    session_end_time_str.replace("Z", "+00:00")
                )
                wake_ts = wake_dt.astimezone(pytz.utc).isoformat()
                records.append(
                    {
                        "measurement": "Sleep Levels",
                        "time": wake_ts,
                        "tags": {"Device": device_name, "isMainSleep": is_main_sleep},
                        "fields": {
                            "SleepSessionId": sleep_session_id,
                            "level": 3,
                            "stageName": "awake",
                        },
                    }
                )
            except ValueError:
                pass
    if inserted_count:
        logger.info(
            "Recorded Sleep data for date %s to %s (Google mode): %s sessions",
            start_date_str,
            end_date_str,
            inserted_count,
        )
    else:
        logger.warning(
            "No Sleep records found for date %s to %s in Google mode",
            start_date_str,
            end_date_str,
        )
    return [HealthPoint.from_record(record) for record in records]
