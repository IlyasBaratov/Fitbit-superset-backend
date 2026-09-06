from app.api.main import create_app
from app.main import create_app as legacy_create_app
from app.api.schemas.ai import AIResponse
from app.models import AIResponse as LegacyResponse
from app.ai.gemini import PROMPT


def test_compatible_api_exports_and_prompt():
    assert legacy_create_app is create_app
    assert LegacyResponse is AIResponse
    assert PROMPT.strip()
    paths = set(create_app().openapi()["paths"])
    assert paths == {"/health", *("/api/ai/" + name for name in ("analyze", "ask", "sleep", "activity", "workouts", "recovery", "test"))}
