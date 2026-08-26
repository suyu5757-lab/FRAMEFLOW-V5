"""Alembic environment for the T02 offline Runtime MVP migration."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import context


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.schemas.runtime_mvp import metadata  # noqa: E402


config = context.config
target_metadata = metadata


def run_migrations_offline() -> None:
    """Emit SQL only; T02 deliberately refuses online database migration."""

    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Protect the existing production database from T02 online execution."""

    raise RuntimeError(
        "T02 migration skeleton is offline-only; use "
        "alembic -c core/migration/alembic.ini upgrade head --sql"
    )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
