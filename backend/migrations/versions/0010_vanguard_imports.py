"""Retain atomic retirement imports and observed source activity separately from trades."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retirement_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column(
            "valuation_id", sa.Integer(), sa.ForeignKey("account_valuations.id"), nullable=False
        ),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(120), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("preview_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("portfolio_id", "checksum", name="uq_retirement_checksum"),
    )
    op.create_table(
        "retirement_activity",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "import_id", sa.Integer(), sa.ForeignKey("retirement_imports.id"), nullable=False
        ),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("fact_json", sa.Text(), nullable=False),
    )
    op.create_index("ix_retirement_activity_fingerprint", "retirement_activity", ["fingerprint"])


def downgrade() -> None:
    op.drop_index("ix_retirement_activity_fingerprint", table_name="retirement_activity")
    op.drop_table("retirement_activity")
    op.drop_table("retirement_imports")
