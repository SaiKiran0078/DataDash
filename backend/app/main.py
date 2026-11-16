from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.api.routes import auth, dashboards, datasets, reports, shared
from app.core.config import Settings, get_settings
from app.core.ratelimit import RateLimiter
from app.db import models  # noqa: F401  (registers the tables on Base.metadata)
from app.db.session import Base, make_engine
from app.engine.errors import DataError
from app.services.dataset_store import DatasetStore


def create_app(settings: Settings | None = None) -> FastAPI:
    """App factory: tests pass their own Settings (in-memory DB, temp folder, no rate limit)."""
    settings = settings or get_settings()
    settings.validate_for_production()

    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)

    app = FastAPI(title="DataDash API", version="6.0.11", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = sessionmaker(engine, expire_on_commit=False)
    app.state.store = DatasetStore(settings.data_dir, session_factory=app.state.session_factory)
    app.state.limiters = {
        "auth": RateLimiter(max_calls=20, window_seconds=60),      # password-guessing brake
        "shared": RateLimiter(max_calls=120, window_seconds=60),
    }

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,                                     # we use Bearer tokens, not cookies
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    @app.exception_handler(DataError)
    async def data_error_handler(_request: Request, exc: DataError):
        return JSONResponse(status_code=exc.status, content={"detail": str(exc)})

    @app.get("/api/health", tags=["health"])
    def health():
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    for module in (auth, datasets, dashboards, shared, reports):
        app.include_router(module.router, prefix="/api")
    return app


def get_app() -> FastAPI:
    """Entry point for the server:  uvicorn app.main:get_app --factory"""
    return create_app()
