"""Bearer authentication shared by authenticated API routes."""
import secrets
from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.errors import APIError

bearer = HTTPBearer(auto_error=False)

def authenticate(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    settings = request.app.state.settings
    if credentials is None or not secrets.compare_digest(credentials.credentials.encode(), settings.api_token.encode()):
        raise APIError("UNAUTHORIZED", "A valid bearer token is required.", 401)
    return settings.user_id


