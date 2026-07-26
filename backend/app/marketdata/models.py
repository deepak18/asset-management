"""SQLAlchemy model for the read-through market-data cache (PLAN.md §1.3).

One row = one cached fetch, uniquely identified by
``(provider_code, data_type, symbol)``. The typed object we fetched is stored
serialized in ``payload`` (JSON text); ``as_of`` records the source's own
timestamp (provenance) and ``fetched_at`` records when *we* stored it (the basis
for TTL freshness). Keeping the payload opaque here lets one table cache quotes,
profiles, and statement sets alike — the typing is enforced when the cache
service re-validates the payload back into its Pydantic schema on read.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MarketDataCacheEntry(Base):
    """A single cached market-data payload with provenance + fetch timestamps."""

    __tablename__ = "market_data_cache"
    __table_args__ = (
        UniqueConstraint("provider_code", "data_type", "symbol", name="uq_market_data_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_code: Mapped[str] = mapped_column(String(40))
    data_type: Mapped[str] = mapped_column(String(40))
    symbol: Mapped[str] = mapped_column(String(20))
    payload: Mapped[str] = mapped_column(Text)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

