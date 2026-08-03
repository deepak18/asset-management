"""Tests for the async engine factory (app.core.database).

The valuable behavior to pin here is the **diagnostic**: an optional DB driver that
isn't installed must produce an error telling you which extra to sync, not a bare
``ModuleNotFoundError: No module named 'asyncpg'`` that leaves you guessing.
"""

from __future__ import annotations

import builtins
from collections.abc import Sequence

import pytest

from app.core.database import create_engine


def test_sqlite_engine_builds_without_pool_kwargs() -> None:
    """SQLite must not receive QueuePool tuning (it would raise)."""

    engine = create_engine("sqlite+aiosqlite://")
    assert engine.dialect.name == "sqlite"


def test_missing_driver_error_names_the_extra_to_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def _no_asyncpg(
        name: str,
        globals_: object = None,
        locals_: object = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> object:
        if name == "asyncpg" or name.startswith("asyncpg."):
            raise ModuleNotFoundError("No module named 'asyncpg'", name="asyncpg")
        return real_import(name, globals_, locals_, fromlist, level)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _no_asyncpg)

    with pytest.raises(ModuleNotFoundError) as excinfo:
        create_engine("postgresql+asyncpg://u:p@localhost:5432/db")

    message = str(excinfo.value)
    assert "asyncpg" in message
    # The whole point: tell the user the exact command that fixes it.
    assert "uv sync --extra dev --extra postgres" in message
    # And explain why it vanished in the first place.
    assert "prunes" in message
