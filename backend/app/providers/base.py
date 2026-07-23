"""Provider interfaces — the ONLY sanctioned I/O boundary.

Domain logic (the calculators) depends on these *interfaces*, never on SQLAlchemy
sessions, HTTP clients, or MCP packets. Concretely, a provider takes raw storage
and hands back **typed Pydantic domain objects** the calculators already understand.
This is what lets us swap Postgres, a mock, or a future service in without touching
a single line of financial math.

We use ``typing.Protocol`` (structural typing) rather than an ABC so implementations
don't need to inherit anything — a class "is" a ``PortfolioProvider`` simply by having
the right async methods. That keeps the boundary decoupled and easy to fake in tests.
"""

from __future__ import annotations

from typing import Protocol

from app.portfolio.schemas import HoldingInfo, PortfolioSummary, Transaction


class PortfolioProvider(Protocol):
    """Read access to a portfolio's ledger, holdings, and identity."""

    async def get_portfolio(self, portfolio_id: int) -> PortfolioSummary | None:
        """Return the portfolio's identity/base currency, or ``None`` if absent."""
        ...

    async def list_transactions(self, portfolio_id: int) -> list[Transaction]:
        """Return all ledger events for the portfolio as typed domain objects."""
        ...

    async def list_holdings(self, portfolio_id: int) -> list[HoldingInfo]:
        """Return the portfolio's tracked securities + classification metadata."""
        ...