"""Tests that the Alembic migrations build the schema the ORM models describe.

These run fully offline against a temporary SQLite file (no Postgres): we apply the
migration with Alembic's programmatic API, then inspect the resulting schema. The
drift guard is the important one — it fails if someone changes a model column but
forgets the corresponding migration, catching schema/model divergence early.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

import app.marketdata.models  # noqa: F401  (registers the cache table on Base.metadata)
import app.portfolio.models  # noqa: F401  (registers ORM tables on Base.metadata)
from app.core.config import get_settings
from app.core.database import Base


@pytest.fixture
def _isolate_settings() -> Iterator[None]:
    """Clear the cached Settings around each test so DATABASE_URL overrides apply."""

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _alembic_config(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    # as_posix() avoids Windows backslashes breaking the SQLite URL.
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    get_settings.cache_clear()
    return Config("alembic.ini")


def test_upgrade_creates_model_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _isolate_settings: None
) -> None:
    db_path = tmp_path / "migrated.db"
    command.upgrade(_alembic_config(db_path, monkeypatch), "head")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    assert set(Base.metadata.tables) <= tables  # every model table created
    assert "alembic_version" in tables          # version stamp present

    # Drift guard: migration columns must exactly match the model columns.
    for name, table in Base.metadata.tables.items():
        actual = {col["name"] for col in inspector.get_columns(name)}
        expected = {col.name for col in table.columns}
        assert expected == actual, f"{name}: migration {actual} != model {expected}"

    engine.dispose()


def test_downgrade_removes_domain_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _isolate_settings: None
) -> None:
    db_path = tmp_path / "reversible.db"
    cfg = _alembic_config(db_path, monkeypatch)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    tables = set(inspect(engine).get_table_names())
    engine.dispose()

    assert "portfolios" not in tables
    assert "transactions" not in tables
    assert "market_data_cache" not in tables
