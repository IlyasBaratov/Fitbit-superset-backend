"""Authenticated Readiness API contract and factual observation tests."""

from datetime import datetime, timezone
from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings


def test_observed_fact_is_authoritative_without_model_inputs():
    cfg = Settings(api_token="r" * 40, gemini_key="test", model="test")
    db, gemini = Mock(), Mock()
    db.query.return_value = []
    clock = lambda: datetime(2026, 10, 8, 18, tzinfo=timezone.utc)
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        path = "/api/health/readiness-score?period=1d"
        assert client.get(path).status_code == 401
        response = client.get(path, headers={"Authorization": "Bearer " + cfg.api_token})
        assert response.status_code == 200
        body = response.json()
        assert body["model_version"] == "readiness-emulator-v0.3"
        assert body["days"][0]["date"] == "2026-10-08"
        assert body["days"][0]["score"] == body["days"][0]["observed_score"] == 53
        assert body["days"][0]["source"] == "observed_google_health"
        assert body["days"][0]["confidence"] == "observed_fact"
        assert body["days"][0]["calculated_score"] is None
        assert body["days"][0]["calculation_insufficient_data"] is True
        assert {call.args[0] for call in db.query.call_args_list} == {
            "HRV", "RestingHR", "Sleep Summary"
        }
        assert db.query.call_count == 3
        assert client.get(path + "&user_id=other", headers={"Authorization": "Bearer " + cfg.api_token}).status_code == 422
    gemini.generate.assert_not_called()


def test_openapi_contains_readiness_sibling_contract():
    schema = create_app().openapi()
    route = schema["paths"]["/api/health/readiness-score"]["get"]
    assert route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ReadinessScoreResponse"
    )
    assert "422" in route["responses"]
    assert "/api/health/sleep-score" in schema["paths"]
