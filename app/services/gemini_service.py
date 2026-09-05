import json
from pathlib import Path
from google import genai
from google.genai import types
from app.models import AIResponse
from app.services.ai_response_validator import InvalidAIOutput, validate_response

PROMPT = (Path(__file__).resolve().parents[1] / "prompts" / "health_analysis.txt").read_text()

class GeminiUnavailable(Exception):
    pass


class GeminiService:
    def __init__(self, settings, client=None):
        self.model = settings.model
        self.client = client or genai.Client(api_key=settings.gemini_key,
            http_options=types.HttpOptions(timeout=45000, retry_options=types.HttpRetryOptions(attempts=1)))

    def close(self):
        self.client.close()

    def generate(self, context, question):
        payload = json.dumps({"health_context": context, "question": question}, allow_nan=False)
        if len(payload.encode()) > 120000:
            raise GeminiUnavailable("Prepared context exceeds the size limit.")
        for attempt in range(2):
            instruction = PROMPT
            if attempt:
                instruction += "\nPrevious output failed validation. Return strict JSON with only supported evidence and no medical claims."
            try:
                result = self.client.models.generate_content(model=self.model, contents=payload,
                    config=types.GenerateContentConfig(system_instruction=instruction,
                        response_mime_type="application/json", response_json_schema=AIResponse.model_json_schema(),
                        temperature=0.2, max_output_tokens=4096))
            except Exception:
                raise GeminiUnavailable("AI analysis is temporarily unavailable.") from None
            try:
                return validate_response(result.text, context)
            except InvalidAIOutput:
                if attempt:
                    raise
        raise InvalidAIOutput("Invalid model output")

    def check(self):
        try:
            result = self.client.models.generate_content(model=self.model,
                contents="Return the JSON object {\"status\":\"ok\"}.",
                config=types.GenerateContentConfig(response_mime_type="application/json", max_output_tokens=256))
            if json.loads(result.text).get("status") != "ok":
                raise ValueError("Invalid connection response")
        except Exception:
            raise GeminiUnavailable("Gemini connection check failed.") from None
        return {"status": "ok", "model": self.model}
