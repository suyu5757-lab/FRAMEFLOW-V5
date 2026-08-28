"""The single V5 Runtime database ownership boundary.

This module is intentionally small: it does not migrate a database and it
does not provide a second persistence implementation.  It only resolves the
canonical production path, detects whether that path is a V5 candidate, and
opens the existing :class:`StateStore` with the required SQLite settings.

Legacy V3 databases are rejected before SQLAlchemy opens them.  Migration and
test callers may opt into a non-production candidate path explicitly.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from core.schemas.runtime_mvp import RUNTIME_TABLE_NAMES
from core.migration.candidate_b_lifecycle import assert_candidate_b_database_open_allowed

from .store import DEFAULT_DATABASE_PATH, StateStore


CANONICAL_DATABASE_PATH = DEFAULT_DATABASE_PATH.resolve()
_LEGACY_MARKERS = frozenset(
    {
        "schema_migrations",
        "provider_profiles",
        "capability_bindings",
        "workflow_runs_v3",
        "render_jobs_v6",
    }
)
_V5_TABLES = frozenset(RUNTIME_TABLE_NAMES)


class RuntimeOwnershipError(RuntimeError):
    """Raised when a caller would give a legacy database writable ownership."""


def canonical_database_path() -> Path:
    """Return the only production database path accepted by Runtime."""

    return CANONICAL_DATABASE_PATH


def _resolve(path: Path | str | None) -> Path:
    return (CANONICAL_DATABASE_PATH if path is None else Path(path)).expanduser().resolve(
        strict=False
    )


def _read_only(path: Path) -> sqlite3.Connection:
    assert_candidate_b_database_open_allowed(path)
    if not path.is_file():
        raise RuntimeOwnershipError(f"runtime database does not exist: {path}")
    connection: sqlite3.Connection | None = None
    try:
        # ``immutable=1`` keeps inspection of a stopped legacy database from
        # creating ``-wal``/``-shm`` sidecars.  If a live WAL is already
        # present, a normal read-only connection is required to see its
        # schema/data; this is used by runtime health checks while a store is
        # still open.
        query = "mode=ro"
        if not Path(f"{path}-wal").exists():
            query += "&immutable=1"
        connection = sqlite3.connect(
            f"file:{path.as_posix()}?{query}", uri=True
        )
        connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
    except sqlite3.DatabaseError as exc:
        if connection is not None:
            connection.close()
        raise RuntimeOwnershipError(f"runtime database is not readable: {path}") from exc
    connection.row_factory = sqlite3.Row
    return connection


def inspect_database(path: Path | str | None = None) -> dict[str, Any]:
    """Inspect a database without opening it for writes.

    ``LEGACY_V3`` and ``MIXED`` are not accepted by ``open_runtime_store``.
    The explicit status is useful to cutover tooling and to review reports.
    """

    resolved = _resolve(path)
    connection = _read_only(resolved)
    try:
        tables = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        )
        table_set = set(tables)
        has_v5 = _V5_TABLES.issubset(table_set)
        has_legacy = bool(_LEGACY_MARKERS & table_set)
        if has_v5 and not has_legacy:
            schema = "V5_RUNTIME"
        elif has_legacy:
            schema = "LEGACY_V3" if not has_v5 else "MIXED"
        else:
            schema = "UNKNOWN"
        row_counts = {
            table: int(
                connection.execute(
                    f'SELECT COUNT(*) FROM "{table.replace(chr(34), chr(34) * 2)}"'
                ).fetchone()[0]
            )
            for table in tables
        }
        return {
            "path": str(resolved),
            "schema": schema,
            "tables": tables,
            "domain_tables": tuple(sorted(_V5_TABLES & table_set)),
            "row_counts": row_counts,
            "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
            "foreign_keys": connection.execute("PRAGMA foreign_keys").fetchone()[0],
            "busy_timeout": connection.execute("PRAGMA busy_timeout").fetchone()[0],
            "integrity_check": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_violations": [
                tuple(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()
            ],
        }
    finally:
        connection.close()


def open_runtime_store(
    path: Path | str | None = None,
    *,
    initialize: bool = False,
    candidate: bool = False,
) -> StateStore:
    """Open the V5 StateStore through one controlled ownership boundary.

    The production path can only be opened when it already contains the V5
    domain schema.  It can never be initialized here.  A non-production path
    is allowed only when ``candidate=True``; this is for isolated migration
    rehearsals and tests, never for application runtime configuration.
    """

    resolved = _resolve(path)
    is_canonical = resolved == CANONICAL_DATABASE_PATH
    if not is_canonical and not candidate:
        raise RuntimeOwnershipError(
            "non-canonical database paths require candidate=True and are not runtime-owned"
        )
    if is_canonical and initialize:
        raise RuntimeOwnershipError(
            "production initialization is forbidden; use a verified cutover candidate"
        )
    if not resolved.is_file():
        if is_canonical:
            raise RuntimeOwnershipError(
                "production V5 database is missing; cutover must place a verified candidate first"
            )
        if not initialize:
            raise RuntimeOwnershipError(f"candidate database does not exist: {resolved}")
        store = StateStore(resolved, initialize=True)
    else:
        info = inspect_database(resolved)
        if info["schema"] != "V5_RUNTIME":
            raise RuntimeOwnershipError(
                f"refusing writable V5 ownership for {info['schema']} database: {resolved}"
            )
        store = StateStore(resolved, initialize=False)
    try:
        pragmas = store.pragmas()
        if pragmas != {"journal_mode": "wal", "foreign_keys": 1, "busy_timeout": 5000}:
            raise RuntimeOwnershipError(
                f"V5 runtime PRAGMA gate failed for {resolved}: {pragmas}"
            )
    except Exception:
        store.dispose()
        raise
    return store


__all__ = [
    "CANONICAL_DATABASE_PATH",
    "RuntimeOwnershipError",
    "canonical_database_path",
    "inspect_database",
    "open_runtime_store",
]
