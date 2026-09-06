from typing import Any, Mapping
from pytz.tzinfo import BaseTzInfo

"""Pure Google health mappings, preserving the collector measurement contracts."""
from datetime import datetime
import logging
from app.domain.models import HealthPoint
from app.domain.normalization import calculate_bmi
from app.providers.google_health.mapper import parse_google_height, parse_google_weight

logger = logging.getLogger(__name__)


def map_body(
    data: Mapping[str, Any],
    start_date_str: str,
    end_date_str: str,
    device_name: str,
    local_timezone: BaseTzInfo,
) -> list[HealthPoint]:
    records = []
    height_samples = []
    height_inserted_count = 0
    height_response = data.get("height", {})
    seen_height_timestamps = set()
    for data_point in (
        height_response.get("dataPoints", [])
        if isinstance(height_response, dict)
        else []
    ):
        height_time, height_fields = parse_google_height(data_point)
        if (
            not height_time
            or not height_fields
            or height_time in seen_height_timestamps
        ):
            continue
        seen_height_timestamps.add(height_time)
        height_samples.append(
            (
                datetime.fromisoformat(height_time.replace("Z", "+00:00")),
                height_fields["heightMeters"],
            )
        )
        records.append(
            {"measurement": "height", "time": height_time, "fields": height_fields}
        )
        height_inserted_count += 1
    height_samples.sort(key=lambda item: item[0])
    if height_inserted_count:
        logger.info("Recorded height (Google mode): %s points", height_inserted_count)
    else:
        logger.warning("No height records available in Google mode")
    points = data.get("weight", [])
    inserted_count = 0
    seen_weight_timestamps = set()
    for data_point, ts in points:
        weight_time, weight_fields = parse_google_weight(data_point)
        weight_time = weight_time or ts
        if (
            not weight_time
            or not weight_fields
            or weight_time in seen_weight_timestamps
        ):
            continue
        seen_weight_timestamps.add(weight_time)
        records.append(
            {"measurement": "weight", "time": weight_time, "fields": weight_fields}
        )
        inserted_count += 1
        weight_dt = datetime.fromisoformat(weight_time.replace("Z", "+00:00"))
        eligible_heights = [
            sample for sample in height_samples if sample[0] <= weight_dt
        ]
        height_meters = eligible_heights[-1][1] if eligible_heights else None
        bmi = calculate_bmi(weight_fields.get("weightKg"), height_meters)
        if bmi is not None:
            records.append(
                {
                    "measurement": "bmi",
                    "time": weight_time,
                    "fields": {
                        "value": bmi,
                        "weightKg": weight_fields.get("weightKg"),
                        "heightMeters": height_meters,
                        "isCalculated": True,
                    },
                }
            )
            inserted_count += 1
    if inserted_count:
        logger.info(
            "Recorded weight and BMI for date %s to %s (Google mode): %s points",
            start_date_str,
            end_date_str,
            inserted_count,
        )
    else:
        logger.warning(
            "No Weight/BMI records found for date %s to %s in Google mode",
            start_date_str,
            end_date_str,
        )
    return [HealthPoint.from_record(record) for record in records]
