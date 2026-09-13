import json
from unittest.mock import Mock
import pytest
from app.config import Settings
from app.services.gemini_service import GeminiService, GeminiUnavailable
from app.services.ai_response_validator import validate_response, InvalidAIOutput

class UpstreamError(Exception):
    def __init__(self, message, status_code=None, code=None, headers=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.response = Mock(status_code=status_code, headers=headers or {})


@pytest.fixture
def context():
    return {"evidence_keys": ["steps"], "activity": {"steps": {}}, "data_quality": {"missing": ["HRV"]}}

@pytest.fixture
def output():
    return {"summary": "Walking activity was recorded.", "insights": [{"category": "activity", "title": "Steps", "observation": "Steps were recorded.", "reasoning": "Based on your recorded steps.", "priority": "low", "based_on": ["steps"]}], "suggestions": [], "warnings": [], "data_gaps": []}

def test_validation_keeps_server_gaps(context, output):
    assert "Unavailable measurement: HRV" in validate_response(json.dumps(output), context).data_gaps

@pytest.mark.parametrize("kind", ["json", "score", "evidence", "diagnosis", "medication", "missing_metric", "unsupported_score"])
def test_rejects_invalid_responses(context, output, kind):
    if kind == "score": output["score"] = {"activity": 101}
    if kind == "unsupported_score": output["score"] = {"sleep": 50}
    if kind == "evidence": output["insights"][0]["based_on"] = ["hrv"]
    if kind == "diagnosis": output["summary"] = "You have a heart condition."
    if kind == "medication": output["summary"] = "Stop your prescribed treatment."
    if kind == "missing_metric": output["summary"] = "Your HRV is excellent."
    with pytest.raises(InvalidAIOutput):
        validate_response("not JSON" if kind == "json" else json.dumps(output), context)

def test_missing_metric_may_be_described_as_missing(context, output):
    output["summary"] = "HRV is unavailable."
    validate_response(json.dumps(output), context)

def test_retries_invalid_output_once(context, output):
    client = Mock()
    client.models.generate_content.side_effect = [Mock(text="bad"), Mock(text=json.dumps(output))]
    service = GeminiService(Settings(api_token="x"*40, gemini_key="secret", model="model"), client)
    assert service.generate(context, "How active?").summary
    assert client.models.generate_content.call_count == 2
    assert "strict JSON" in client.models.generate_content.call_args.kwargs["config"].system_instruction
    assert "secret" not in client.models.generate_content.call_args.kwargs["contents"]

def test_second_invalid_output_fails(context):
    client = Mock()
    client.models.generate_content.return_value.text = "bad"
    service = GeminiService(Settings(api_token="x"*40, gemini_key="k", model="m"), client)
    with pytest.raises(InvalidAIOutput): service.generate(context, "question")
    assert client.models.generate_content.call_count == 2

def test_non_retryable_upstream_failure_not_retried(context):
    client = Mock()
    client.models.generate_content.side_effect = UpstreamError("bad api key secret", status_code=401, code="UNAUTHENTICATED")
    service = GeminiService(Settings(api_token="x"*40, gemini_key="k", model="m"), client)
    with pytest.raises(GeminiUnavailable, match="configuration is invalid") as err:
        service.generate(context, "question")
    assert err.value.code == "AI_PROVIDER_CONFIGURATION_ERROR"
    assert client.models.generate_content.call_count == 1


@pytest.mark.parametrize("score", [True, "75"])
def test_scores_must_be_json_numbers(context, output, score):
    output["score"] = {"activity": score}
    with pytest.raises(InvalidAIOutput):
        validate_response(json.dumps(output), context)


def test_no_sleep_claim_without_sleep_evidence(context, output):
    output["summary"] = "Your sleep quality is excellent."
    with pytest.raises(InvalidAIOutput):
        validate_response(json.dumps(output), context)


def test_meeting_claims_need_calendar_evidence(context, output):
    output["summary"] = "Your meetings cluster on Wednesdays."
    with pytest.raises(InvalidAIOutput):
        validate_response(json.dumps(output), context)
    context["evidence_keys"] = ["steps", "calendar_load", "calendar_series"]
    context["calendar"] = {"load": {"days_with_events": 12}}
    assert validate_response(json.dumps(output), context).summary


def test_transient_timeout_is_retried_once_when_next_attempt_succeeds(context, output):
    client = Mock()
    client.models.generate_content.side_effect = [TimeoutError("timed out"), Mock(text=json.dumps(output))]
    service = GeminiService(Settings(api_token="x"*40, gemini_key="k", model="m", gemini_retry_base_ms=0, gemini_retry_jitter_ms=0), client)
    assert service.generate(context, "question").summary
    assert client.models.generate_content.call_count == 2


def test_retry_after_header_is_used_for_backoff(context, monkeypatch):
    client = Mock()
    error = UpstreamError("rate limited", status_code=429, headers={"Retry-After": "0"})
    client.models.generate_content.side_effect = [error, GeminiUnavailable("done")]
    service = GeminiService(Settings(api_token="x"*40, gemini_key="k", model="m", gemini_retry_attempts=2), client)
    slept = []
    monkeypatch.setattr("app.services.gemini_service.time.sleep", lambda s: slept.append(s))
    with pytest.raises(GeminiUnavailable):
        service.generate(context, "question")
    assert slept == [0.0]


def test_retry_exhaustion_for_transient_error(context):
    client = Mock()
    client.models.generate_content.side_effect = TimeoutError("timed out")
    service = GeminiService(Settings(api_token="x"*40, gemini_key="k", model="m", gemini_retry_attempts=2, gemini_retry_base_ms=0, gemini_retry_jitter_ms=0), client)
    with pytest.raises(GeminiUnavailable, match="did not respond in time") as err:
        service.generate(context, "question")
    assert err.value.code == "AI_PROVIDER_TIMEOUT"
    assert client.models.generate_content.call_count == 2


def test_fallback_model_is_used_after_transient_primary_failure(context, output):
    client = Mock()
    calls = []

    def side_effect(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] == "primary":
            raise TimeoutError("timed out")
        return Mock(text=json.dumps(output))

    client.models.generate_content.side_effect = side_effect
    service = GeminiService(Settings(api_token="x"*40, gemini_key="k", model="primary", fallback_model="fallback",
        gemini_retry_attempts=1, gemini_retry_base_ms=0, gemini_retry_jitter_ms=0), client)
    assert service.generate(context, "question").summary
    assert calls == ["primary", "fallback"]
