"""Bounded per-process caching and endpoint orchestration."""
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
import threading
import time
from app.errors import APIError
from app.ai.analytics import Window
from app.ai.context import measurements, build_context, classify
from app.storage.influx.queries import DataUnavailable
from app.ai.gemini import GeminiUnavailable
from app.ai.validator import InvalidAIOutput

LOGGER = logging.getLogger(__name__)

class AnalysisService:
    def __init__(self, settings, influx, gemini, clock=None, calendar=None):
        self.settings, self.influx, self.gemini = settings, influx, gemini
        self.calendar = calendar
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.cache = OrderedDict()
        self.lock = threading.Lock()

    def period_days(self, period):
        if period is None:
            return self.settings.default_days
        if not re.fullmatch(r"[1-9][0-9]?d", period):
            raise APIError("INVALID_ANALYSIS_PERIOD", f"Analysis period must be between 1 and {self.settings.max_days} days (for example 7d).", 422)
        days = int(period[:-1])
        if days > self.settings.max_days:
            raise APIError("INVALID_ANALYSIS_PERIOD", f"Analysis period must be between 1 and {self.settings.max_days} days.", 422)
        return days

    def run(self, request, endpoint, user):
        if user != self.settings.user_id:
            raise APIError("UNAUTHORIZED", "User identity is not authorized.", 401)
        days = self.period_days(request.period)
        question = request.question.strip() if endpoint == "ask" else f"Analyze my last {days} days, focusing on {', '.join(request.focus) if endpoint == 'analyze' else endpoint}."
        focus = classify(question) if endpoint == "ask" else (request.focus if endpoint == "analyze" else [endpoint])
        window = Window(days, self.settings.timezone, self.clock())
        # Serialize personal analysis requests to bound provider usage and duplicate in-flight calls.
        if not self.lock.acquire(timeout=1):
            raise APIError("AI_BUSY", "An analysis is already running; retry shortly.", 429)
        try:
            try:
                data = self.influx.fetch(measurements(focus), window.query_start, window.now)
            except DataUnavailable:
                raise APIError("DATA_SERVICE_UNAVAILABLE", "Health data is temporarily unavailable.") from None
            context, sufficient = build_context(data, window, focus, self._calendar_insights(focus, days),
                                                self.settings.calendar_ai_include_titles)
            if not sufficient:
                raise APIError("INSUFFICIENT_DATA", "Not enough relevant data is available for this analysis.", 422)
            key = hashlib.sha256(json.dumps([user, self.settings.provider, self.settings.device_id, self.settings.model,
                endpoint, sorted(focus), question, context], sort_keys=True, allow_nan=False).encode()).hexdigest()
            now = time.monotonic()
            for expired in [k for k, (until, _) in self.cache.items() if until <= now]:
                del self.cache[expired]
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key][1].model_copy(deep=True)
            try:
                response = self.gemini.generate(context, question)
            except GeminiUnavailable as err:
                raise APIError(getattr(err, "code", "AI_SERVICE_UNAVAILABLE"), str(err), getattr(err, "status", 503)) from None
            except InvalidAIOutput:
                raise APIError("INVALID_AI_OUTPUT", "AI analysis could not be validated.", 502) from None
            self.cache[key] = (time.monotonic()+self.settings.cache_seconds, response.model_copy(deep=True))
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
            return response
        finally:
            self.lock.release()

    def _calendar_insights(self, focus, days):
        """The deterministic insights; an unreadable calendar never fails an analysis (D1)."""
        if "calendar" not in focus or self.calendar is None:
            return None
        try:
            insights = self.calendar.insights(f"{days}d")
        except (APIError, DataUnavailable):
            LOGGER.warning("calendar insights unavailable; continuing without calendar context")
            return None
        return insights.model_dump() if hasattr(insights, "model_dump") else insights

    def check(self):
        if not self.lock.acquire(timeout=1):
            raise APIError("AI_BUSY", "An analysis is already running; retry shortly.", 429)
        try:
            return self.gemini.check()
        except GeminiUnavailable as err:
            raise APIError(getattr(err, "code", "AI_SERVICE_UNAVAILABLE"), str(err), getattr(err, "status", 503)) from None
        finally:
            self.lock.release()
