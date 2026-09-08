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


class CalendarStatusResponse(BaseModel):
    """The connection itself; never the token, the client secret or the person's events."""

    model_config = ConfigDict(extra="forbid", strict=True)
    connected: bool
    configured: bool
    calendar_ids: list[str]
    token_saved_at: AwareDatetime | None
    last_event_start: AwareDatetime | None
    redirect_uri: str
