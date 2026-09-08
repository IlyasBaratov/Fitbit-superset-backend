"""Connect and callback endpoints for the read-only calendar scope (D13)."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import urllib.parse
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from app.api.calendar_connect import (
    MAX_PENDING_STATES,
    STATE_TTL_SECONDS,
    CalendarConnectService,
)
from app.api.main import create_app
from app.core.config import Settings
from app.errors import APIError

SECRET = "calendar-client-secret"
SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"


@pytest.fixture
def setup(tmp_path):
    cfg = Settings(
        api_token="t" * 40,
        gemini_key="test",
        model="test",
        calendar_client_id="calendar-client-id",
        calendar_client_secret=SECRET,
        calendar_token_file_path=str(tmp_path / "tokens" / "google_calendar.token"),
    )
    db, gemini = Mock(), Mock()
    db.query.return_value = []
    clock = lambda: datetime(2026, 3, 9, 12, tzinfo=timezone.utc)
    return cfg, db, gemini, clock


def _exchange_session(payload, status=200):
    session = Mock()
    session.post.return_value.status_code = status
    session.post.return_value.json.return_value = payload
    return session


def _state_of(begun):
    query = urllib.parse.urlparse(begun["authorization_url"]).query
    return urllib.parse.parse_qs(query)["state"][0]


def _begin(client, cfg):
    response = client.get(
        "/api/calendar/connect", headers={"Authorization": "Bearer " + cfg.api_token}
    )
    assert response.status_code == 200
    return response


def test_connect_requires_a_bearer_token_and_offers_read_only_access(setup):
    cfg, db, gemini, clock = setup
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        assert client.get("/api/calendar/connect").status_code == 401
        response = _begin(client, cfg)
        body = response.json()
        assert body["expires_in"] == STATE_TTL_SECONDS
        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(body["authorization_url"]).query
        )
        assert query["scope"] == [SCOPE]
        assert query["redirect_uri"] == [cfg.calendar_redirect_uri]
        assert query["client_id"] == ["calendar-client-id"]
        assert query["access_type"] == ["offline"]
        assert len(query["state"][0]) >= 32
        assert _state_of(_begin(client, cfg).json()) != query["state"][0]
        assert SECRET not in response.text


def test_callback_stores_the_token_without_echoing_any_of_it(setup):
    cfg, db, gemini, clock = setup
    session = _exchange_session(
        {
            "access_token": "calendar-access",
            "refresh_token": "calendar-refresh",
            "expires_in": 3599,
        }
    )
    app = create_app(cfg, db, gemini, clock)
    with TestClient(app) as client:
        app.state.calendar_connect.session = session
        state = _state_of(_begin(client, cfg).json())
        response = client.get(f"/api/calendar/callback?state={state}&code=granted")
        assert response.status_code == 200
        assert "connected" in response.text
        for phrase in ("calendar-access", "calendar-refresh", "granted", SECRET):
            assert phrase not in response.text
    token_file = Path(cfg.calendar_token_file_path)
    saved = json.loads(token_file.read_text(encoding="utf-8"))
    assert saved["provider"] == "google_calendar"
    assert saved["refresh_token"] == "calendar-refresh"
    assert oct(token_file.stat().st_mode)[-3:] == "600"
    sent = session.post.call_args
    assert sent.args[0] == "https://oauth2.googleapis.com/token"
    assert sent.kwargs["data"]["code"] == "granted"
    assert sent.kwargs["data"]["redirect_uri"] == cfg.calendar_redirect_uri


def test_callback_rejects_unknown_denied_and_replayed_authorizations(setup):
    cfg, db, gemini, clock = setup
    session = _exchange_session({"access_token": "a", "refresh_token": "r"})
    app = create_app(cfg, db, gemini, clock)
    with TestClient(app) as client:
        app.state.calendar_connect.session = session
        state = _state_of(_begin(client, cfg).json())
        for query in (
            "state=unknown&code=granted",
            "code=granted",
            f"state={state}",
            f"state={state}&error=access_denied",
        ):
            result = client.get("/api/calendar/callback?" + query)
            assert result.status_code == 400
            assert result.json()["error"] == "CALENDAR_CONNECT_REJECTED"
            assert "access_denied" not in result.text
        session.post.assert_not_called()
        assert client.get(f"/api/calendar/callback?state={state}&code=granted").status_code == 200
        replayed = client.get(f"/api/calendar/callback?state={state}&code=granted")
        assert replayed.status_code == 400
        assert session.post.call_count == 1


def test_a_failed_exchange_reports_nothing_and_writes_nothing(setup):
    cfg, db, gemini, clock = setup
    session = _exchange_session({"error_description": SECRET}, status=400)
    app = create_app(cfg, db, gemini, clock)
    with TestClient(app) as client:
        app.state.calendar_connect.session = session
        state = _state_of(_begin(client, cfg).json())
        response = client.get(f"/api/calendar/callback?state={state}&code=granted")
        assert response.status_code == 400
        assert response.json()["error"] == "CALENDAR_CONNECT_REJECTED"
        assert SECRET not in response.text
    assert not Path(cfg.calendar_token_file_path).exists()


def test_an_unconfigured_server_answers_503_on_both_endpoints(setup):
    cfg, db, gemini, clock = setup
    cfg = replace(cfg, calendar_client_id="", calendar_client_secret="")
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        response = client.get(
            "/api/calendar/connect",
            headers={"Authorization": "Bearer " + cfg.api_token},
        )
        assert response.status_code == 503
        assert response.json()["error"] == "CALENDAR_NOT_CONFIGURED"
        callback = client.get("/api/calendar/callback?state=x&code=y")
        assert callback.status_code == 503
        assert callback.json()["error"] == "CALENDAR_NOT_CONFIGURED"


def test_pending_states_expire_and_the_oldest_is_evicted(setup):
    cfg, *_ = setup
    now = [datetime(2026, 3, 9, 12, tzinfo=timezone.utc)]
    session = _exchange_session({"access_token": "a", "refresh_token": "r"})
    service = CalendarConnectService(cfg, session=session, clock=lambda: now[0])
    expiring = _state_of(service.begin())
    now[0] += timedelta(seconds=STATE_TTL_SECONDS + 1)
    with pytest.raises(APIError) as error:
        service.complete(expiring, "granted")
    assert (error.value.code, error.value.status) == ("CALENDAR_CONNECT_REJECTED", 400)
    states = [_state_of(service.begin()) for _ in range(MAX_PENDING_STATES + 1)]
    with pytest.raises(APIError):
        service.complete(states[0], "granted")
    service.complete(states[-1], "granted")
    assert session.post.call_count == 1
