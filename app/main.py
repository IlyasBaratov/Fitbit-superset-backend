"""Compatibility ASGI entrypoint and authentication export."""
from app.api.main import app, create_app
from app.core.security import authenticate
