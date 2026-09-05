import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.config import Settings
from app.main import create_app, authenticate
from app.models import AnalysisRequest, AskRequest

@pytest.fixture
def settings():
    return Settings(api_token="t" * 40, gemini_key="test", model="test")

def test_configuration_requires_secrets():
    with pytest.raises(ValueError):
        Settings(api_token="", gemini_key="", model="")

def test_authentication(settings):
    app = create_app(settings)
    @app.get("/private")
    def private(user=Depends(authenticate)):
        return {"user": user}
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/private").status_code == 401
        assert client.get("/private", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get("/private", headers={"Authorization": "Bearer " + settings.api_token}).json() == {"user": "user_001"}

def test_requests_reject_identity_and_blank_questions():
    with pytest.raises(ValidationError):
        AnalysisRequest(UserId="other")
    with pytest.raises(ValidationError):
        AskRequest(question="  ")
