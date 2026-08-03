"""statement imports

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-02

Creates ``statement_imports``, the metadata/progress table backing asynchronous
broker-statement uploads (app/portfolio/models.py::StatementImport).

Only metadata lives in the database; the uploaded bytes are written to the blob
store and referenced by ``storage_key``. ``checksum`` (SHA-256 of the upload) is
indexed so a re-upload of an identical file can be detected before it double-counts
an entire ledger. Small JSON arrays (tickers, warnings) are stored as TEXT to keep
the schema dialect-portable across SQLite (unit tests) and PostgreSQL (production).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "statement_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "portfolio_id",
            sa.Integer(),
            sa.ForeignKey("portfolios.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, index=True),
        sa.Column("source_format", sa.String(length=40), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=120), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False, index=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_rows", sa.Integer(), nullable=True),
        sa.Column("processed_rows", sa.Integer(), nullable=False),
        sa.Column("created_transactions", sa.Integer(), nullable=False),
        sa.Column("tickers_json", sa.Text(), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("statement_imports")
