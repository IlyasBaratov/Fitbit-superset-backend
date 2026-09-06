import json
import logging
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from google import genai
from google.genai import types
from app.api.schemas.ai import AIResponse
from app.ai.validator import InvalidAIOutput, validate_response

PROMPT = (Path(__file__).resolve().parent / "prompts" / "health_analysis.txt").read_text()

class GeminiUnavailable(Exception):
    def __init__(self, message="AI analysis is temporarily unavailable.", code="AI_SERVICE_UNAVAILABLE", status=503, transient=False):
        super().__init__(message)
        self.code = code
        self.status = status
        self.transient = transient


RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404}
TIMEOUT_CODES = {"DEADLINE_EXCEEDED"}
OVERLOAD_CODES = {"RESOURCE_EXHAUSTED", "UNAVAILABLE"}
CONFIGURATION_CODES = {"INVALID_ARGUMENT", "UNAUTHENTICATED", "PERMISSION_DENIED", "NOT_FOUND"}
LOGGER = logging.getLogger(__name__)


class GeminiService:
    def __init__(self, settings, client=None):
        self.model = settings.model
        self.fallback_model = settings.fallback_model.strip()
        self.retry_attempts = settings.gemini_retry_attempts
        self.retry_base_ms = settings.gemini_retry_base_ms
        self.retry_max_backoff_ms = settings.gemini_retry_max_backoff_ms
        self.retry_jitter_ms = settings.gemini_retry_jitter_ms
        self.retry_max_elapsed_ms = settings.gemini_retry_max_elapsed_ms
        self.client = client or genai.Client(api_key=settings.gemini_key,
            http_options=types.HttpOptions(timeout=settings.gemini_timeout_ms, retry_options=types.HttpRetryOptions(attempts=1)))

    def close(self):
        self.client.close()

    def generate(self, context, question):
        payload = json.dumps({"health_context": context, "question": question}, allow_nan=False)
        if len(payload.encode()) > 120000:
            raise GeminiUnavailable("Prepared context exceeds the size limit.")
        started = time.monotonic()
        try:
            return self._generate_with_retries(self.model, payload, context, started)
        except GeminiUnavailable as err:
            if not (self.fallback_model and self.fallback_model != self.model and err.transient):
                raise
            LOGGER.warning("gemini transient failure, trying fallback model=%s elapsed_ms=%d", self.fallback_model, int((time.monotonic()-started)*1000))
            return self._generate_with_retries(self.fallback_model, payload, context, started)

    def _generate_with_retries(self, model, payload, context, started):
        last_error = GeminiUnavailable("AI analysis is temporarily unavailable.", transient=True)
        for attempt in range(1, self.retry_attempts + 1):
            try:
                return self._generate_and_validate(model, payload, context)
            except InvalidAIOutput:
                raise
            except Exception as err:
                status = self._status_code(err)
                category, code, message = self._classify_error(err, status)
                elapsed_ms = int((time.monotonic() - started) * 1000)
                LOGGER.warning("gemini upstream error category=%s status=%s attempt=%d elapsed_ms=%d", category, status, attempt, elapsed_ms)
                transient = category in {"timeout", "overload", "transient"}
                last_error = GeminiUnavailable(message, code=code, status=503 if transient else 500, transient=transient)
                deadline_hit = elapsed_ms >= self.retry_max_elapsed_ms
                if not transient or attempt >= self.retry_attempts or deadline_hit:
                    raise last_error from None
                delay = self._retry_delay_seconds(err, attempt)
                remaining = (self.retry_max_elapsed_ms / 1000) - (time.monotonic() - started)
                if remaining <= 0:
                    raise last_error from None
                time.sleep(max(0.0, min(delay, remaining)))
        raise last_error

    def _generate_and_validate(self, model, payload, context):
        for attempt in range(2):
            instruction = PROMPT
            if attempt:
                instruction += "\nPrevious output failed validation. Return strict JSON with only supported evidence and no medical claims."
            result = self.client.models.generate_content(model=model, contents=payload,
                config=types.GenerateContentConfig(system_instruction=instruction,
                    response_mime_type="application/json", response_json_schema=AIResponse.model_json_schema(),
                    temperature=0.2, max_output_tokens=4096))
            try:
                return validate_response(result.text, context)
            except InvalidAIOutput:
                if attempt:
                    raise
        raise InvalidAIOutput("Invalid model output")

    def _status_code(self, err):
        status = getattr(err, "status_code", None)
        if status is None:
            status = getattr(getattr(err, "response", None), "status_code", None)
        try:
            return int(status) if status is not None else None
        except (TypeError, ValueError):
            return None

    def _classify_error(self, err, status):
        raw_code = getattr(err, "code", "")
        code = str(raw_code).upper().strip() if raw_code is not None else ""
        message = (getattr(err, "message", "") or str(err)).lower()
        if isinstance(err, TimeoutError) or status == 408 or code in TIMEOUT_CODES or "timeout" in message or "timed out" in message:
            return "timeout", "AI_PROVIDER_TIMEOUT", "Gemini did not respond in time. Please retry shortly."
        if status == 429 or status == 503 or code in OVERLOAD_CODES or "rate limit" in message or "temporar" in message or "unavailable" in message:
            return "overload", "AI_PROVIDER_OVERLOADED", "Gemini is temporarily overloaded. Please retry shortly."
        if status in NON_RETRYABLE_STATUS_CODES or code in CONFIGURATION_CODES:
            return "configuration", "AI_PROVIDER_CONFIGURATION_ERROR", "Gemini configuration is invalid. Verify API key and model settings."
        if status in RETRYABLE_STATUS_CODES:
            return "transient", "AI_SERVICE_UNAVAILABLE", "AI analysis is temporarily unavailable."
        return "unknown", "AI_SERVICE_UNAVAILABLE", "AI analysis is temporarily unavailable."

    def _retry_delay_seconds(self, err, attempt):
        retry_after = self._retry_after_seconds(err)
        if retry_after is not None:
            return retry_after
        exponential = self.retry_base_ms * (2 ** max(0, attempt - 1))
        backoff_ms = min(self.retry_max_backoff_ms, exponential)
        jitter = random.uniform(0, self.retry_jitter_ms) if self.retry_jitter_ms else 0
        return (backoff_ms + jitter) / 1000

    def _retry_after_seconds(self, err):
        headers = getattr(getattr(err, "response", None), "headers", None) or {}
        value = headers.get("Retry-After") if hasattr(headers, "get") else None
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                return None
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())

    def check(self):
        try:
            result = self.client.models.generate_content(model=self.model,
                contents="Return the JSON object {\"status\":\"ok\"}.",
                config=types.GenerateContentConfig(response_mime_type="application/json", max_output_tokens=256))
            if json.loads(result.text).get("status") != "ok":
                raise ValueError("Invalid connection response")
        except Exception as err:
            status = self._status_code(err)
            _, code, message = self._classify_error(err, status)
            raise GeminiUnavailable("Gemini connection check failed." if code == "AI_SERVICE_UNAVAILABLE" else message, code=code, status=503) from None
        return {"status": "ok", "model": self.model}
