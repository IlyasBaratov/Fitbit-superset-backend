from contextlib import asynccontextmanager
import secrets
from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import Settings
from app.errors import APIError
from app.models import AnalysisRequest, AskRequest, AIResponse

bearer = HTTPBearer(auto_error=False)

def authenticate(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    settings = request.app.state.settings
    if credentials is None or not secrets.compare_digest(credentials.credentials.encode(), settings.api_token.encode()):
        raise APIError("UNAUTHORIZED", "A valid bearer token is required.", 401)
    return settings.user_id


def create_app(settings=None, influx=None, gemini=None, clock=None):
    @asynccontextmanager
    async def lifespan(app):
        from app.services.influx_service import InfluxService
        from app.services.gemini_service import GeminiService
        from app.services.analysis_service import AnalysisService
        cfg = settings or Settings.from_env()
        app.state.settings = cfg
        db = influx or InfluxService(cfg)
        ai = gemini or GeminiService(cfg)
        app.state.analysis = AnalysisService(cfg, db, ai, clock)
        try:
            yield
        finally:
            if influx is None:
                db.close()
            if gemini is None:
                ai.close()
    app = FastAPI(title="Wearable AI API", lifespan=lifespan)

    @app.exception_handler(APIError)
    async def error_handler(request, exc):
        return JSONResponse(status_code=exc.status, content={"error": exc.code, "message": exc.message},
                            headers={"WWW-Authenticate": "Bearer"} if exc.status == 401 else None)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/ai/analyze", response_model=AIResponse)
    def analyze(body: AnalysisRequest, request: Request, user=Depends(authenticate)):
        return request.app.state.analysis.run(body, "analyze", user)

    @app.post("/api/ai/ask", response_model=AIResponse)
    def ask(body: AskRequest, request: Request, user=Depends(authenticate)):
        return request.app.state.analysis.run(body, "ask", user)

    def specialized(endpoint):
        def route(body: AnalysisRequest, request: Request, user=Depends(authenticate)):
            return request.app.state.analysis.run(body, endpoint, user)
        route.__name__ = "analyze_" + endpoint
        return route

    for endpoint in ("sleep", "activity", "workouts", "recovery"):
        app.add_api_route("/api/ai/"+endpoint, specialized(endpoint), methods=["POST"], response_model=AIResponse)

    @app.post("/api/ai/test")
    def connection_test(request: Request, user=Depends(authenticate)):
        return request.app.state.analysis.check()

    return app

app = create_app()
