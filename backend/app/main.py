"""FastAPI application factory + lifespan.

Why a factory (``create_app``) instead of a module-level ``app``? It lets tests build
an isolated instance with overridden dependencies, and keeps construction explicit.
A module-level ``app`` is still exported at the bottom for ``uvicorn app.main:app``.

Why a lifespan? The async DB engine (a connection pool) must be created once at
startup and disposed at shutdown — not per request. We build it in the lifespan,
stash the engine + session factory on ``app.state``, and tear the engine down on
exit so no connections leak.

Run it:  ``uv run uvicorn app.main:app --reload``  →  http://localhost:8000/docs
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.database import create_engine, create_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the DB engine/session factory on startup; dispose on shutdown."""

    settings = get_settings()
    engine = create_engine(settings.database_url)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""

    app = FastAPI(
        title="Asset Management API",
        version="0.1.0",
        summary="Deterministic portfolio analytics over a currency-aware ledger.",
        lifespan=lifespan,
    )
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/health", tags=["System"])
    async def health() -> dict[str, str]:
        """Liveness probe — cheap check that the app is up (no DB touch)."""

        return {"status": "ok"}

    return app


app = create_app()
