"""FastAPI composition root with injectable infrastructure for tests."""

from contextlib import asynccontextmanager, ExitStack
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from app.core.config import Settings
from app.core.logging import configure_logging
from app.errors import APIError
from app.ai.service import AnalysisService
from app.ai.gemini import GeminiService
from app.storage.influx.queries import InfluxService
from app.api.routes import ai, system, health, calendar
from app.api.calendar_connect import CalendarConnectService
from app.api.calendar_service import CalendarReadService
from app.api.health_service import HealthReadService


def create_app(settings=None, influx=None, gemini=None, clock=None):
    @asynccontextmanager
    async def lifespan(app):
        cfg = settings or Settings.from_env()
        if settings is None:
            configure_logging(
                secrets=(
                    cfg.api_token,
                    cfg.gemini_key,
                    cfg.influx_password,
                    cfg.calendar_client_secret,
                )
            )
        with ExitStack() as resources:
            db = influx if influx is not None else InfluxService(cfg)
            if influx is None:
                resources.callback(db.close)
            llm = gemini if gemini is not None else GeminiService(cfg)
            if gemini is None:
                resources.callback(llm.close)
            app.state.settings = cfg
            app.state.influx = db
            app.state.clock = clock
            app.state.calendar = CalendarReadService(cfg, db, clock)
            app.state.analysis = AnalysisService(cfg, db, llm, clock, app.state.calendar)
            app.state.health = HealthReadService(cfg, db, clock)
            connect = CalendarConnectService(cfg, clock=clock)
            resources.callback(connect.close)
            app.state.calendar_connect = connect
            yield

    app = FastAPI(title="Wearable AI API", lifespan=lifespan)

    @app.exception_handler(APIError)
    async def error_handler(request, exc):
        return JSONResponse(
            status_code=exc.status,
            content={"error": exc.code, "message": exc.message},
            headers={"WWW-Authenticate": "Bearer"} if exc.status == 401 else None,
        )

    app.include_router(system.router)
    app.include_router(ai.router)
    app.include_router(health.router)
    app.include_router(calendar.router)
    return app


app = create_app()
