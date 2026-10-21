"""Retain transaction deletion tombstones for history and retry safety."""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # Dropping tombstones must not resurrect events hidden from the ledger.
    op.execute("DELETE FROM transactions WHERE deleted_at IS NOT NULL")
    with op.batch_alter_table("transactions") as batch:
        batch.drop_column("deleted_at")
