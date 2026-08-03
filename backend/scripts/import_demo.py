"""End-to-end demo: create a portfolio, upload a Robinhood CSV, read analytics.

Runs the real FastAPI app in-process against a throwaway in-memory database, so it
needs no Docker, no network, and no seeded data. Use it to sanity-check a statement
export before uploading it through the UI:

    uv run python scripts/import_demo.py                 # built-in sample CSV
    uv run python scripts/import_demo.py path/to/my.csv  # your own export

Nothing is written to your real database.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.marketdata.models  # noqa: F401  (registers cache table on Base.metadata)
import app.portfolio.models  # noqa: F401  (registers ORM tables on Base.metadata)
from app.api.deps import get_market_data_provider, get_session, get_statement_storage
from app.core.database import Base
from app.main import create_app
from app.storage.local_disk import LocalDiskStatementStorage

SAMPLE_CSV = (
    b"Activity Date,Process Date,Settle Date,Instrument,Description,"
    b"Trans Code,Quantity,Price,Amount\n"
    b"06/01/2022,06/01/2022,06/01/2022,NVDA,NVIDIA Corp,CDIV,,,$3.00\n"
    b"03/04/2021,03/05/2021,03/08/2021,NVDA,NVIDIA Corp,Sell,2,$200.00,$400.00\n"
    b"01/02/2020,01/03/2020,01/06/2020,NVDA,NVIDIA Corp,Buy,5,$100.00,($500.00)\n"
    b"06/02/2022,06/02/2022,06/02/2022,,ACH Deposit,ACH,,,$500.00\n"
)


async def main(csv_bytes: bytes) -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    api = create_app()
    api.state.session_factory = factory  # background tasks resolve this themselves

    async def _session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    api.dependency_overrides[get_session] = _session
    api.dependency_overrides[get_market_data_provider] = lambda: None  # stay offline

    with tempfile.TemporaryDirectory() as tmp:
        api.dependency_overrides[get_statement_storage] = (
            lambda: LocalDiskStatementStorage(Path(tmp))
        )

        transport = ASGITransport(app=api)
        async with AsyncClient(transport=transport, base_url="http://demo") as client:
            created = await client.post(
                "/api/v1/portfolios", json={"name": "Demo", "base_currency": "USD"}
            )
            pid = created.json()["id"]
            print(f"created portfolio {pid}")

            accepted = await client.post(
                f"/api/v1/portfolios/{pid}/imports?source_format=robinhood_csv",
                files={"file": ("statement.csv", csv_bytes, "text/csv")},
            )
            print(f"\nupload -> HTTP {accepted.status_code} (accepted, queued)")
            if accepted.status_code != 202:
                print(json.dumps(accepted.json(), indent=2))
                await engine.dispose()
                return
            job_id = accepted.json()["id"]

            status = await client.get(f"/api/v1/portfolios/{pid}/imports/{job_id}")
            print("\nfinal job status:")
            print(json.dumps(status.json(), indent=2))

            analytics = await client.get(f"/api/v1/portfolios/{pid}/analytics")
            body = analytics.json()
            print("\npositions:")
            for pos in body["positions"]:
                print(
                    f"  {pos['ticker']}: open={pos['open_quantity']} "
                    f"cost={pos['open_cost_basis_base']} "
                    f"realized={pos['realized_pnl_base']} "
                    f"dividends={pos['dividends_base']}"
                )
            print(f"\nmoney-weighted return (XIRR): {body['money_weighted_return']}")

    await engine.dispose()


if __name__ == "__main__":
    data = Path(sys.argv[1]).read_bytes() if len(sys.argv) > 1 else SAMPLE_CSV
    asyncio.run(main(data))
