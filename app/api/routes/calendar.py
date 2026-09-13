"""Connecting the person's Google Calendar and reading the events it stored.

The callback is Google's redirect target; every other route needs the bearer token.
"""

from typing import Annotated
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import PlainTextResponse
from app.core.security import authenticate
from app.api.dependencies import get_calendar, get_influx
from app.api.schemas.calendar import (
    CalendarEventsResponse,
    CalendarInsightsResponse,
    CalendarStatusResponse,
)
from app.api.schemas.health import HealthQuery

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


@router.get("/api/calendar/status", response_model=CalendarStatusResponse)
def status(request: Request, user=Depends(authenticate), repository=Depends(get_influx)):
    return request.app.state.calendar_connect.status(repository)


@router.delete("/api/calendar/connection", status_code=204, response_class=Response)
def disconnect(request: Request, user=Depends(authenticate)):
    request.app.state.calendar_connect.disconnect()
    return Response(status_code=204)


@router.get("/api/calendar/events", response_model=CalendarEventsResponse)
def events(
    query: Annotated[HealthQuery, Query()],
    user=Depends(authenticate),
    service=Depends(get_calendar),
):
    return service.events(query.period)


@router.get("/api/calendar/insights", response_model=CalendarInsightsResponse)
def insights(
    query: Annotated[HealthQuery, Query()],
    user=Depends(authenticate),
    service=Depends(get_calendar),
):
    return service.insights(query.period)
