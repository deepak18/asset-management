"""Provider interface for market data.

Business code depends on this ``Protocol``, never on AlphaVantage, MCP, or HTTP
directly. A concrete adapter (AlphaVantage-over-MCP, wrapped by the read-through
cache) is supplied in a later slice; swapping the source — or faking it in tests —
requires no change to any consumer.
"""

from __future__ import annotations

from typing import Protocol

from app.marketdata.schemas import (
    CompanyProfile,
    FinancialStatements,
    MarketDataType,
    Quote,
)


class MarketDataProvider(Protocol):
    """Read access to pricing + fundamentals for a ticker (cache-first)."""

    async def get_quote(self, ticker: str) -> Quote | None:
        """Return the latest known price for ``ticker``, or ``None`` if unknown."""
        ...

    async def get_company_profile(self, ticker: str) -> CompanyProfile | None:
        """Return descriptive company metadata, or ``None`` if unknown."""
        ...

    async def get_financial_statements(
        self, ticker: str, statement_type: MarketDataType
    ) -> FinancialStatements | None:
        """Return the multi-period statement set of ``statement_type``, or ``None``."""
        ...
