"""initial portfolio schema

Revision ID: 0001
Revises:
Create Date: 2026-07-25

Creates the portfolio domain tables (portfolios, holdings, transactions,
cash_balances) mirroring app/portfolio/models.py. Money/quantity columns use
NUMERIC(28, 10) for exact decimal arithmetic (native NUMERIC on Postgres); the
ORM swaps a TEXT-backed variant for SQLite, but the physical migration stays
dialect-portable here.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Exact decimal for all money/quantity columns (see models.ExactDecimal).
_MONEY = sa.Numeric(28, 10)


def upgrade() -> None:
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "holdings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("sector", sa.String(length=80), nullable=True),
        sa.Column("industry", sa.String(length=80), nullable=True),
        sa.UniqueConstraint("portfolio_id", "ticker", name="uq_holding_ticker"),
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column(
            "type",
            sa.Enum("BUY", "SELL", "DIVIDEND", "FEE", "SPLIT", name="transaction_type"),
            nullable=False,
        ),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("quantity", _MONEY, nullable=False),
        sa.Column("price", _MONEY, nullable=False),
        sa.Column("fees", _MONEY, nullable=False),
        sa.Column("amount", _MONEY, nullable=False),
        sa.Column("split_ratio", _MONEY, nullable=False),
    )

    op.create_table(
        "cash_balances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("balance", _MONEY, nullable=False),
        sa.UniqueConstraint("portfolio_id", "currency", name="uq_cash_currency"),
    )


def downgrade() -> None:
    op.drop_table("cash_balances")
    op.drop_table("transactions")
    op.drop_table("holdings")
    op.drop_table("portfolios")
    # Drop the PostgreSQL native ENUM type (no-op on SQLite).
    sa.Enum(name="transaction_type").drop(op.get_bind(), checkfirst=True)

