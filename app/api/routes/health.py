"""Authenticated health-data endpoints, with server-controlled identity."""

from typing import Annotated
from fastapi import APIRouter, Depends, Query, Request
from app.core.security import authenticate
from app.api.dependencies import get_health
from app.api.health_service import HEALTH_MEASUREMENTS
from app.api.schemas.health import HealthQuery, HealthResponse, DevicesResponse
from app.errors import APIError

router = APIRouter()


def health_route(category):
    def read(
        query: Annotated[HealthQuery, Query()],
        user=Depends(authenticate),
        service=Depends(get_health),
    ):
        return service.read(category, query.period)

    read.__name__ = "read_" + category.replace("-", "_")
    return read


for category in HEALTH_MEASUREMENTS:
    router.add_api_route(
        "/api/health/" + category,
        health_route(category),
        methods=["GET"],
        response_model=HealthResponse,
    )


@router.get("/api/devices", response_model=DevicesResponse)
def devices(request: Request, user=Depends(authenticate), service=Depends(get_health)):
    if request.query_params:
        raise APIError(
            "INVALID_DEVICE_QUERY",
            "Device identity is controlled by the server; query parameters are not accepted.",
            422,
        )
    return service.devices()
