from dataclasses import replace
from unittest.mock import Mock
from app.core.config import WorkerSettings
from app.providers.google_calendar.client import GoogleCalendarClient


def client(monkeypatch, **overrides):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    transport = Mock()
    settings = replace(WorkerSettings.from_env(), **overrides)
    return GoogleCalendarClient(settings, transport), transport


def page(*ids, next_page_token=None):
    body = {"items": [{"id": event_id} for event_id in ids]}
    if next_page_token:
        body["nextPageToken"] = next_page_token
    return body


def test_list_events_sends_the_documented_query(monkeypatch):
    api, transport = client(monkeypatch)
    transport.request.return_value = page("a")

    assert api.list_events(
        "primary", "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z"
    ) == [{"id": "a"}]
    url, kwargs = transport.request.call_args.args[0], transport.request.call_args.kwargs
    assert url == "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    assert kwargs["params"] == {
        "singleEvents": "true",
        "showDeleted": "true",
        "orderBy": "startTime",
        "maxResults": 250,
        "timeMin": "2026-09-01T00:00:00Z",
        "timeMax": "2026-09-08T00:00:00Z",
    }


def test_calendar_id_is_url_encoded(monkeypatch):
    api, transport = client(
        monkeypatch, calendar_api_base_url="https://example.test/calendar/v3"
    )
    transport.request.return_value = page()

    api.list_events("user@example.com", "2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z")
    assert (
        transport.request.call_args.args[0]
        == "https://example.test/calendar/v3/calendars/user%40example.com/events"
    )


def test_pagination_follows_next_page_token(monkeypatch):
    api, transport = client(monkeypatch)
    transport.request.side_effect = [
        page("a", next_page_token="p2"),
        page("b", next_page_token="p3"),
        page("c"),
    ]

    events = api.list_events(
        "primary", "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z"
    )
    assert [event["id"] for event in events] == ["a", "b", "c"]
    tokens = [
        call.kwargs["params"].get("pageToken")
        for call in transport.request.call_args_list
    ]
    assert tokens == [None, "p2", "p3"]


def test_skipped_page_keeps_collected_events(monkeypatch):
    api, transport = client(monkeypatch)
    transport.request.side_effect = [page("a", next_page_token="p2"), None]

    events = api.list_events(
        "primary", "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z"
    )
    assert [event["id"] for event in events] == ["a"]
    assert transport.request.call_count == 2


def test_pagination_stops_at_the_page_cap(monkeypatch):
    api, transport = client(monkeypatch)
    transport.request.return_value = page("a", next_page_token="more")

    events = api.list_events(
        "primary", "2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z"
    )
    assert transport.request.call_count == 50
    assert len(events) == 50
