"""SQLite-consistent backup and restore helpers for T02-R.

All source reads use SQLite's read-only URI mode.  The helpers refuse the
production database as a restore target; production can only be a read-only
backup source during this task.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .candidate_b_lifecycle import assert_candidate_b_database_open_allowed

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_DATABASE = (PROJECT_ROOT / "data" / "frameflow.db").resolve()


class BackupError(RuntimeError):
    """Raised when a backup or restore safety invariant fails."""


def _resolve(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _guard_restore_target(path: Path) -> None:
    if path == PRODUCTION_DATABASE:
        raise BackupError(
            f"T02-R refuses to restore into production: {PRODUCTION_DATABASE}; "
            "production cutover is deferred to T03-R"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_only(path: Path) -> sqlite3.Connection:
    assert_candidate_b_database_open_allowed(path)
    if not path.is_file():
        raise BackupError(f"SQLite source does not exist: {path}")
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True
        )
        connection.row_factory = sqlite3.Row
        return connection
    except Exception:
        if connection is not None:
            connection.close()
        raise


def _table_names(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]


def _integrity(connection: sqlite3.Connection) -> tuple[str, list[tuple[Any, ...]]]:
    integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    foreign_keys = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()]
    return integrity, foreign_keys


def _schema_version(connection: sqlite3.Connection) -> int | str | None:
    for table in ("schema_migrations", "alembic_version"):
        if table not in _table_names(connection):
            continue
        rows = connection.execute(f'SELECT * FROM "{table}"').fetchall()
        if not rows:
            return None
        values = [row[0] for row in rows]
        try:
            return max(int(value) for value in values)
        except (TypeError, ValueError):
            return str(values[-1])
    return None


def verify_backup(path: Path | str) -> dict[str, Any]:
    """Open a backup read-only and return integrity/schema metadata."""

    backup_path = _resolve(path)
    connection = _read_only(backup_path)
    try:
        integrity, foreign_keys = _integrity(connection)
        return {
            "backup_path": str(backup_path),
            "backup_sha256": _sha256(backup_path),
            "source_schema_version": _schema_version(connection),
            "table_count": len(_table_names(connection)),
            "tables": _table_names(connection),
            "integrity_check": integrity,
            "foreign_key_violations": foreign_keys,
            "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
            "foreign_keys": connection.execute("PRAGMA foreign_keys").fetchone()[0],
            "busy_timeout": connection.execute("PRAGMA busy_timeout").fetchone()[0],
        }
    finally:
        connection.close()


def create_backup(source_path: Path | str, backup_path: Path | str) -> dict[str, Any]:
    """Create a consistent SQLite backup without writing the source."""

    source = _resolve(source_path)
    backup = _resolve(backup_path)
    assert_candidate_b_database_open_allowed(backup)
    _guard_restore_target(backup)
    if source == backup:
        raise BackupError("backup target must differ from source")
    if backup.exists():
        raise BackupError(f"refusing to overwrite existing backup: {backup}")
    backup.parent.mkdir(parents=True, exist_ok=True)
    source_sha_before = _sha256(source)
    source_connection = _read_only(source)
    destination: sqlite3.Connection | None = None
    try:
        destination = sqlite3.connect(backup)
        source_connection.backup(destination, pages=256, sleep=0.05)
        destination.commit()
    finally:
        if destination is not None:
            destination.close()
        source_connection.close()
    source_sha_after = _sha256(source)
    if source_sha_before != source_sha_after:
        raise BackupError(
            "source database changed during backup; candidate evidence is invalid"
        )
    verified = verify_backup(backup)
    if verified["integrity_check"] != "ok" or verified["foreign_key_violations"]:
        raise BackupError(f"backup integrity verification failed: {verified}")
    return {
        "source_path": str(source),
        "backup_path": str(backup),
        "created_at": datetime.now(UTC).isoformat(),
        "source_sha256": source_sha_before,
        "backup_sha256": verified["backup_sha256"],
        "source_schema_version": verified["source_schema_version"],
        "table_count": verified["table_count"],
        "integrity_check": verified["integrity_check"],
        "foreign_key_violations": verified["foreign_key_violations"],
        "journal_mode": verified["journal_mode"],
        "foreign_keys": verified["foreign_keys"],
        "busy_timeout": verified["busy_timeout"],
    }


def restore_backup(backup_path: Path | str, target_path: Path | str) -> dict[str, Any]:
    """Restore a verified backup into a non-production candidate path."""

    backup = _resolve(backup_path)
    target = _resolve(target_path)
    assert_candidate_b_database_open_allowed(target)
    _guard_restore_target(target)
    if backup == target:
        raise BackupError("restore target must differ from backup source")
    verified = verify_backup(backup)
    if verified["integrity_check"] != "ok" or verified["foreign_key_violations"]:
        raise BackupError("refusing to restore an invalid backup")
    target.parent.mkdir(parents=True, exist_ok=True)
    source_connection = _read_only(backup)
    destination: sqlite3.Connection | None = None
    try:
        destination = sqlite3.connect(target)
        source_connection.backup(destination, pages=256, sleep=0.05)
        destination.commit()
    finally:
        if destination is not None:
            destination.close()
        source_connection.close()
    restored = verify_backup(target)
    if restored["integrity_check"] != "ok" or restored["foreign_key_violations"]:
        raise BackupError(f"restored candidate failed integrity verification: {restored}")
    return {
        "backup_path": str(backup),
        "target_path": str(target),
        "backup_sha256": verified["backup_sha256"],
        "target_sha256": restored["backup_sha256"],
        "integrity_check": restored["integrity_check"],
        "table_count": restored["table_count"],
        "foreign_key_violations": restored["foreign_key_violations"],
    }


def write_manifest(path: Path | str, manifest: dict[str, Any]) -> None:
    """Write a non-secret migration manifest to an explicitly provided path."""

    output = _resolve(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
