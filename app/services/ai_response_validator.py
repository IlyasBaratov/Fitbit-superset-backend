"""Structural and conservative semantic checks; not a clinical safety guarantee."""
import json
import re
from app.models import AIResponse

class InvalidAIOutput(Exception):
    pass

UNSAFE = re.compile(
    r"\b(?:you (?:have|are suffering from) (?:a |an |the )?(?:heart condition|disease|diabetes|cancer|infection|sleep apnea|arrhythmia|hypertension)|you (?:are sick|are ill)|you(?:'re| are) (?:diabetic|hypertensive)|"
    r"(?:proves?|confirms?|diagnoses?) (?:that |a |the |you )|"
    r"(?:stop|discontinue|reduce|increase|skip|change) (?:\w+\s+){0,3}(?:medication|medicine|prescription|prescribed|treatment|dose)|"
    r"(?:take|start|prescribe) (?:\w+\s+){0,2}(?:antibiotics|medication|insulin))\b", re.I)
METRIC_TERMS = {
    r"\b(?:sleep duration|sleep quality|sleep efficiency|your sleep)\b": {"sleep_hours", "sleep_efficiency"},
    r"\b(?:step count|steps)\b": {"steps"},
    r"\b(?:hrv|rmssd)\b": {"hrv_rmssd", "hrv_deep_rmssd"},
    r"\b(?:spo2|oxygen saturation)\b": {"spo2", "intraday_spo2"},
    r"\b(?:resting heart rate|resting hr)\b": {"resting_hr"},
    r"\b(?:breathing rate|respiratory rate)\b": {"breathing_rate"},
    r"\b(?:skin temperature|temperature deviation)\b": {"skin_temperature_deviation"},
    r"\b(?:deep sleep|rem sleep)\b": {"deep_minutes", "rem_minutes", "deep_sleep_percent", "rem_percent"},
    r"\b(?:weight|bmi)\b": {"weight", "bmi"},
}
ABSENCE = re.compile(r"missing|unavailable|not (?:available|provided|supplied)|no (?:data|measurements)|cannot|can't|insufficient", re.I)


def validate_response(text, context):
    if not isinstance(text, str) or len(text) > 50000:
        raise InvalidAIOutput("Invalid output size")
    try:
        response = AIResponse.model_validate_json(text)
    except ValueError:
        raise InvalidAIOutput("Invalid JSON response schema") from None
    evidence = set(context["evidence_keys"])
    for item in [*response.insights, *response.suggestions]:
        if not set(item.based_on) <= evidence:
            raise InvalidAIOutput("Unsupported evidence reference")
    for category, value in response.score.model_dump().items():
        if value is not None and not context.get(category):
            raise InvalidAIOutput("Score has no supporting data")
    serialized = json.dumps(response.model_dump(), ensure_ascii=False)
    if UNSAFE.search(serialized):
        raise InvalidAIOutput("Unsupported diagnostic or treatment claim")
    texts = [response.summary] + [i.observation + " " + i.reasoning for i in response.insights]
    for text in texts:
        for sentence in re.split(r"[.!?;]\s*", text):
            for pattern, keys in METRIC_TERMS.items():
                if re.search(pattern, sentence, re.I) and not keys & evidence and not ABSENCE.search(sentence):
                    raise InvalidAIOutput("Claim references an unavailable metric")
    # Preserve deterministic gaps even if the model omits them.
    quality = context.get("data_quality", {})
    for source in quality.get("missing", []):
        gap = f"Unavailable measurement: {source}"
        if gap not in response.data_gaps:
            response.data_gaps.append(gap)
    for source in quality.get("partial", []):
        gap = f"Partial coverage: {source}"
        if gap not in response.data_gaps:
            response.data_gaps.append(gap)
    if any(v is not None for v in response.score.model_dump().values()):
        response.warnings.append("Scores are model-generated wellness estimates, not clinical assessments.")
    return response
