from datetime import datetime, timezone
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.main import create_app
from app.models import AIResponse, AnalysisRequest
from app.services.analysis_service import AnalysisService
from app.services.influx_service import DataUnavailable
from app.services.gemini_service import GeminiUnavailable
from app.services.ai_response_validator import InvalidAIOutput

@pytest.fixture
def setup():
    settings = Settings(api_token="x"*40, gemini_key="k", model="m", timezone="UTC")
    db, ai = Mock(), Mock()
    db.fetch.return_value = {
        "Sleep Summary": [{"time": "2026-09-05T00:00:00Z", "minutesAsleep": 400}],
        "Total Steps": [{"time": "2026-09-05T00:00:00Z", "value": 1000}],
        "RestingHR": [{"time": "2026-09-05T00:00:00Z", "value": 60}],
        "Activity Records": [{"time": "2026-09-05T00:00:00Z", "duration": 1000}],
    }
    ai.generate.return_value = AIResponse(summary="Summary", insights=[], suggestions=[], warnings=[], data_gaps=[])
    ai.check.return_value = {"status": "ok", "model": "m"}
    clock = lambda: datetime(2026,9,5,12,tzinfo=timezone.utc)
    app = create_app(settings, db, ai, clock)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + settings.api_token
        yield client, db, ai, app

@pytest.mark.parametrize("endpoint", ["analyze", "sleep", "activity", "workouts", "recovery", "ask"])
def test_endpoints(setup, endpoint):
    client, db, ai, app = setup
    body = {"period": "7d"}
    if endpoint == "ask": body["question"] = "How active have I been?"
    response = client.post("/api/ai/"+endpoint, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["summary"] == "Summary"
    assert db.fetch.call_args.args[1].tzinfo is not None
    assert ai.generate.call_count == 1

@pytest.mark.parametrize("period", ["0d", "91d", "7", "-1d", "all", "100000000d"])
def test_invalid_period_skips_services(setup, period):
    client, db, ai, app = setup
    response = client.post("/api/ai/analyze", json={"period": period})
    assert response.status_code == 422
    assert response.json()["error"] == "INVALID_ANALYSIS_PERIOD"
    db.fetch.assert_not_called()

def test_no_data_skips_gemini(setup):
    client, db, ai, app = setup
    db.fetch.return_value = {}
    response = client.post("/api/ai/sleep", json={})
    assert response.json()["error"] == "INSUFFICIENT_DATA"
    ai.generate.assert_not_called()

@pytest.mark.parametrize("failure,code", [(DataUnavailable(), "DATA_SERVICE_UNAVAILABLE"), (GeminiUnavailable(), "AI_SERVICE_UNAVAILABLE"), (InvalidAIOutput(), "INVALID_AI_OUTPUT")])
def test_controlled_failures(setup, failure, code):
    client, db, ai, app = setup
    if isinstance(failure, DataUnavailable): db.fetch.side_effect = failure
    else: ai.generate.side_effect = failure
    assert client.post("/api/ai/analyze", json={}).json()["error"] == code

def test_cache_hits_and_invalidates_on_data_change(setup):
    client, db, ai, app = setup
    for _ in range(2): assert client.post("/api/ai/analyze", json={}).status_code == 200
    assert ai.generate.call_count == 1
    db.fetch.return_value["Total Steps"][0]["value"] = 2000
    assert client.post("/api/ai/analyze", json={}).status_code == 200
    assert ai.generate.call_count == 2

def test_expired_cache_and_question_isolation(setup):
    client, db, ai, app = setup
    app.state.settings.cache_seconds = -1
    for _ in range(2): client.post("/api/ai/analyze", json={})
    assert ai.generate.call_count == 2
    client.post("/api/ai/ask", json={"question": "How many steps?"})
    client.post("/api/ai/ask", json={"question": "Am I walking more?"})
    assert ai.generate.call_count == 4

def test_api_authentication_and_connection_check(setup):
    client, db, ai, app = setup
    assert client.post("/api/ai/test").status_code == 200
    client.headers.pop("Authorization")
    assert client.post("/api/ai/analyze", json={}).status_code == 401
    assert client.post("/api/ai/test").status_code == 401
    db.fetch.assert_not_called()

def test_user_isolation_and_busy_limit(setup):
    client, db, ai, app = setup
    from app.errors import APIError
    with pytest.raises(APIError) as err:
        app.state.analysis.run(AnalysisRequest(), "analyze", "another-user")
    assert err.value.status == 401
    app.state.analysis.lock.acquire()
    try:
        assert client.post("/api/ai/analyze", json={}).status_code == 429
    finally:
        app.state.analysis.lock.release()
    db.fetch.assert_not_called()


def test_provider_timeout_error_is_exposed(setup):
    client, db, ai, app = setup
    ai.generate.side_effect = GeminiUnavailable("Gemini did not respond in time. Please retry shortly.",
        code="AI_PROVIDER_TIMEOUT", status=503, transient=True)
    response = client.post("/api/ai/analyze", json={})
    assert response.status_code == 503
    assert response.json()["error"] == "AI_PROVIDER_TIMEOUT"
