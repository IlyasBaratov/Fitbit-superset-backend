from typing import Any, Mapping
from pytz.tzinfo import BaseTzInfo

"""Pure Google health mappings, preserving the collector measurement contracts."""
from datetime import datetime, timedelta
import logging
import pytz
from app.domain.models import HealthPoint
from app.providers.google_health.parsing import (
    extract_first_numeric,
    convert_google_duration_to_seconds,
)

logger = logging.getLogger(__name__)


def _rollup(data, kind, day):
    return data.get(kind, {}).get(day.strftime("%Y-%m-%d"), {})


def map_resting(
    data: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    records = []
    points = data.get("daily-resting-heart-rate", [])
    inserted_count = 0
    for data_point, ts in points:
        rhr_fields = data_point.get("dailyRestingHeartRate", {})
        bpm = extract_first_numeric(rhr_fields.get("beatsPerMinute"))
        if bpm is None:
            continue
        records.append(
            {
                "measurement": "RestingHR",
                "time": ts,
                "tags": {"Device": device_name},
                "fields": {"value": float(bpm)},
            }
        )
        inserted_count += 1
    if inserted_count:
        logger.info(
            "Recorded Resting HR for date %s to %s (Google mode): %s points",
            start_date_str,
            end_date_str,
            inserted_count,
        )
    else:
        logger.warning(
            "No Resting HR records found for date %s to %s in Google mode",
            start_date_str,
            end_date_str,
        )
    return [HealthPoint.from_record(record) for record in records]


def map_zones(
    data: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    records = []
    az_start = datetime.strptime(start_date_str, "%Y-%m-%d")
    az_end = datetime.strptime(end_date_str, "%Y-%m-%d")
    current = az_start
    inserted_count = 0
    while current <= az_end:
        try:
            response = _rollup(data, "active-zone-minutes", current)
            rollup_points = (
                response.get("rollupDataPoints", [])
                if isinstance(response, dict)
                else []
            )
            for rp in rollup_points:
                azm = rp.get("activeZoneMinutes", {})
                fields = {}
                for field_name, provider_key in (
                    ("Fat Burn", "sumInFatBurnHeartZone"),
                    ("Cardio", "sumInCardioHeartZone"),
                    ("Peak", "sumInPeakHeartZone"),
                ):
                    value = (
                        extract_first_numeric(azm.get(provider_key))
                        if provider_key in azm
                        else None
                    )
                    if value is not None:
                        fields[field_name] = int(value)
                for total_key in ("totalActiveZoneMinutes", "sumActiveZoneMinutes"):
                    total_value = (
                        extract_first_numeric(azm.get(total_key))
                        if total_key in azm
                        else None
                    )
                    if total_value is not None:
                        fields["TotalActiveZoneMinutes"] = int(total_value)
                        break
                if not fields:
                    continue
                ts = local_timezone.localize(current).astimezone(pytz.utc).isoformat()
                records.append(
                    {
                        "measurement": "HR zones",
                        "time": ts,
                        "tags": {"Device": device_name},
                        "fields": fields,
                    }
                )
                inserted_count += 1
        except (TypeError, ValueError, KeyError) as e:
            logger.warning(
                "Google active-zone-minutes rollup failed for %s: %s",
                current.strftime("%Y-%m-%d"),
                str(e),
            )
        current += timedelta(days=1)
    if inserted_count:
        logger.info(
            "Recorded HR Zones for date %s to %s (Google mode): %s points",
            start_date_str,
            end_date_str,
            inserted_count,
        )
    else:
        logger.warning(
            "No HR Zone records found for date %s to %s in Google mode",
            start_date_str,
            end_date_str,
        )
    return [HealthPoint.from_record(record) for record in records]


def map_daily_totals(
    data: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    records = []
    rollup_map = [
        ("steps", "Total Steps", "value", float),
        ("total-calories", "calories", "value", float),
    ]
    for data_type, measurement_name, field_name, cast_fn in rollup_map:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
        current = start_date
        inserted_count = 0
        while current <= end_date:
            next_day = current + timedelta(days=1)
            try:
                response = _rollup(data, data_type, current)
            except (TypeError, ValueError, KeyError) as e:
                logger.warning(
                    "Google dailyRollUp failed for %s on %s: %s",
                    data_type,
                    current.strftime("%Y-%m-%d"),
                    str(e),
                )
                current = next_day
                continue
            rollup_points = (
                response.get("rollupDataPoints", [])
                if isinstance(response, dict)
                else []
            )
            for rp in rollup_points:
                value = None
                if data_type == "steps":
                    value = extract_first_numeric(rp.get("steps", {}).get("countSum"))
                elif data_type == "total-calories":
                    value = extract_first_numeric(
                        rp.get("totalCalories", {}).get("kcalSum")
                    )
                if value is None:
                    continue
                civil_start = rp.get("civilStartTime", {})
                date_val = civil_start.get("date", {})
                try:
                    dt = local_timezone.localize(
                        datetime(
                            int(date_val.get("year", current.year)),
                            int(date_val.get("month", current.month)),
                            int(date_val.get("day", current.day)),
                        )
                    )
                    ts = dt.astimezone(pytz.utc).isoformat()
                except (TypeError, ValueError, KeyError):
                    ts = (
                        local_timezone.localize(current)
                        .astimezone(pytz.utc)
                        .isoformat()
                    )
                records.append(
                    {
                        "measurement": measurement_name,
                        "time": ts,
                        "tags": {"Device": device_name},
                        "fields": {field_name: cast_fn(value)},
                    }
                )
                inserted_count += 1
            current = next_day
        if inserted_count:
            logger.info(
                "Recorded %s for date %s to %s (Google mode): %s points",
                measurement_name,
                start_date_str,
                end_date_str,
                inserted_count,
            )
        else:
            logger.warning(
                "No %s records found for date %s to %s in Google mode",
                measurement_name,
                start_date_str,
                end_date_str,
            )
    return [HealthPoint.from_record(record) for record in records]


def map_distance(
    data: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    records = []
    dist_start = datetime.strptime(start_date_str, "%Y-%m-%d")
    dist_end = datetime.strptime(end_date_str, "%Y-%m-%d")
    current = dist_start
    inserted_count = 0
    while current <= dist_end:
        try:
            dist_response = _rollup(data, "distance", current)
            for rp in (
                dist_response.get("rollupDataPoints", [])
                if isinstance(dist_response, dict)
                else []
            ):
                mm = extract_first_numeric(rp.get("distance", {}).get("millimetersSum"))
                if mm is not None:
                    ts = (
                        local_timezone.localize(current)
                        .astimezone(pytz.utc)
                        .isoformat()
                    )
                    records.append(
                        {
                            "measurement": "distance",
                            "time": ts,
                            "tags": {"Device": device_name},
                            "fields": {"value": float(mm / 1000000)},
                        }
                    )
                    inserted_count += 1
        except (TypeError, ValueError, KeyError) as e:
            logger.warning(
                "Google distance rollup failed for %s: %s",
                current.strftime("%Y-%m-%d"),
                str(e),
            )
        current += timedelta(days=1)
    if inserted_count:
        logger.info(
            "Recorded distance for date %s to %s (Google mode): %s points",
            start_date_str,
            end_date_str,
            inserted_count,
        )
    else:
        logger.warning(
            "No distance records found for date %s to %s in Google mode",
            start_date_str,
            end_date_str,
        )
    return [HealthPoint.from_record(record) for record in records]


def map_sedentary(
    data: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    records = []
    sedentary_start = datetime.strptime(start_date_str, "%Y-%m-%d")
    sedentary_end = datetime.strptime(end_date_str, "%Y-%m-%d")
    current = sedentary_start
    inserted_count = 0
    while current <= sedentary_end:
        try:
            sedentary_response = _rollup(data, "sedentary-period", current)
            rollup_points = (
                sedentary_response.get("rollupDataPoints", [])
                if isinstance(sedentary_response, dict)
                else []
            )
            total_sedentary_minutes = 0
            for rp in rollup_points:
                sedentary_data = rp.get("sedentaryPeriod", {})
                duration = (
                    sedentary_data.get("durationSum")
                    or sedentary_data.get("durationSeconds")
                    or sedentary_data.get("duration")
                )
                secs = convert_google_duration_to_seconds(duration)
                if secs is not None:
                    total_sedentary_minutes += secs / 60
            if total_sedentary_minutes > 0:
                ts = local_timezone.localize(current).astimezone(pytz.utc).isoformat()
                records.append(
                    {
                        "measurement": "Activity Minutes",
                        "time": ts,
                        "tags": {"Device": device_name},
                        "fields": {"minutesSedentary": int(total_sedentary_minutes)},
                    }
                )
                inserted_count += 1
        except (TypeError, ValueError, KeyError) as e:
            logger.warning(
                "Google sedentary-period rollup failed for %s: %s",
                current.strftime("%Y-%m-%d"),
                str(e),
            )
        current += timedelta(days=1)
    if inserted_count:
        logger.info(
            "Recorded Activity Minutes (sedentary) for date %s to %s (Google mode): %s points",
            start_date_str,
            end_date_str,
            inserted_count,
        )
    else:
        logger.warning(
            "No sedentary period records found for date %s to %s in Google mode",
            start_date_str,
            end_date_str,
        )
    return [HealthPoint.from_record(record) for record in records]
