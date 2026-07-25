"""Alembic migration environment (async).

This module is executed by Alembic on every ``alembic`` command. Its jobs:

* Source the DB URL from the app's typed ``Settings`` (not from alembic.ini), so
  there is one configuration source of truth.
* Point ``target_metadata`` at ``Base.metadata`` (importing the ORM models so their
  tables register) — this is what ``--autogenerate`` diffs future model changes against.
* Run migrations through the **same async engine factory** the app uses
  (``app.core.database.create_engine``), bridging Alembic's sync migration API to our
  async engine via ``connection.run_sync(...)``.

``render_as_batch`` is enabled for SQLite because SQLite cannot ALTER columns in
place; batch mode rebuilds the table transparently (harmless for create-only, and we
never run Postgres in batch mode here).
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

import app.portfolio.models  # noqa: F401  (import registers ORM tables on Base.metadata)
from app.core.config import get_settings
from app.core.database import Base, create_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection (``alembic upgrade --sql``)."""

    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live DB using the app's async engine."""

    connectable = create_engine(_get_url())
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

