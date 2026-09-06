from dataclasses import replace
from unittest.mock import Mock
import pytz
import requests
from app.core.config import WorkerSettings
from app.providers.google_health.client import GoogleHealthClient


def client(monkeypatch):
    monkeypatch.setattr("app.core.config.load_dotenv", lambda: None)
    transport = Mock()
    return GoogleHealthClient(replace(WorkerSettings.from_env(), health_api_provider="google"), transport, pytz.timezone("America/Los_Angeles")), transport


def point(timestamp):
    return {"heartRate": {"sampleTime": {"physicalTime": timestamp}, "beatsPerMinute": 60}}


def test_pagination_and_dst_filter(monkeypatch):
    api, transport = client(monkeypatch)
    transport.request.side_effect = [{"dataPoints": [point("2026-03-08T09:00:00Z")], "nextPageToken": "next"}, {"dataPoints": [point("2026-03-09T06:00:00Z")]}]
    rows = api.get_google_datapoints_for_date("heart-rate", "2026-03-08")
    assert len(rows) == 2
    params = transport.request.call_args_list[0].kwargs["params"]
    assert "2026-03-08T08:00:00Z" in params["filter"]
    assert "2026-03-09T07:00:00Z" in params["filter"]
    assert transport.request.call_args_list[1].kwargs["params"]["pageToken"] == "next"


def test_filter_fallback_and_local_date(monkeypatch):
    api, transport = client(monkeypatch)
    response = Mock(status_code=400)
    transport.request.side_effect = [requests.HTTPError(response=response), {"dataPoints": [point("2026-08-20T12:00:00Z"), point("2026-08-20T01:00:00Z")]}]
    assert len(api.get_google_datapoints_for_date("heart-rate", "2026-08-20")) == 1
    assert "filter" not in transport.request.call_args.kwargs["params"]


def test_partial_page_failure_preserves_available_rows(monkeypatch):
    api, transport = client(monkeypatch)
    transport.request.side_effect = [{"dataPoints": [point("2026-08-20T12:00:00Z")], "nextPageToken": "next"}, requests.HTTPError(response=Mock(status_code=500))]
    assert len(api.get_google_datapoints_for_date("heart-rate", "2026-08-20")) == 1
