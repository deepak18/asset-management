"""Tests that the Alembic migrations build the schema the ORM models describe.

These run fully offline against a temporary SQLite file (no Postgres): we apply the
migration with Alembic's programmatic API, then inspect the resulting schema. The
drift guard is the important one — it fails if someone changes a model column but
forgets the corresponding migration, catching schema/model divergence early.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, inspect, select

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


def test_existing_labels_and_legacy_partial_jobs_are_protected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _isolate_settings: None
) -> None:
    db_path = tmp_path / "legacy.db"
    cfg = _alembic_config(db_path, monkeypatch)
    command.upgrade(cfg, "0004")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        metadata = MetaData()
        portfolios = Table("portfolios", metadata, autoload_with=engine)
        holdings = Table("holdings", metadata, autoload_with=engine)
        jobs = Table("statement_imports", metadata, autoload_with=engine)
        with engine.begin() as conn:
            conn.execute(portfolios.insert().values(id=1, name="Legacy", base_currency="USD"))
            conn.execute(holdings.insert(), [
                {"portfolio_id": 1, "ticker": "AAA", "sector": "Manual", "industry": None},
                {"portfolio_id": 1, "ticker": "BBB", "sector": None, "industry": "Manual"},
                {"portfolio_id": 1, "ticker": "CCC", "sector": None, "industry": None},
            ])
            for status in ("PENDING", "RUNNING", "FAILED", "SUCCEEDED"):
                conn.execute(jobs.insert().values(
                    portfolio_id=1, status=status, source_format="robinhood_csv",
                    original_filename="old.csv", storage_key="old.raw", checksum="a" * 64,
                    size_bytes=1, processed_rows=0, created_transactions=0,
                    tickers_json="[]", warnings_json="[]",
                ))
        command.upgrade(cfg, "head")
        upgraded = MetaData()
        holdings = Table("holdings", upgraded, autoload_with=engine)
        jobs = Table("statement_imports", upgraded, autoload_with=engine)
        with engine.connect() as conn:
            sources = dict(conn.execute(select(
                holdings.c.ticker, holdings.c.classification_source
            )).tuples().all())
            retry_safety = dict(conn.execute(select(
                jobs.c.status, jobs.c.retry_safe
            )).tuples().all())
        assert sources == {"AAA": "MANUAL", "BBB": "MANUAL", "CCC": "NONE"}
        assert retry_safety == {
            "PENDING": False, "RUNNING": False, "FAILED": False, "SUCCEEDED": True,
        }
    finally:
        engine.dispose()


def test_holding_history_backfill_and_downgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _isolate_settings: None,
) -> None:
    db_path = tmp_path / "history.db"
    cfg = _alembic_config(db_path, monkeypatch)
    command.upgrade(cfg, "0005")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        metadata = MetaData()
        portfolios = Table("portfolios", metadata, autoload_with=engine)
        jobs = Table("statement_imports", metadata, autoload_with=engine)
        txns = Table("transactions", metadata, autoload_with=engine)
        with engine.begin() as conn:
            conn.execute(portfolios.insert().values(id=1, name="Legacy", base_currency="USD"))
            conn.execute(jobs.insert().values(
                id=1, portfolio_id=1, status="SUCCEEDED", source_format="robinhood_csv",
                original_filename="old.csv", storage_key="old.raw", checksum="a" * 64,
                size_bytes=1, processed_rows=1, created_transactions=1,
                tickers_json='["AAA"]', warnings_json="[]", history_complete=True,
            ))
            for job_id in (None, 1):
                conn.execute(txns.insert().values(
                    portfolio_id=1, ticker="AAA", type="BUY", trade_date=date(2024, 1, 1),
                    currency="USD", quantity=1, price=100, fees=0, amount=0, split_ratio=1,
                    import_job_id=job_id,
                ))
        command.upgrade(cfg, "head")
        txns = Table("transactions", MetaData(), autoload_with=engine)
        with engine.connect() as conn:
            origins = conn.execute(select(txns.c.history_origin).order_by(txns.c.id)).scalars().all()
        assert origins == ["UNKNOWN", "OBSERVED"]
        command.downgrade(cfg, "0005")
        assert "history_origin" not in {c["name"] for c in inspect(engine).get_columns("transactions")}
        command.upgrade(cfg, "head")
    finally:
        engine.dispose()


def test_deletion_migration_preserves_active_rows_and_never_resurrects_deleted_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _isolate_settings: None,
) -> None:
    db_path = tmp_path / "deletion.db"
    cfg = _alembic_config(db_path, monkeypatch)
    command.upgrade(cfg, "0006")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    try:
        metadata = MetaData()
        portfolios = Table("portfolios", metadata, autoload_with=engine)
        txns = Table("transactions", metadata, autoload_with=engine)
        with engine.begin() as conn:
            conn.execute(portfolios.insert().values(id=1, name="Existing", base_currency="USD"))
            for txn_id in (1, 2):
                conn.execute(txns.insert().values(
                    id=txn_id, portfolio_id=1, ticker="AAA", type="BUY", trade_date=date(2024, 1, 1),
                    currency="USD", quantity=1, price=100, fees=0, amount=0, split_ratio=1,
                    history_origin="OBSERVED",
                ))
        command.upgrade(cfg, "head")
        txns = Table("transactions", MetaData(), autoload_with=engine)
        with engine.begin() as conn:
            assert conn.execute(select(txns.c.deleted_at)).scalars().all() == [None, None]
            conn.execute(txns.update().where(txns.c.id == 2).values(deleted_at=datetime.now(UTC)))
        command.downgrade(cfg, "0006")
        txns = Table("transactions", MetaData(), autoload_with=engine)
        with engine.connect() as conn:
            assert conn.execute(select(txns.c.id)).scalars().all() == [1]
        assert "deleted_at" not in txns.c
        command.upgrade(cfg, "head")
    finally:
        engine.dispose()
