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
        stages_map = {
            s["type"]: int(s["minutes"])
            for s in stages_summary
            if s.get("type") and s.get("minutes") is not None
        }
        def optional_minutes(name):
            value = summary.get(name)
            return int(value) if value is not None else None

        minutes_asleep = optional_minutes("minutesAsleep")
        minutes_awake = optional_minutes("minutesAwake")
        minutes_in_period = optional_minutes("minutesInSleepPeriod")
        minutes_after_wakeup = optional_minutes("minutesAfterWakeUp")
        minutes_to_fall = optional_minutes("minutesToFallAsleep")
        minutes_light = stages_map.get("LIGHT")
        minutes_rem = stages_map.get("REM")
        minutes_deep = stages_map.get("DEEP")
        efficiency = sleep_efficiency(
            minutes_asleep, minutes_in_period, summary.get("efficiency")
        )
        metadata = sleep.get("metadata") or {}
        is_main_sleep = str(bool(metadata.get("mainSleep", True))).lower()
        short_awakenings = sleep.get("shortAwakenings") or []
        short_awake_seconds = 0
        valid_awakenings = []
        for awakening in short_awakenings:
            try:
                beginning = datetime.fromisoformat(
                    awakening["startTime"].replace("Z", "+00:00")
                )
                ending = datetime.fromisoformat(
                    awakening["endTime"].replace("Z", "+00:00")
                )
                duration = int((ending - beginning).total_seconds())
                if beginning.tzinfo is None or ending.tzinfo is None or duration <= 0:
                    continue
                short_awake_seconds += duration
                valid_awakenings.append((beginning, ending, duration))
            except (KeyError, TypeError, ValueError):
                continue
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
                        **(
                            {
                                "shortAwakeningCount": len(valid_awakenings),
                                "shortAwakeningSeconds": short_awake_seconds,
                            }
                            if "shortAwakenings" in sleep
                            else {
                                "shortAwakeningSeconds": summary.get("shortAwakeningSeconds")
                            }
                        ),
                        "startTime": start_time_str,
                        "endTime": session_end_time_str,
                        "isProcessed": metadata.get("processed"),
                    }
                ),
            }
        )
        inserted_count += 1
        for beginning, ending, duration in valid_awakenings:
            records.append(
                {
                    "measurement": "Sleep Short Awakenings",
                    "time": beginning.astimezone(pytz.utc).isoformat(),
                    "tags": {"Device": device_name, "isMainSleep": is_main_sleep},
                    "fields": {
                        "SleepSessionId": sleep_session_id,
                        "endTime": ending.astimezone(pytz.utc).isoformat(),
                        "duration_seconds": duration,
                    },
                }
            )
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
