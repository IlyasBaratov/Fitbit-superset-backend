"""Bounded health reads using the existing identity-scoped query layer."""

from datetime import datetime, timedelta, timezone
import re
import pytz
from pydantic import ValidationError
from app.errors import APIError
from app.core.exceptions import DataUnavailable, QueryLimitExceeded
from app.storage.influx.queries import INTRADAY, MAX_ROWS
from app.api.schemas.health import (
    HealthResponse,
    HealthSeries,
    HealthRow,
    DevicesResponse,
    DeviceObservation,
)

HEALTH_MEASUREMENTS = {
    "heart-rate": ("HeartRate_Intraday", "RestingHR", "HRV", "HR zones"),
    "sleep": ("Sleep Summary", "Sleep Levels"),
    "activity": (
        "Steps_Intraday",
        "Total Steps",
        "calories",
        "distance",
        "Activity Minutes",
    ),
    "workouts": ("Activity Records",),
    "spo2": ("SPO2", "SPO2_Intraday"),
    "body": ("height", "weight", "bmi"),
    "calendar": ("Calendar Events",),
}


def resolve_interval(settings, clock, period=None):
    """Whole local days up to now; shared by every bounded read (health, calendar)."""
    days = settings.default_days
    if period is not None:
        if not re.fullmatch(r"[1-9][0-9]?d", period):
            raise APIError(
                "INVALID_HEALTH_PERIOD",
                "Period must be a day count such as 7d.",
                422,
            )
        days = int(period[:-1])
    if not 1 <= days <= settings.max_days:
        raise APIError(
            "INVALID_HEALTH_PERIOD",
            f"Period must be between 1 and {settings.max_days} days.",
            422,
        )
    zone = pytz.timezone(settings.timezone)
    end = clock().astimezone(timezone.utc)
    first = end.astimezone(zone).date() - timedelta(days=days - 1)
    start = zone.localize(datetime.combine(first, datetime.min.time())).astimezone(
        timezone.utc
    )
    return start, end, days


class HealthReadService:
    def __init__(self, settings, repository, clock=None):
        self.settings, self.repository = settings, repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _interval(self, period):
        start, end, _ = resolve_interval(self.settings, self.clock, period)
        return start, end

    @staticmethod
    def _row(row):
        timestamp = datetime.fromisoformat(str(row["time"]).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("Stored timestamp must include timezone")
        return {
            "timestamp": timestamp.astimezone(timezone.utc),
            "fields": {
                key: value
                for key, value in row.items()
                if key != "time" and value is not None
            },
        }

    def read(self, category: str, period: str | None = None) -> HealthResponse:
        start, end = self._interval(period)
        try:
            series = []
            for measurement in HEALTH_MEASUREMENTS[category]:
                rows = (
                    self.repository.query(measurement, start, end)
                    if start < end
                    else []
                )
                if len(rows) > MAX_ROWS:
                    raise QueryLimitExceeded("Use a shorter period")
                series.append(
                    HealthSeries(
                        measurement=measurement,
                        resolution="hourly" if measurement in INTRADAY else "stored",
                        rows=[HealthRow(**self._row(row)) for row in rows],
                    )
                )
            return HealthResponse(
                start=start, end=end, timezone=self.settings.timezone, series=series
            )
        except QueryLimitExceeded:
            raise APIError(
                "HEALTH_QUERY_TOO_LARGE",
                "Requested data exceeds the safe query limit; use a shorter period.",
                422,
            ) from None
        except (DataUnavailable, ValidationError, KeyError, ValueError, TypeError):
            raise APIError(
                "DATA_SERVICE_UNAVAILABLE",
                "Health data is temporarily unavailable.",
                503,
            ) from None

    def devices(self) -> DevicesResponse:
        try:
            observations = []
            for measurement in ("Device Metadata", "DeviceBatteryLevel"):
                row = self.repository.latest_device_observation(measurement)
                if row is not None:
                    observations.append(
                        DeviceObservation(measurement=measurement, **self._row(row))
                    )
            return DevicesResponse(
                device_id=self.settings.device_id,
                provider=self.settings.provider,
                observations=observations,
            )
        except (DataUnavailable, ValidationError, KeyError, ValueError, TypeError):
            raise APIError(
                "DATA_SERVICE_UNAVAILABLE",
                "Device data is temporarily unavailable.",
                503,
            ) from None
