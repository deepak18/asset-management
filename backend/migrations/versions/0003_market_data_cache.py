"""market data cache

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-26

Creates the ``market_data_cache`` table backing the read-through cache
(app/marketdata/cache.py). One row per (provider_code, data_type, symbol); the
fetched typed object is stored serialized in ``payload`` (TEXT). ``as_of`` is the
source's own timestamp (provenance / restatement auditing) and ``fetched_at`` is
when we stored it (TTL basis). Dialect-portable: TEXT + timezone-aware DateTime
work on both SQLite (unit tests) and PostgreSQL (production).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_data_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider_code", sa.String(length=40), nullable=False),
        sa.Column("data_type", sa.String(length=40), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider_code", "data_type", "symbol", name="uq_market_data_key"
        ),
    )


def downgrade() -> None:
    op.drop_table("market_data_cache")
