"""Alembic environment for the side-by-side Runtime MVP migration.

The database target is deliberately explicit.  The empty URL in alembic.ini
is not a usable default, and a production database path is rejected in both
offline and online modes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.schemas.runtime_mvp import metadata  # noqa: E402


config = context.config
target_metadata = metadata
PRODUCTION_DATABASE = (PROJECT_ROOT / "data" / "frameflow.db").resolve()


def _database_url() -> str:
    """Return an explicit SQLite URL and refuse the production path."""

    x_args = context.get_x_argument(as_dictionary=True)
    value = x_args.get("db_path") or os.environ.get("DATABASE_URL")
    if value is None or not str(value).strip():
        value = config.get_main_option("sqlalchemy.url").strip()
    if not value:
        raise RuntimeError(
            "T02-R requires an explicit candidate database: "
            "alembic -x db_path=<candidate.db> ..."
        )
    value = str(value).strip()
    url = value if value.startswith("sqlite:") else f"sqlite:///{Path(value).resolve(strict=False).as_posix()}"
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or not parsed.database or parsed.database == ":memory:":
        raise RuntimeError("T02-R accepts only an explicit file-backed SQLite candidate database")
    database_path = Path(parsed.database).resolve(strict=False)
    if database_path == PRODUCTION_DATABASE:
        raise RuntimeError(
            f"T02-R refuses the production database path: {PRODUCTION_DATABASE}; "
            "production cutover is deferred to T03-R"
        )
    return url


def run_migrations_offline() -> None:
    """Emit SQL for an explicitly named candidate target."""

    url = _database_url()
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
    """Run online only against an explicit, non-production candidate."""

    url = _database_url()
    connectable = create_engine(url, future=True)
    try:
        with connectable.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("PRAGMA busy_timeout=5000")
            # Keep connection setup outside Alembic's migration transaction.
            # SQLite PRAGMA statements may leave an implicit transaction open.
            connection.commit()
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                render_as_batch=True,
                transactional_ddl=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
