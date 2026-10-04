"""Public contract and read-path tests for experimental sleep scores."""

from datetime import datetime, timezone
from unittest.mock import Mock
from fastapi.testclient import TestClient
from app.api.main import create_app
from app.core.config import Settings


def test_sleep_score_route_auth_bounds_missing_sleep_and_no_gemini():
    cfg = Settings(api_token="s" * 40, gemini_key="test", model="test")
    db, gemini = Mock(), Mock()
    db.query.return_value = []
    clock = lambda: datetime(2026, 10, 4, 18, tzinfo=timezone.utc)
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        path = "/api/health/sleep-score?period=2d"
        assert client.get(path).status_code == 401
        headers = {"Authorization": "Bearer " + cfg.api_token}
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["model_version"] == "sleep-score-emulator-v0.1"
        assert [item["date"] for item in body["days"]] == ["2026-10-03", "2026-10-04"]
        assert all(item["score"] is None and item["insufficient_data"] for item in body["days"])
        assert all("missing_main_sleep_session" in item["flags"] for item in body["days"])
        assert client.get(path + "&UserId=other", headers=headers).status_code == 422
        assert client.get("/api/health/sleep-score?period=91d", headers=headers).status_code == 422
    db.query_raw_sleep_heart_rate.assert_not_called()
    gemini.generate.assert_not_called()
