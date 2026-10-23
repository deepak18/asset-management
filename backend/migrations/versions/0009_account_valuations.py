"""Add account metadata and reported valuations without modifying ledger facts."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "portfolios",
        sa.Column(
            "account_type",
            sa.String(24),
            nullable=False,
            server_default="UNKNOWN",
        ),
    )
    op.add_column("portfolios", sa.Column("custodian", sa.String(120), nullable=True))
    op.add_column("portfolios", sa.Column("external_account_id", sa.String(120), nullable=True))
    op.create_table(
        "securities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("instrument_type", sa.String(24), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
    )
    op.create_table(
        "security_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("source_code", sa.String(80), nullable=False),
        sa.Column("value", sa.String(240), nullable=False),
        sa.UniqueConstraint("source_code", "value", name="uq_security_alias"),
    )
    op.create_table(
        "account_valuations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("complete_snapshot", sa.Boolean(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_code", sa.String(80), nullable=False),
        sa.Column("source_reference", sa.String(240), nullable=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("portfolio_id", "as_of", name="uq_account_valuation_date"),
    )
    # Pin historical DDL independently of future ORM changes. SQLite stores exact text.
    decimal_type = sa.Numeric(28, 10).with_variant(sa.String(), "sqlite")
    op.create_table(
        "account_valuation_positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "valuation_id", sa.Integer(), sa.ForeignKey("account_valuations.id"), nullable=False
        ),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("quantity", decimal_type, nullable=False),
        sa.Column("reported_price", decimal_type, nullable=True),
        sa.Column("reported_value", decimal_type, nullable=False),
        sa.Column("cost_basis", decimal_type, nullable=True),
        sa.Column("source_reference", sa.String(240), nullable=True),
        sa.UniqueConstraint("valuation_id", "security_id", name="uq_valuation_security"),
    )


def downgrade() -> None:
    op.drop_table("account_valuation_positions")
    op.drop_table("account_valuations")
    op.drop_table("security_aliases")
    op.drop_table("securities")
    with op.batch_alter_table("portfolios") as batch:
        batch.drop_column("external_account_id")
        batch.drop_column("custodian")
        batch.drop_column("account_type")
