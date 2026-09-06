"""Strict public health read contracts."""
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, AwareDatetime

class HealthQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    period: str | None = None

class HealthRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    timestamp: AwareDatetime
    fields: dict[str, int | float | str | bool]

class HealthSeries(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    measurement: str
    resolution: Literal["hourly", "stored"]
    rows: list[HealthRow]

class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start: AwareDatetime
    end: AwareDatetime
    timezone: str
    series: list[HealthSeries]

class DeviceObservation(HealthRow):
    measurement: Literal["Device Metadata", "DeviceBatteryLevel"]

class DevicesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    device_id: str
    provider: str
    observations: list[DeviceObservation]
