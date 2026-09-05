from contextlib import asynccontextmanager
import secrets
from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.config import Settings

class APIError(Exception):
    def __init__(self, code, message, status=503):
        self.code, self.message, self.status = code, message, status

bearer = HTTPBearer(auto_error=False)
def create_app(settings=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings or Settings.from_env()
        yield
    app = FastAPI(title="Wearable AI API", lifespan=lifespan)
    @app.exception_handler(APIError)
    async def error_handler(request, exc):
        return JSONResponse(status_code=exc.status, content={"error": exc.code, "message": exc.message})
    @app.get("/health")
    def health():
        return {"status": "ok"}
    return app

from fastapi import Request
def authenticate(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    settings = request.app.state.settings
    if credentials is None or not secrets.compare_digest(credentials.credentials, settings.api_token):
        raise APIError("UNAUTHORIZED", "A valid bearer token is required.", 401)
    return settings.user_id

app = create_app()
