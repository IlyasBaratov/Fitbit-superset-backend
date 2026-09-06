"""Inclusive date ranges preserving existing provider-window overlap."""

from datetime import date, timedelta
from app.core.exceptions import ConfigurationError


def validate_range(start, end):
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except (ValueError, TypeError):
        raise ConfigurationError(
            "Dates must be supplied in YYYY-MM-DD format"
        ) from None
    if first > last:
        raise ConfigurationError("End date must not precede start date")
    return first, last


def iter_days(start, end):
    current, last = validate_range(start, end)
    while current <= last:
        yield current.isoformat()
        current += timedelta(days=1)


def iter_windows(start, end, gap):
    if gap <= 0:
        raise ValueError("Date-window gap must be positive")
    current, last = validate_range(start, end)
    while current <= last:
        yield current.isoformat(), min(current + timedelta(days=gap), last).isoformat()
        current += timedelta(days=gap)
