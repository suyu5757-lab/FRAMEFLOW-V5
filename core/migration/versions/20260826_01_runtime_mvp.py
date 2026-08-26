"""Create the provider-neutral FRAMEFLOW Runtime MVP schema.

Revision ID: 20260826_01
Revises:
"""

from __future__ import annotations

from alembic import op
from alembic import context
from sqlalchemy.schema import CreateTable

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
    """Create the 11-table MVP on the explicit candidate connection."""

    # Online env.py applies these before Alembic opens its migration
    # transaction.  journal_mode=WAL can implicitly commit in SQLite, so it
    # must not run inside the revision transaction.  Keep the statements in
    # offline SQL for reproducible dry-runs.
    if context.is_offline_mode():
        for statement in RUNTIME_PRAGMA_STATEMENTS:
            op.execute(statement.rstrip(";"))
        for table in metadata.sorted_tables:
            op.execute(CreateTable(table))
    else:
        metadata.create_all(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    """Drop only the candidate Runtime MVP tables in reverse dependency order."""

    if context.is_offline_mode():
        for table_name in reversed(RUNTIME_TABLE_NAMES):
            op.execute(f'DROP TABLE "{table_name}"')
    else:
        metadata.drop_all(op.get_bind(), checkfirst=False)
