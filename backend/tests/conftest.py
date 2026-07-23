"""Shared fixtures for the backend test suite.

Provider boundaries are mocked/faked here (there are none in the pure calculators
yet). We expose a couple of small FX tables so currency-normalization paths are
exercised without any network access.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.portfolio.models  # noqa: F401  (import registers ORM tables on Base.metadata)
from app.core.currency import FxRate, FxRateTable
from app.core.database import Base


@pytest.fixture
def usd_only_fx() -> FxRateTable:
    """A USD-base table with no cross rates — pure single-currency math."""

    return FxRateTable(base_currency="USD")


@pytest.fixture
def usd_inr_fx() -> FxRateTable:
    """USD-base table with a couple of dated INR rates for mixed-currency tests.

    1 INR == 0.012 USD on 2026-01-10; 1 INR == 0.011 USD on 2026-06-10.
    """

    return FxRateTable(
        base_currency="USD",
        rates=(
            FxRate(currency="INR", as_of=date(2026, 1, 10), rate_to_base=Decimal("0.012")),
            FxRate(currency="INR", as_of=date(2026, 6, 10), rate_to_base=Decimal("0.011")),
        ),
    )


@pytest_asyncio.fixture
async def async_session() -> AsyncIterator[AsyncSession]:
    """Disposable in-memory SQLite session for offline provider/model unit tests.

    A ``StaticPool`` keeps the single in-memory connection alive across the fixture
    so the schema created by ``create_all`` is visible to the session. Real
    Postgres/pgvector wiring is exercised separately under ``@pytest.mark.integration``.
    """

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session

    await engine.dispose()
