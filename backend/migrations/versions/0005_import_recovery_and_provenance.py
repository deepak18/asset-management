"""Track classification provenance, import ownership, and unresolved records."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "holdings",
        sa.Column("classification_source", sa.String(20), nullable=False, server_default="NONE"),
    )
    op.execute(
        "UPDATE holdings SET classification_source = 'MANUAL' "
        "WHERE sector IS NOT NULL OR industry IS NOT NULL"
    )
    op.add_column(
        "statement_imports",
        sa.Column("history_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Legacy partial writes have no ownership tags; deleting them would be unsafe.
    op.add_column(
        "statement_imports",
        sa.Column("retry_safe", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.execute("UPDATE statement_imports SET retry_safe = false WHERE status != 'SUCCEEDED'")
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column("import_job_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_transaction_import", "statement_imports", ["import_job_id"], ["id"]
        )
        batch.create_index("ix_transactions_import_job_id", ["import_job_id"])
    op.create_table(
        "import_unresolved_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("statement_imports.id"), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), sa.ForeignKey("portfolios.id"), nullable=False),
        sa.Column("ticker", sa.String(20), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("import_id", "source_line", name="uq_import_issue_line"),
        sa.Column("source_line", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_import_unresolved_items_import_id", "import_unresolved_items", ["import_id"]
    )
    op.create_index(
        "ix_import_unresolved_items_portfolio_id", "import_unresolved_items", ["portfolio_id"]
    )


def downgrade() -> None:
    op.drop_table("import_unresolved_items")
    with op.batch_alter_table("transactions") as batch:
        batch.drop_index("ix_transactions_import_job_id")
        batch.drop_constraint("fk_transaction_import", type_="foreignkey")
        batch.drop_column("import_job_id")
    op.drop_column("statement_imports", "retry_safe")
    op.drop_column("statement_imports", "history_complete")
    op.drop_column("holdings", "classification_source")
