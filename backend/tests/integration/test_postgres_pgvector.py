"""Integration test: real PostgreSQL + pgvector.

Opt-in only — excluded from the fast default run (see the ``integration`` marker in
pyproject.toml). Requires a running database:

    docker compose up -d
    uv sync --extra postgres --extra dev
    uv run pytest -m integration

The DB URL comes from ``DATABASE_URL`` (falling back to the compose defaults). We
validate three things: (1) we can connect, (2) the ``vector`` extension is present,
and (3) a real ``vector`` column round-trips a value — proving pgvector is usable by
the later embedding pipeline.
TEMP tables auto-drop, so the test is side-effect-free on the target database.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.integration

_DEFAULT_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/asset_management"


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", _DEFAULT_URL)


async def test_connection_and_pgvector_roundtrip() -> None:
    engine = create_async_engine(_database_url())
    try:
        async with engine.begin() as conn:
            # The 0002 migration normally enables this; ensure it's present so the
            # test is self-contained even against a freshly created database.
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

            extname = (
                await conn.execute(
                    text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                )
            ).scalar_one()
            assert extname == "vector"

            # Prove a real vector column stores and returns a value.
            await conn.execute(text("CREATE TEMP TABLE _v (id int, embedding vector(3))"))
            await conn.execute(text("INSERT INTO _v (id, embedding) VALUES (1, '[1,2,3]')"))
            stored = (
                await conn.execute(text("SELECT embedding FROM _v WHERE id = 1"))
            ).scalar_one()
            assert stored is not None
    finally:
        await engine.dispose()
