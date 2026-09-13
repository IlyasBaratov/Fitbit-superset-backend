"""Strict public contracts for the calendar read API (D7: HR figures are a proxy)."""

from pydantic import BaseModel, ConfigDict, AwareDatetime

Number = float | int


class EventVitals(BaseModel):
    """Heart-rate response to one event; `None` fields simply have no data behind them."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    mean_hr: Number | None
    max_hr: Number | None
    sample_count: int
    coverage_pct: Number
    hr_vs_resting_pct: Number | None
    steps: Number | None
    steps_per_minute: Number | None
    movement_confounded: bool
    pre30_mean_hr: Number | None
    post30_mean_hr: Number | None
    recovery_delta: Number | None


class CalendarEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    event_id: str
    calendar_id: str
    summary: str
    start: AwareDatetime
    end: AwareDatetime
    duration_minutes: Number
    attendees: int | None
    is_organizer: bool | None
    response_status: str
    event_type: str
    recurring_event_id: str
    vitals: EventVitals | None
    notes: list[str]


class CalendarEventsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start: AwareDatetime
    end: AwareDatetime
    timezone: str
    bucket_minutes: int
    events: list[CalendarEvent]


class InsightsPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    start: AwareDatetime
    end: AwareDatetime
    timezone: str
    days: int
    bucket_minutes: int


class DailyLoad(BaseModel):
    """One local day of meeting load, as `daily_load` counts it."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    date: str
    event_count: int
    meeting_count: int
    meeting_minutes: Number
    event_minutes: Number
    back_to_back_count: int
    first_event_hour: Number
    last_event_hour: Number


class Correlation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    r: Number | None
    n: int
    insufficient_data: bool


class Terciles(BaseModel):
    """The busiest third of days against the quietest third, for one metric."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    days: int
    top_third_mean: Number | None
    bottom_third_mean: Number | None
    top_third_meeting_minutes: Number | None
    bottom_third_meeting_minutes: Number | None
    difference: Number | None
    percent: Number | None
    insufficient_data: bool


class ShiftedCorrelation(BaseModel):
    """Sleep, HRV and resting heart rate are read the morning after the load (D7)."""

    model_config = ConfigDict(extra="forbid", strict=True)
    same_day: Correlation
    next_day: Correlation


class ShiftedTerciles(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    same_day: Terciles
    next_day: Terciles


class SeriesSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    title: str
    occurrences: int
    with_vitals: int
    mean_hr_vs_resting_pct: Number | None
    mean_recovery_delta: Number | None
    confounded_count: int


class PartOfDay(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    mean_hr_vs_resting_pct: Number | None
    n: int


class TopEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    event_id: str
    title: str
    start: AwareDatetime
    duration_minutes: Number
    attendees: int
    mean_hr: Number | None
    hr_vs_resting_pct: Number
    recovery_delta: Number | None


class CalendarInsightsResponse(BaseModel):
    """Deterministic calendar insights; every heart-rate figure is a proxy (D7)."""

    model_config = ConfigDict(extra="forbid", strict=True)
    period: InsightsPeriod
    days_with_events: int
    daily_load: list[DailyLoad]
    correlations: dict[str, ShiftedCorrelation]
    tercile_comparison: dict[str, ShiftedTerciles]
    series: list[SeriesSummary]
    time_of_day: dict[str, PartOfDay]
    top_events: list[TopEvent]
    caveats: list[str]


class CalendarStatusResponse(BaseModel):
    """The connection itself; never the token, the client secret or the person's events."""

    model_config = ConfigDict(extra="forbid", strict=True)
    connected: bool
    configured: bool
    calendar_ids: list[str]
    token_saved_at: AwareDatetime | None
    last_event_start: AwareDatetime | None
    redirect_uri: str
