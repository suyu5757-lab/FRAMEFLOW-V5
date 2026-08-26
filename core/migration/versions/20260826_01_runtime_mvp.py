"""Create the provider-neutral FRAMEFLOW Runtime MVP schema.

Revision ID: 20260826_01
Revises:
"""

from __future__ import annotations

from alembic import op
from sqlalchemy.schema import CreateTable, DropTable

from core.schemas.runtime_mvp import (
    RUNTIME_PRAGMA_STATEMENTS,
    RUNTIME_TABLE_NAMES,
    metadata,
)


revision = "20260826_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Emit the 11-table MVP and required SQLite pragmas in offline mode."""

    for statement in RUNTIME_PRAGMA_STATEMENTS:
        op.execute(statement.rstrip(";"))
    for table in metadata.sorted_tables:
        op.execute(CreateTable(table))


def downgrade() -> None:
    """Emit the reverse table order; online execution is blocked by env.py."""

    for table_name in reversed(RUNTIME_TABLE_NAMES):
        op.execute(DropTable(metadata.tables[table_name]))
