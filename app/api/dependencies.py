"""Request-scoped access to application-owned services."""

from fastapi import Request


def get_analysis(request: Request):
    return request.app.state.analysis


def get_influx(request: Request):
    return request.app.state.influx


def get_health(request: Request):
    return request.app.state.health
