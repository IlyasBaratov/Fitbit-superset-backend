"""The stored `Calendar Events` contract, and the event shapes Google actually returns."""
from pathlib import Path
import json
import pytz
from app.domain.measurements import FIELD_TYPES
from app.domain.normalization import build_common_tags
from app.providers.google_calendar.mapper import SUMMARY_MAX_LENGTH, map_events
from app.storage.influx.schema import prepare_points

ZONE = pytz.timezone("America/Los_Angeles")
CALENDAR_TAGS = build_common_tags(
    "u", "google_calendar", "Google Calendar", "google_calendar"
)


def fixture():
    path = Path(__file__).parent / "fixtures" / "google_calendar_contract.json"
    return json.loads(path.read_text())


def mapped(items, calendar_id="primary"):
    return map_events(items, calendar_id, ZONE)


def fields_of(items, calendar_id="primary"):
    return mapped(items, calendar_id)[0].fields


def test_stored_calendar_points_match_the_recorded_contract():
    contract = fixture()
    points = map_events(
        contract["items"], contract["calendar_id"], pytz.timezone(contract["timezone"])
    )
    actual = prepare_points(
        [point.as_record() for point in points], CALENDAR_TAGS, contract["timezone"]
    )
    canonical = lambda rows: sorted(json.dumps(row, sort_keys=True) for row in rows)
    assert canonical(actual) == canonical(contract["expected"])


def test_every_mapped_field_is_declared_in_the_schema():
    contract = fixture()
    declared = set(FIELD_TYPES["Calendar Events"])
    for point in map_events(contract["items"], "primary", ZONE):
        assert set(point.fields) <= declared


def test_timed_event_is_stamped_at_its_start_in_utc():
    point = mapped(
        [
            {
                "id": "e1",
                "start": {"dateTime": "2026-09-01T09:00:00-07:00"},
                "end": {"dateTime": "2026-09-01T10:30:00-07:00"},
            }
        ]
    )[0]
    assert point.timestamp == "2026-09-01T16:00:00+00:00"
    assert point.tags == {"CalendarId": "primary", "EventId": "e1"}
    assert point.fields["endTime"] == "2026-09-01T17:30:00+00:00"
    assert point.fields["duration_seconds"] == 5400
    assert point.fields["isAllDay"] is False


def test_all_day_event_uses_local_midnight_and_whole_days():
    point = mapped(
        [{"id": "e2", "start": {"date": "2026-09-03"}, "end": {"date": "2026-09-05"}}]
    )[0]
    assert point.timestamp == "2026-09-03T07:00:00+00:00"
    assert point.fields["duration_seconds"] == 172800
    assert point.fields["isAllDay"] is True


def test_all_day_duration_absorbs_a_daylight_saving_change():
    point = mapped(
        [{"id": "e3", "start": {"date": "2026-11-01"}, "end": {"date": "2026-11-02"}}]
    )[0]
    assert point.timestamp == "2026-11-01T07:00:00+00:00"
    assert point.fields["duration_seconds"] == 90000


def test_cancelled_instance_falls_back_to_its_original_start():
    point = mapped(
        [
            {
                "id": "e4",
                "status": "cancelled",
                "recurringEventId": "series",
                "originalStartTime": {"dateTime": "2026-09-02T09:00:00-07:00"},
            }
        ]
    )[0]
    assert point.timestamp == "2026-09-02T16:00:00+00:00"
    assert point.fields["status"] == "cancelled"
    assert point.fields["recurringEventId"] == "series"
    assert "endTime" not in point.fields
    assert "duration_seconds" not in point.fields


def test_google_defaults_are_restored_for_omitted_keys():
    fields = fields_of([{"id": "e5", "start": {"dateTime": "2026-09-01T09:00:00Z"}}])
    assert fields["status"] == "confirmed"
    assert fields["eventType"] == "default"
    assert fields["transparency"] == "opaque"
    assert fields["attendees"] == 0
    assert fields["isOrganizer"] is False


def test_attendee_count_excludes_self_and_keeps_only_the_own_response():
    fields = fields_of(
        [
            {
                "id": "e6",
                "start": {"dateTime": "2026-09-01T09:00:00Z"},
                "attendees": [
                    {"email": "one@example.com", "responseStatus": "accepted"},
                    {"email": "two@example.com", "responseStatus": "declined"},
                    {
                        "email": "me@example.com",
                        "self": True,
                        "responseStatus": "tentative",
                    },
                ],
                "organizer": {"email": "one@example.com"},
            }
        ]
    )
    assert fields["attendees"] == 2
    assert fields["responseStatus"] == "tentative"
    assert fields["isOrganizer"] is False
    assert "example.com" not in json.dumps(fields)


def test_summary_is_stripped_of_control_characters_and_truncated():
    fields = fields_of(
        [
            {
                "id": "e7",
                "summary": "Quarterly\treview\nwith\r\nnotes " + "x" * 300,
                "start": {"dateTime": "2026-09-01T09:00:00Z"},
            }
        ]
    )
    assert fields["summary"].startswith("Quarterly review with notes x")
    assert len(fields["summary"]) == SUMMARY_MAX_LENGTH


def test_events_without_an_identifier_or_any_start_are_skipped():
    assert (
        mapped(
            [
                {"start": {"dateTime": "2026-09-01T09:00:00Z"}},
                {"id": "  ", "start": {"dateTime": "2026-09-01T09:00:00Z"}},
                {"id": "e8"},
                {"id": "e9", "start": {}},
                {"id": "e10", "start": {"dateTime": "not-a-timestamp"}},
                "not-an-event",
            ]
        )
        == []
    )


def test_calendar_id_is_tagged_per_calendar():
    points = mapped(
        [{"id": "e11", "start": {"dateTime": "2026-09-01T09:00:00Z"}}],
        calendar_id="team@example.com",
    )
    assert points[0].tags["CalendarId"] == "team@example.com"
