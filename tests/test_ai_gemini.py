import json
from unittest.mock import Mock
import pytest
from app.config import Settings
from app.services.gemini_service import GeminiService, GeminiUnavailable
from app.services.ai_response_validator import validate_response, InvalidAIOutput

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

def test_upstream_failure_redacted_and_not_retried(context):
    client = Mock()
    client.models.generate_content.side_effect = TimeoutError("secret URL")
    service = GeminiService(Settings(api_token="x"*40, gemini_key="k", model="m"), client)
    with pytest.raises(GeminiUnavailable, match="temporarily unavailable"):
        service.generate(context, "question")
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
