"""Read-only compatibility access for the archived V3 database.

The adapter exists for historical SH records that are not valid ShotSpec v2.2
and therefore cannot be silently inserted into the V5 ``shots`` table.  It
uses SQLite's read-only URI mode on every connection and has no write API.
"""

from __future__ import annotations

import json
import sqlite3
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from scripts.migrate_shot_spec_v1_to_v2_2 import migrate_shot_spec_v1_to_v2_2


SHOT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "shot_spec_v2.2.schema.json"
)
SHOT_VALIDATOR = Draft202012Validator(json.loads(SHOT_SCHEMA_PATH.read_text(encoding="utf-8")))
LEGACY_READ_ONLY_COMPAT = "LEGACY_READ_ONLY_COMPAT"
MIGRATE_TO_V5 = "MIGRATE_TO_V5"
PROVEN_ARCHIVE_ONLY = "PROVEN_ARCHIVE_ONLY"
UNACCOUNTED = "UNACCOUNTED"


class LegacyReadOnlyError(RuntimeError):
    """Raised for every attempted write through the legacy compatibility path."""


def _json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _shot_id(value: Mapping[str, Any]) -> str | None:
    for key in ("id", "shot_id", "shotId"):
        item = value.get(key)
        if item is not None and str(item).strip():
            return str(item)
    return None


class LegacyReadOnlyCompatibility:
    """Expose historical embedded shots without any writable connection."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser().resolve(strict=False)
        if not self.path.is_file():
            raise LegacyReadOnlyError(f"legacy archive does not exist: {self.path}")

    def _connection(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(
                f"file:{self.path.as_posix()}?mode=ro&immutable=1", uri=True, timeout=5
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
            return connection
        except sqlite3.DatabaseError as exc:
            raise LegacyReadOnlyError(f"legacy archive is not readable: {self.path}") from exc

    @contextmanager
    def connection(self):
        """Yield one read-only SQLite connection for compatibility probes."""

        connection = self._connection()
        try:
            yield connection
        finally:
            connection.close()

    def list_shots(self) -> list[dict[str, Any]]:
        connection = self._connection()
        result: list[dict[str, Any]] = []
        try:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "projects" not in tables:
                return result
            for project in connection.execute(
                "SELECT id, document_json FROM projects ORDER BY id"
            ).fetchall():
                document = _json(project["document_json"])
                shots = document.get("shots") if isinstance(document, dict) else None
                if not isinstance(shots, list):
                    continue
                for raw in shots:
                    if not isinstance(raw, dict):
                        continue
                    shot_id = _shot_id(raw)
                    if not shot_id:
                        continue
                    result.append(
                        {
                            "id": shot_id,
                            "project_id": str(project["id"]),
                            "legacy_status": raw.get("status"),
                            "shot_spec_v1": deepcopy(raw),
                            "source_path": str(self.path),
                        }
                    )
            return result
        finally:
            connection.close()

    def get_shot(self, shot_id: str) -> dict[str, Any] | None:
        return next((item for item in self.list_shots() if item["id"] == shot_id), None)

    def write(self, *_args: Any, **_kwargs: Any) -> None:
        raise LegacyReadOnlyError("legacy compatibility archive is read-only")

    def write_shot(self, *_args: Any, **_kwargs: Any) -> None:
        self.write(*_args, **_kwargs)

    def __enter__(self) -> "LegacyReadOnlyCompatibility":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


def account_legacy_shots(
    path: Path | str, shot_ids: list[str] | tuple[str, ...]
) -> dict[str, Any]:
    """Account for every required historical shot before cutover.

    A record that validates as v2.2 is safe to migrate.  A record with an
    invalid/unfinished legacy status remains available through the explicit
    read-only adapter.  Missing records are ``UNACCOUNTED`` and block cutover.
    """

    adapter = LegacyReadOnlyCompatibility(path)
    by_id = {item["id"]: item for item in adapter.list_shots()}
    records: list[dict[str, Any]] = []
    counts = {MIGRATE_TO_V5: 0, LEGACY_READ_ONLY_COMPAT: 0, PROVEN_ARCHIVE_ONLY: 0, UNACCOUNTED: 0}
    for shot_id in shot_ids:
        record = by_id.get(shot_id)
        if record is None:
            classification = UNACCOUNTED
            detail = {"shot_id": shot_id, "classification": classification}
        else:
            try:
                migrated = migrate_shot_spec_v1_to_v2_2(record["shot_spec_v1"])
                errors = list(SHOT_VALIDATOR.iter_errors(migrated))
            except Exception as exc:
                errors = [exc]
            if not errors:
                classification = MIGRATE_TO_V5
                detail = {
                    "shot_id": shot_id,
                    "classification": classification,
                    "legacy_status": record["legacy_status"],
                    "reason": "canonical v2.2 validation passed",
                }
            else:
                classification = LEGACY_READ_ONLY_COMPAT
                detail = {
                    "shot_id": shot_id,
                    "classification": classification,
                    "legacy_status": record["legacy_status"],
                    "reason": "legacy record remains readable without rewriting it",
                    "validation_error": str(errors[0]),
                }
        counts[classification] += 1
        records.append(detail)
    return {
        "source_path": str(adapter.path),
        "required": len(shot_ids),
        "accounted": len(shot_ids) - counts[UNACCOUNTED],
        "unaccounted": counts[UNACCOUNTED],
        "counts": counts,
        "records": records,
        "write_policy": "all writes fail with LegacyReadOnlyError",
    }


__all__ = [
    "LEGACY_READ_ONLY_COMPAT",
    "MIGRATE_TO_V5",
    "PROVEN_ARCHIVE_ONLY",
    "UNACCOUNTED",
    "LegacyReadOnlyCompatibility",
    "LegacyReadOnlyError",
    "account_legacy_shots",
]
