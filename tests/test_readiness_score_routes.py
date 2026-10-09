"""Authenticated Readiness API contract and factual observation tests."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
from unittest.mock import Mock

import pytest
import pytz
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.main import create_app
from app.api.readiness_score_service import load_observed_readiness
from app.api.schemas.scores import ReadinessMetricComponent, ReadinessScoreDay
from app.core.config import Settings
from app.core.exceptions import DataUnavailable, QueryLimitExceeded
from app.scores.sleep import aware_utc, normalize_sleep_days


SNAPSHOT = Path(__file__).parent / "fixtures" / "readiness_real_health_snapshot.json"


def factual_rows():
    document = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert document["source"] == "stored_health_influxdb_owner_data"
    assert document["timezone"] == "America/Los_Angeles"
    assert "readiness" not in document["measurements"]
    return document["measurements"]


def request_on(local_day: date, period="1d", data=None, *, error=None):
    cfg = Settings(api_token="r" * 40, gemini_key="test", model="test")
    db, gemini = Mock(), Mock()
    rows = factual_rows() if data is None else data

    def query(measurement, start, end):
        if error is not None:
            raise error
        return [row for row in rows[measurement] if start <= aware_utc(row["time"]) < end]

    db.query.side_effect = query
    clock = lambda: datetime.combine(local_day, datetime.min.time(), timezone.utc).replace(hour=19)
    with TestClient(create_app(cfg, db, gemini, clock)) as client:
        response = client.get(
            "/api/health/readiness-score?period=" + period,
            headers={"Authorization": "Bearer " + cfg.api_token},
        )
    return response, db, gemini


def without_dates(data, measurement, excluded, *, sleep=False):
    from pytz import timezone as pytz_timezone

    zone = pytz_timezone("America/Los_Angeles")
    copy = {name: list(rows) for name, rows in data.items()}
    key = "endTime" if sleep else "time"
    copy[measurement] = [
        row for row in copy[measurement]
        if aware_utc(row[key]).astimezone(zone).date() not in excluded
    ]
    return copy


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
    assert "score" in schema["components"]["schemas"]["ReadinessScoreDay"]["required"]


def test_real_observations_are_exact_ordered_and_model_estimates_remain_separate():
    response, db, gemini = request_on(date(2026, 10, 8), "7d")
    assert response.status_code == 200
    body = response.json()
    expected = load_observed_readiness()
    days = body["days"]
    assert [row["date"] for row in days] == [
        (date(2026, 10, 2) + timedelta(days=i)).isoformat() for i in range(7)
    ]
    assert [(row["score"], row["observed_score"]) for row in days] == [
        (expected[date.fromisoformat(row["date"])], expected[date.fromisoformat(row["date"])])
        for row in days
    ]
    assert all(row["source"] == "observed_google_health" for row in days)
    assert all(row["confidence"] == "observed_fact" for row in days)
    assert days[-1]["calculated_score"] == 50
    assert days[-1]["calculated_score"] != days[-1]["score"]
    assert days[-1]["calculation_insufficient_data"] is False
    assert [call.args[0] for call in db.query.call_args_list] == [
        "HRV", "RestingHR", "Sleep Summary"
    ]
    assert all(call.args[1] == datetime(2026, 9, 2, 7, tzinfo=timezone.utc)
               for call in db.query.call_args_list)
    gemini.generate.assert_not_called()


def test_versioned_observation_file_contains_exact_owner_facts():
    assert load_observed_readiness() == {
        date(2026, 9, 27): 67, date(2026, 9, 28): 56,
        date(2026, 9, 29): 65, date(2026, 9, 30): 62,
        date(2026, 10, 1): 52, date(2026, 10, 2): 61,
        date(2026, 10, 3): 15, date(2026, 10, 4): 22,
        date(2026, 10, 5): 25, date(2026, 10, 6): 13,
        date(2026, 10, 7): 65, date(2026, 10, 8): 53,
    }


@pytest.mark.parametrize("period", ["0d", "91d", "1w"])
def test_invalid_period_follows_existing_422_contract(period):
    response, _, _ = request_on(date(2026, 10, 8), period)
    assert response.status_code == 422
    assert response.json()["error"] == "INVALID_HEALTH_PERIOD"


def test_unobserved_real_day_is_calculated_and_reconstructible():
    response, _, _ = request_on(date(2026, 9, 14))
    assert response.status_code == 200
    day = response.json()["days"][0]
    assert day["score"] == day["calculated_score"] == 68
    assert day["observed_score"] is None
    assert day["source"] == "calculated_v0.3"
    assert day["confidence"] == "experimental"
    assert day["calculation_insufficient_data"] is False
    components = day["components"]
    h, r, balance, sleep = (
        components["hrv_current"], components["rhr_current"],
        components["hrv_balance_7d"], components["sleep_balance_7d"],
    )
    raw = min(100.0, max(1.0,
        53.81 + 16.83 * h["positive_term"] - 18.57 * h["negative_term"]
        + 9.85 * r["positive_term"] - 38.21 * r["negative_term"]
        - 10.24 * balance["penalty_term"] + 0.05 * sleep["balance"]
    ))
    assert day["calculated_raw_score"] == pytest.approx(raw)
    assert day["calculated_score"] == math.floor(raw + 0.5)


def test_empty_database_and_real_september_30_gap():
    empty = {name: [] for name in factual_rows()}
    response, _, _ = request_on(date(2026, 9, 22), "7d", empty)
    assert response.status_code == 200
    assert len(response.json()["days"]) == 7
    assert all(row["score"] is None and row["source"] == "insufficient"
               and row["calculation_insufficient_data"] for row in response.json()["days"])
    response, _, _ = request_on(date(2026, 9, 30))
    day = response.json()["days"][0]
    assert (day["score"], day["observed_score"], day["calculated_score"]) == (62, 62, None)
    assert day["source"] == "observed_google_health"


@pytest.mark.parametrize("measurement,flag", [
    ("HRV", "missing_current_hrv"), ("RestingHR", "missing_current_rhr")
])
def test_missing_current_measurement_does_not_forward_fill(measurement, flag):
    data = without_dates(factual_rows(), measurement, {date(2026, 9, 14)})
    response, _, _ = request_on(date(2026, 9, 14), data=data)
    day = response.json()["days"][0]
    assert day["score"] is None and day["calculated_score"] is None
    assert day["source"] == "insufficient"
    assert flag in day["flags"]


def test_thirteen_baseline_dates_fail_and_fourteen_cross_threshold():
    data = factual_rows()
    zone = pytz.timezone("America/Los_Angeles")
    target = date(2026, 9, 14)
    window_start = target - timedelta(days=30)
    prior = sorted({
        aware_utc(row["time"]).astimezone(zone).date()
        for row in data["HRV"] if window_start <= aware_utc(row["time"]).astimezone(zone).date() < target
    } & {
        aware_utc(row["time"]).astimezone(zone).date()
        for row in data["RestingHR"] if window_start <= aware_utc(row["time"]).astimezone(zone).date() < target
    })
    for count in (13, 14):
        limited = data
        kept = set(prior[-count:])
        for measurement in ("HRV", "RestingHR"):
            all_prior = {
                aware_utc(row["time"]).astimezone(zone).date()
                for row in data[measurement]
                if window_start <= aware_utc(row["time"]).astimezone(zone).date() < target
            }
            excluded = all_prior - kept
            limited = without_dates(limited, measurement, excluded)
        response, _, _ = request_on(date(2026, 9, 14), data=limited)
        day = response.json()["days"][0]
        assert day["hrv_baseline_days"] == day["rhr_baseline_days"] == count
        assert (day["calculated_score"] is not None) == (count == 14)
        if count == 13:
            assert {"insufficient_hrv_baseline", "insufficient_rhr_baseline"} <= set(day["flags"])


def test_partial_and_insufficient_hrv_balance_from_factual_rows():
    for excluded, count, partial in (
        ({date(2026, 9, 10)}, 6, True),
        ({date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10)}, 4, False),
    ):
        data = without_dates(factual_rows(), "HRV", excluded)
        response, _, _ = request_on(date(2026, 9, 14), data=data)
        day = response.json()["days"][0]
        assert day["components"]["hrv_balance_7d"]["days_used"] == count
        if partial:
            assert day["score"] is not None
            assert day["confidence"] == "experimental_partial"
            assert "partial_hrv_balance_window" in day["flags"]
            zone = pytz.timezone("America/Los_Angeles")
            dated = {
                aware_utc(row["time"]).astimezone(zone).date(): float(row["dailyRmssd"])
                for row in data["HRV"]
            }
            expected = sum(
                (0.8 ** offset) * dated[date(2026, 9, 14) - timedelta(days=offset)]
                for offset in (0, 1, 2, 3, 5, 6)
            ) / sum(0.8 ** offset for offset in (0, 1, 2, 3, 5, 6))
            assert day["components"]["hrv_balance_7d"]["value"] == pytest.approx(expected)
        else:
            assert day["score"] is None
            assert "insufficient_hrv_balance_window" in day["flags"]


def test_partial_sleep_scales_debt_and_four_nights_are_insufficient():
    original, _, _ = request_on(date(2026, 9, 14))
    original_debt = original.json()["days"][0]["components"]["sleep_balance_7d"]["debt_minutes"]
    data = without_dates(factual_rows(), "Sleep Summary", {date(2026, 9, 10)}, sleep=True)
    response, _, _ = request_on(date(2026, 9, 14), data=data)
    day = response.json()["days"][0]
    component = day["components"]["sleep_balance_7d"]
    selected = normalize_sleep_days(data["Sleep Summary"], [], [], "America/Los_Angeles", 420)
    expected = sum(max(0, 420 - selected[date(2026, 9, 14) - timedelta(days=i)].session.minutes_asleep)
                   for i in range(7) if i != 4) * 7 / 6
    assert component["nights_used"] == 6
    assert component["debt_minutes"] == pytest.approx(expected)
    assert component["debt_minutes"] != original_debt
    assert day["confidence"] == "experimental_partial"
    assert "partial_sleep_window" in day["flags"]
    data = without_dates(factual_rows(), "Sleep Summary", {
        date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 10)
    }, sleep=True)
    response, _, _ = request_on(date(2026, 9, 14), data=data)
    day = response.json()["days"][0]
    assert day["score"] is None
    assert day["components"]["sleep_balance_7d"]["nights_used"] == 4
    assert "insufficient_sleep_window" in day["flags"]


def test_multiple_real_main_sleep_sessions_select_longest_processed():
    data = factual_rows()
    selected = normalize_sleep_days(data["Sleep Summary"], [], [], "America/Los_Angeles", 420)
    assert selected[date(2026, 10, 7)].session.minutes_asleep == 482
    assert selected[date(2026, 10, 8)].session.minutes_asleep == 400
    response, _, _ = request_on(date(2026, 10, 8))
    day = response.json()["days"][0]
    debt = sum(max(0, 420 - selected[date(2026, 10, 8) - timedelta(days=i)].session.minutes_asleep)
               for i in range(7))
    assert day["components"]["sleep_balance_7d"]["debt_minutes"] == debt
    assert day["components"]["sleep_balance_7d"]["nights_used"] == 7


@pytest.mark.parametrize("error,status,code", [
    (QueryLimitExceeded("private query detail"), 422, "HEALTH_QUERY_TOO_LARGE"),
    (DataUnavailable("private data detail"), 503, "DATA_SERVICE_UNAVAILABLE"),
])
def test_repository_errors_are_translated_without_leaks(error, status, code):
    response, _, _ = request_on(date(2026, 9, 14), error=error)
    assert response.status_code == status
    assert response.json()["error"] == code
    assert "private" not in response.text


def test_invalid_stored_timestamp_is_503_and_schema_rejects_nonfinite():
    data = factual_rows()
    data["HRV"] = [{**data["HRV"][0], "time": "invalid timestamp"}, *data["HRV"]]
    response, _, _ = request_on(date(2026, 9, 14), data=data)
    assert response.status_code == 503
    response, _, _ = request_on(date(2026, 9, 14))
    day = response.json()["days"][0]
    with pytest.raises(ValidationError):
        ReadinessScoreDay(**{**day, "date": date.fromisoformat(day["date"]),
                             "calculated_raw_score": float("nan")})
    with pytest.raises(ValidationError):
        ReadinessMetricComponent(value=float("inf"))


def test_sd_floor_flags_pass_through_response(monkeypatch):
    import app.api.readiness_score_service as service_module

    original = service_module.readiness_v03

    def with_floor_flag(*args):
        result = original(*args)
        return replace(result, flags=(*result.flags, "hrv_sd_floor_applied"))

    monkeypatch.setattr(service_module, "readiness_v03", with_floor_flag)
    response, _, _ = request_on(date(2026, 9, 14))
    assert response.status_code == 200
    assert "hrv_sd_floor_applied" in response.json()["days"][0]["flags"]
