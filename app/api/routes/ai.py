"""Existing AI API routes with unchanged request and response contracts."""
from fastapi import APIRouter, Depends, Request
from app.core.security import authenticate
from app.api.schemas.ai import AnalysisRequest, AskRequest, AIResponse

router = APIRouter()

@router.post("/api/ai/analyze", response_model=AIResponse)
def analyze(body: AnalysisRequest, request: Request, user=Depends(authenticate)):
    return request.app.state.analysis.run(body, "analyze", user)

@router.post("/api/ai/ask", response_model=AIResponse)
def ask(body: AskRequest, request: Request, user=Depends(authenticate)):
    return request.app.state.analysis.run(body, "ask", user)

def specialized(endpoint):
    def route(body: AnalysisRequest, request: Request, user=Depends(authenticate)):
        return request.app.state.analysis.run(body, endpoint, user)
    route.__name__ = "analyze_" + endpoint
    return route

for endpoint in ("sleep", "activity", "workouts", "recovery"):
    router.add_api_route("/api/ai/"+endpoint, specialized(endpoint), methods=["POST"], response_model=AIResponse)

@router.post("/api/ai/test")
def connection_test(request: Request, user=Depends(authenticate)):
    return request.app.state.analysis.check()

