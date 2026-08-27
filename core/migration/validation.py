"""Read-only validation for a V5 Runtime MVP candidate database."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect

from core.schemas.runtime_mvp import RUNTIME_TABLE_NAMES, metadata


INTERNAL_TABLES = {"alembic_version", "sqlite_sequence"}


class CandidateValidationError(RuntimeError):
    """Raised when a candidate does not match the Runtime MVP contract."""


def _read_only(path: Path | str) -> sqlite3.Connection:
    candidate = Path(path).expanduser().resolve(strict=False)
    if not candidate.is_file():
        raise CandidateValidationError(f"candidate database does not exist: {candidate}")
    # Candidate validation must see a just-created WAL if migration has not
    # checkpointed it yet.  The connection is always closed in validate_candidate's
    # finally block; final swap additionally requires a real rename probe.
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"file:{candidate.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection
    except Exception:
        if connection is not None:
            connection.close()
        raise


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _type_name(column: Any) -> str:
    return str(column.type.compile(dialect=sqlite_dialect())).upper()


def _table_snapshot(connection: sqlite3.Connection, table_name: str) -> dict[str, Any]:
    quoted = _quote(table_name)
    columns = [dict(row) for row in connection.execute(f"PRAGMA table_info({quoted})").fetchall()]
    foreign_keys = [dict(row) for row in connection.execute(f"PRAGMA foreign_key_list({quoted})").fetchall()]
    indexes = [dict(row) for row in connection.execute(f"PRAGMA index_list({quoted})").fetchall()]
    return {"columns": columns, "foreign_keys": foreign_keys, "indexes": indexes}


def validate_candidate(path: Path | str) -> dict[str, Any]:
    """Compare candidate tables, columns, nullability, PKs and FKs to metadata."""

    candidate = Path(path).expanduser().resolve(strict=False)
    connection = _read_only(candidate)
    errors: list[str] = []
    try:
        actual_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected_tables = set(RUNTIME_TABLE_NAMES)
        domain_tables = actual_tables - INTERNAL_TABLES
        if domain_tables != expected_tables:
            errors.append(
                f"domain tables differ: expected={sorted(expected_tables)} actual={sorted(domain_tables)}"
            )

        table_details: dict[str, Any] = {}
        for table_name in RUNTIME_TABLE_NAMES:
            if table_name not in actual_tables:
                continue
            actual = _table_snapshot(connection, table_name)
            table_details[table_name] = actual
            actual_by_name = {str(row["name"]): row for row in actual["columns"]}
            expected_table = metadata.tables[table_name]
            expected_names = {column.name for column in expected_table.columns}
            if set(actual_by_name) != expected_names:
                errors.append(
                    f"{table_name} columns differ: expected={sorted(expected_names)} actual={sorted(actual_by_name)}"
                )
            for column in expected_table.columns:
                row = actual_by_name.get(column.name)
                if row is None:
                    continue
                expected_type = _type_name(column)
                actual_type = str(row["type"]).upper()
                if expected_type != actual_type:
                    errors.append(
                        f"{table_name}.{column.name} type differs: expected={expected_type} actual={actual_type}"
                    )
                if bool(row["pk"]) != bool(column.primary_key):
                    errors.append(f"{table_name}.{column.name} primary-key flag differs")
                if bool(row["notnull"]) != (not bool(column.nullable)):
                    errors.append(f"{table_name}.{column.name} nullable flag differs")

            expected_fks = sorted(
                (element.parent.name, element.column.table.name, element.column.name)
                for column in expected_table.columns
                for element in column.foreign_keys
            )
            actual_fks = sorted(
                (str(row["from"]), str(row["table"]), str(row["to"]))
                for row in actual["foreign_keys"]
            )
            if actual_fks != expected_fks:
                errors.append(
                    f"{table_name} foreign keys differ: expected={expected_fks} actual={actual_fks}"
                )

        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key_violations = [
            tuple(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()
        ]
        pragmas = {
            "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
            "foreign_keys": connection.execute("PRAGMA foreign_keys").fetchone()[0],
            "busy_timeout": connection.execute("PRAGMA busy_timeout").fetchone()[0],
        }
        if integrity != "ok":
            errors.append(f"integrity_check={integrity}")
        if foreign_key_violations:
            errors.append(f"foreign_key_check={foreign_key_violations}")
        if str(pragmas["journal_mode"]).lower() != "wal":
            errors.append(f"journal_mode={pragmas['journal_mode']}")
        if int(pragmas["foreign_keys"]) != 1:
            errors.append(f"foreign_keys={pragmas['foreign_keys']}")
        if int(pragmas["busy_timeout"]) != 5000:
            errors.append(f"busy_timeout={pragmas['busy_timeout']}")
        result = {
            "path": str(candidate),
            "all_tables": sorted(actual_tables),
            "domain_tables": sorted(domain_tables),
            "internal_tables": sorted(actual_tables & INTERNAL_TABLES),
            "table_details": table_details,
            "integrity_check": integrity,
            "foreign_key_violations": foreign_key_violations,
            "pragmas": pragmas,
            "errors": errors,
        }
    finally:
        connection.close()
    return result


def assert_candidate_valid(path: Path | str) -> dict[str, Any]:
    result = validate_candidate(path)
    if result["errors"]:
        raise CandidateValidationError("; ".join(result["errors"]))
    return result
