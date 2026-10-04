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


def test_sleep_score_route_uses_derived_components_and_flags_missing_hr():
    cfg = Settings(api_token="s" * 40, gemini_key="test", model="test")
    db, gemini = Mock(), Mock()
    start = "2026-10-04T08:50:00Z"
    summary = {"time": start, "startTime": start, "endTime": "2026-10-04T16:52:00Z",
               "SleepSessionId": "oct4", "isMainSleep": "true", "isProcessed": True,
               "minutesAsleep": 437, "minutesInBed": 482,
               "shortAwakeningSeconds": 960, "shortAwakeningCount": 1}
    stages = [
        {"time": "2026-10-04T08:50:00Z", "stageName": "awake", "duration_seconds": 600},
        {"time": "2026-10-04T09:00:00Z", "stageName": "light", "duration_seconds": 960},
        {"time": "2026-10-04T09:16:00Z", "stageName": "deep", "duration_seconds": 6000},
        {"time": "2026-10-04T10:56:00Z", "stageName": "awake", "duration_seconds": 1980},
        {"time": "2026-10-04T11:29:00Z", "stageName": "light", "duration_seconds": 6000},
    ]
    stages = [{**row, "SleepSessionId": "oct4"} for row in stages]
    awakening = {"time": "2026-10-04T09:00:00Z", "endTime": "2026-10-04T09:16:00Z",
                 "SleepSessionId": "oct4", "duration_seconds": 960}
    data = {"Sleep Summary": [summary], "Sleep Levels": stages,
            "Sleep Short Awakenings": [awakening]}
    db.query.side_effect = lambda measurement, *_: data.get(measurement, [])
    db.query_raw_sleep_heart_rate.return_value = []
    clock = lambda: datetime(2026, 10, 4, 18, tzinfo=timezone.utc)
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        headers = {"Authorization": "Bearer " + cfg.api_token}
        day = client.get("/api/health/sleep-score?period=1d", headers=headers).json()["days"][0]
        assert day["score"] == 78 and day["raw_score"] == 78.184
        assert day["sleep_efficiency"] == 100 * 437 / 482
        assert day["components"]["restlessness"]["minutes"] == 16
        assert day["components"]["interruptions"]["minutes"] == 33
        assert day["components"]["full_awakenings"]["count"] == 1
        assert day["components"]["sound_sleep"]["minutes"] is None
        assert "high_resolution_hr_unavailable" in day["flags"]
        assert "tts_approximation_no_hr" in day["flags"]
        db.query_raw_sleep_heart_rate.return_value = [
            {"time": "2026-10-04T09:00:01Z", "value": 123456},
        ]
        response = client.get("/api/health/sleep-score?period=1d", headers=headers)
        assert response.status_code == 200
        assert "123456" not in response.text
        assert "tts_stable_light_unvalidated" in response.json()["days"][0]["flags"]
        data["Sleep Short Awakenings"] = []
        summary.pop("shortAwakeningSeconds")
        summary.pop("shortAwakeningCount")
        missing = client.get("/api/health/sleep-score?period=1d", headers=headers).json()["days"][0]
        assert missing["score"] is None and missing["insufficient_data"] is True
        assert "missing_restlessness" in missing["flags"]
    gemini.generate.assert_not_called()
