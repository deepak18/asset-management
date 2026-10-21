"""Persist explicit, holding-scoped history confirmations."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("holdings", sa.Column("history_review_token", sa.String(64), nullable=True))
    op.add_column(
        "holdings", sa.Column("history_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("holdings") as batch:
        batch.drop_column("history_confirmed_at")
        batch.drop_column("history_review_token")
