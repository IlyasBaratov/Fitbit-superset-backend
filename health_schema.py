"""Compatibility exports for the extracted health schema."""

from app.domain.measurements import COMMON_TAG_KEYS, SLEEP_STAGE_MAPPING, FIELD_TYPES
from app.domain.normalization import (
    build_common_tags,
    sanitize_fields,
    utc_timestamp,
    local_date_boundary_utc,
    point_identity,
    weight_values,
    height_values,
    calculate_bmi,
    distance_meters_to_km,
    normalize_duration_seconds,
    sleep_efficiency,
    sleep_stage,
    stable_resource_id,
    metadata_signature,
)
from app.storage.influx.schema import coerce_fields, prepare_point, prepare_points
from app.providers.google_health.mapper import (
    parse_google_exercise,
    parse_google_height,
    parse_google_weight,
)

__all__ = [
    "COMMON_TAG_KEYS",
    "SLEEP_STAGE_MAPPING",
    "FIELD_TYPES",
    "build_common_tags",
    "sanitize_fields",
    "utc_timestamp",
    "local_date_boundary_utc",
    "point_identity",
    "weight_values",
    "height_values",
    "calculate_bmi",
    "distance_meters_to_km",
    "normalize_duration_seconds",
    "sleep_efficiency",
    "sleep_stage",
    "stable_resource_id",
    "metadata_signature",
    "coerce_fields",
    "prepare_point",
    "prepare_points",
    "parse_google_exercise",
    "parse_google_height",
    "parse_google_weight",
]
