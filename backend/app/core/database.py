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


# Async DB drivers are optional extras so the fast unit path (SQLite) stays lean
# and doesn't need a compiled wheel. When a URL asks for a driver that isn't
# installed, SQLAlchemy raises a bare ``ModuleNotFoundError`` naming only the
# module — which doesn't tell you how to fix it. Map the driver back to the extra
# that provides it so the error is actionable.
_DRIVER_EXTRAS: dict[str, str] = {
    "asyncpg": "postgres",
    "aiosqlite": "dev",
}


def _explain_missing_driver(url: str, exc: ModuleNotFoundError) -> ModuleNotFoundError:
    """Rewrite a missing-driver import error into an instruction that fixes it."""

    driver = exc.name or ""
    extra = _DRIVER_EXTRAS.get(driver)
    hint = (
        f"install it with: uv sync --extra dev --extra {extra}"
        if extra
        else "install the driver package for this URL"
    )
    return ModuleNotFoundError(
        f"The database driver {driver!r} required by DATABASE_URL "
        f"({url.split('://', 1)[0]}://...) is not installed — {hint}. "
        "Note that `uv sync` prunes packages outside the extras you name, so "
        "syncing without --extra postgres removes asyncpg.",
        name=exc.name,
    )


def create_engine(
    database_url: str,
    *,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
) -> AsyncEngine:
    """Create an async engine for the given URL.

    ``echo=True`` logs emitted SQL — handy when debugging, off by default.

    Connection pooling is applied only to **server** databases
    (Postgres): ``pool_size`` keeps a warm set of connections, ``max_overflow``
    allows temporary bursts, and ``pool_pre_ping`` cheaply checks a connection is
    still alive before handing it out (recovering transparently from ones the DB
    dropped after an idle period). SQLite ignores these — it uses its own pooling
    (NullPool / StaticPool), so passing QueuePool tuning would error.

    Raises a ``ModuleNotFoundError`` carrying the exact install command when the
    URL names a driver (e.g. ``asyncpg``) that isn't installed.
    """

    kwargs: dict[str, object] = {"echo": echo, "future": True}
    if not database_url.startswith("sqlite"):
        kwargs["pool_size"] = pool_size
        kwargs["max_overflow"] = max_overflow
        kwargs["pool_pre_ping"] = True
    try:
        return create_async_engine(database_url, **kwargs)
    except ModuleNotFoundError as exc:
        raise _explain_missing_driver(database_url, exc) from exc


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build a session factory bound to ``engine``.

    ``expire_on_commit=False`` keeps attribute access valid after ``commit()`` —
    important for async flows where we often read objects right after committing.
    """

    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
