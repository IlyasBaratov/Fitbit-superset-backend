"""Public experimental sleep-score response, with explicit missing values."""

from datetime import date
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict


class SleepScoreComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    minutes_asleep: float | None = None
    goal_minutes: float | None = None
    shortfall_minutes: float | None = None
    minutes: float | None = None
    count: int | None = None
    percent: float | None = None
    penalty: float | None = None
    method: str | None = None
    hr_coverage_minutes: float | None = None
    hr_sparse_minutes: float | None = None
    eligible_minutes: float | None = None
    unknown_minutes: float | None = None


class SleepScoreDay(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    date: date
    score: int | None
    raw_score: float | None
    sleep_efficiency: float | None
    insufficient_data: bool
    confidence: Literal["experimental", "experimental_approximate", "insufficient"]
    components: dict[str, SleepScoreComponent]
    flags: list[str]


class SleepScoreResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    start: AwareDatetime
    end: AwareDatetime
    timezone: str
    model_version: Literal["sleep-score-emulator-v0.1"]
    days: list[SleepScoreDay]
    caveats: list[str]
