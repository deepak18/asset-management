"""Async SQLAlchemy engine + session plumbing

This is infrastructure, **not** business logic (§3). It exposes:

* ``Base`` — the declarative base all ORM models inherit from; its ``metadata``
  is what Alembic (later) and ``create_all`` (tests) use to build the schema.
* ``create_engine`` / ``create_session_factory`` — small factories, so tests can
  spin up a disposable in-memory SQLite engine while production wires a
  ``postgresql+asyncpg`` engine from ``Settings.database_url``.

Why async all the way down? FastAPI route handlers are async (PLAN.md §1.1), and
mixing a sync DB driver under an async server blocks the event loop. SQLAlchemy's
async engine (backed by ``greenlet``) keeps DB I/O non-blocking end-to-end.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model (single metadata registry)."""


def create_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create an async engine for the given URL.

    ``echo=True`` logs emitted SQL — handy when debugging, off by default.
    """

    return create_async_engine(database_url, echo=echo, future=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build a session factory bound to ``engine``.

    ``expire_on_commit=False`` keeps attribute access valid after ``commit()`` —
    important for async flows where we often read objects right after committing.
    """

    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
