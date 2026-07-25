"""enable pgvector extension

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-25

Enables the pgvector extension so later phases (document embeddings) can store
``vector`` columns. Guarded by dialect: on SQLite (unit tests) this is a no-op,
so the migration chain still applies cleanly offline; on PostgreSQL it runs
``CREATE EXTENSION``.
Kept as a versioned migration (not just a container init script)
so it also applies to managed/cloud Postgres where init scripts don't run.
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP EXTENSION IF EXISTS vector")
