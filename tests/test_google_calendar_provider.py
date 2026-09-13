from dataclasses import replace
from unittest.mock import Mock
import logging
import pytest
import pytz
import requests
from app.core.config import WorkerSettings
from app.core.exceptions import AuthenticationError, ProviderError
from app.providers.google_calendar.provider import GoogleCalendarProvider


def provider(monkeypatch, zone="UTC", **overrides):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    client = Mock()
    client.list_events.return_value = []
    settings = replace(WorkerSettings.from_env(), **overrides)
    return (
        GoogleCalendarProvider(settings, client, pytz.timezone(zone)),
        client,
    )


def http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


def timed_event(event_id, start, end):
    return {
        "id": event_id,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
        "updated": "2026-09-01T10:00:00Z",
        "summary": "Standup",
    }


def test_window_spans_whole_local_days_across_midnight(monkeypatch):
    api, client = provider(monkeypatch, zone="America/Los_Angeles")

    api.fetch_events("2026-09-01", "2026-09-02")
    _, time_min, time_max = client.list_events.call_args.args
    assert time_min == "2026-09-01T07:00:00+00:00"
    assert time_max == "2026-09-03T07:00:00+00:00"


def test_events_are_mapped_per_calendar(monkeypatch):
    api, client = provider(
        monkeypatch, calendar_ids=("primary", "team@example.com")
    )
    client.list_events.side_effect = [
        [timed_event("a", "2026-09-01T09:00:00Z", "2026-09-01T10:00:00Z")],
        [timed_event("b", "2026-09-01T11:00:00Z", "2026-09-01T11:30:00Z")],
    ]

    points = api.fetch_events("2026-09-01", "2026-09-01")
    assert [point.measurement for point in points] == [
        "Calendar Events",
        "Calendar Events",
    ]
    assert [point.tags for point in points] == [
        {"CalendarId": "primary", "EventId": "a"},
        {"CalendarId": "team@example.com", "EventId": "b"},
    ]
    assert points[1].fields["duration_seconds"] == 1800


@pytest.mark.parametrize("failure", [http_error(403), http_error(404), ProviderError("down")])
def test_one_unreadable_calendar_does_not_block_the_next(monkeypatch, failure):
    api, client = provider(
        monkeypatch, calendar_ids=("secret@example.com", "primary")
    )
    client.list_events.side_effect = [
        failure,
        [timed_event("b", "2026-09-01T11:00:00Z", "2026-09-01T11:30:00Z")],
    ]

    points = api.fetch_events("2026-09-01", "2026-09-01")
    assert [point.tags["CalendarId"] for point in points] == ["primary"]


def test_missing_token_returns_no_points_and_logs_once(monkeypatch, caplog):
    api, client = provider(monkeypatch)
    client.list_events.side_effect = AuthenticationError("Token file not found")

    with caplog.at_level(logging.WARNING):
        assert api.fetch_events("2026-09-01", "2026-09-01") == []
        assert api.fetch_events("2026-09-02", "2026-09-02") == []
    not_connected = [
        record for record in caplog.records if "not connected" in record.message
    ]
    assert len(not_connected) == 1
    assert "Token file not found" not in caplog.text

    client.list_events.side_effect = None
    client.list_events.return_value = []
    with caplog.at_level(logging.WARNING):
        api.fetch_events("2026-09-03", "2026-09-03")
        client.list_events.side_effect = AuthenticationError("revoked")
        assert api.fetch_events("2026-09-04", "2026-09-04") == []
    assert len([r for r in caplog.records if "not connected" in r.message]) == 2


def test_close_and_refresh_use_the_calendar_transport(monkeypatch):
    api, client = provider(monkeypatch)
    client.transport.token_manager.refresh.return_value = "token"

    assert api.refresh_credentials() == "token"
    api.close()
    client.transport.close.assert_called_once()
    client.transport.token_manager.close.assert_called_once()
