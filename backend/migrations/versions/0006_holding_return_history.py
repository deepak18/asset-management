"""Persist snapshot/observed history for holding returns.

Legacy unowned events may be snapshots; their cash-flow history cannot safely be
inferred. Owned import rows retain their separate job completeness checks.
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("history_origin", sa.String(20), nullable=False, server_default="UNKNOWN"),
    )
    op.execute(
        "UPDATE transactions SET history_origin = 'OBSERVED' WHERE import_job_id IS NOT NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.drop_column("history_origin")
