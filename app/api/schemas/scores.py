"""Strict public experimental score responses, with explicit provenance."""

from datetime import date
from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


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


class ReadinessMetricComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    value: float | None = None
    baseline_mean: float | None = None
    baseline_sd: float | None = None
    scale: float | None = None
    z: float | None = None
    positive_term: float | None = None
    negative_term: float | None = None
    days_used: int = 0


class ReadinessBalanceComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    value: float | None = None
    z: float | None = None
    penalty_term: float | None = None
    days_used: int = 0
    decay: float | None = None


class ReadinessSleepComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    goal_minutes: float | None = None
    debt_minutes: float | None = None
    balance: float | None = None
    nights_used: int = 0


class ReadinessComponents(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    hrv_current: ReadinessMetricComponent
    rhr_current: ReadinessMetricComponent
    hrv_balance_7d: ReadinessBalanceComponent
    sleep_balance_7d: ReadinessSleepComponent


class ReadinessScoreDay(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    date: date
    score: int | None = Field(ge=1, le=100)
    source: Literal["observed_google_health", "calculated_v0.3", "insufficient"]
    confidence: Literal["observed_fact", "experimental", "experimental_partial", "insufficient"]
    observed_score: int | None = Field(default=None, ge=1, le=100)
    calculated_score: int | None = Field(default=None, ge=1, le=100)
    calculated_raw_score: float | None = Field(default=None, ge=1, le=100)
    calculation_insufficient_data: bool
    hrv_baseline_days: int
    rhr_baseline_days: int
    components: ReadinessComponents
    flags: list[str]


class ReadinessScoreResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    start: AwareDatetime
    end: AwareDatetime
    timezone: str
    model_version: Literal["readiness-emulator-v0.3"]
    days: list[ReadinessScoreDay]
    caveats: list[str]
