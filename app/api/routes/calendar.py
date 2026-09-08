"""Connecting the person's Google Calendar; the callback is Google's redirect target."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from app.core.security import authenticate

router = APIRouter()

CONNECTED_MESSAGE = "Google Calendar connected. You can close this tab."


@router.get("/api/calendar/connect")
def connect(request: Request, user=Depends(authenticate)):
    return request.app.state.calendar_connect.begin()


@router.get("/api/calendar/callback", response_class=PlainTextResponse)
def callback(request: Request, state: str = "", code: str = "", error: str = ""):
    """No bearer: Google redirects the browser here; the `state` nonce is the credential."""
    request.app.state.calendar_connect.complete(state, code, error)
    return PlainTextResponse(CONNECTED_MESSAGE)
