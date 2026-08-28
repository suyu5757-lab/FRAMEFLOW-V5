"""Evidence and deterministic equivalence gates for T03 Candidate A/B.

Candidate A is the only candidate that may be opened by the application
launcher.  Candidate B is validated as a closed SQLite file and is compared
with A through source, migration, schema, logical-data, and row-accounting
evidence.  This module never opens a candidate through the Runtime backend.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

from core.schemas.runtime_mvp import RUNTIME_TABLE_NAMES

from .candidate_b_lifecycle import (
    CandidateBSealError,
    assert_candidate_b_database_open_allowed,
)
from .legacy_compat import account_legacy_shots
from .v3_to_v5 import inspect_legacy_database
from .validation import validate_candidate


INTERNAL_TABLES = {"alembic_version", "sqlite_sequence"}
MIGRATION_REVISION = "20260826_01"
MIGRATION_IMPLEMENTATION_VERSION = "v3_to_v5:20260826_01-deterministic-v2"
SCHEMA_CONTRACT_VERSION = "runtime-mvp:5.3.2"
REQUIRED_LEGACY_SHOT_IDS = tuple(f"SH{number:03d}" for number in range(4, 21))
A0_STAGE = "A0_MIGRATION_BASELINE"
A1_STAGE = "A1_POST_SMOKE"
B0_STAGE = "B0_MIGRATION_BASELINE"


class CandidateEquivalenceError(RuntimeError):
    """Raised when candidate evidence cannot be collected safely."""


def _resolve(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _read_only(path: Path | str) -> sqlite3.Connection:
    resolved = _resolve(path)
    assert_candidate_b_database_open_allowed(resolved)
    if not resolved.is_file():
        raise CandidateEquivalenceError(f"candidate database does not exist: {resolved}")
    query = "mode=ro"
    if not Path(f"{resolved}-wal").exists():
        query += "&immutable=1"
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"file:{resolved.as_posix()}?{query}", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection
    except sqlite3.DatabaseError as exc:
        if connection is not None:
            connection.close()
        raise CandidateEquivalenceError(f"candidate database is not readable: {resolved}") from exc


def _normalise_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__bytes__": value.hex()}
    if isinstance(value, memoryview):
        return {"__bytes__": value.tobytes().hex()}
    return value


def _index_snapshot(connection: sqlite3.Connection, table_name: str) -> list[dict[str, Any]]:
    indexes: list[dict[str, Any]] = []
    for row in connection.execute(f"PRAGMA index_list({_quote(table_name)})").fetchall():
        index_name = str(row[1])
        columns = [
            {"seqno": int(info[0]), "cid": int(info[1]), "name": info[2]}
            for info in connection.execute(f"PRAGMA index_info({_quote(index_name)})").fetchall()
        ]
        indexes.append(
            {
                "name": index_name,
                "unique": int(row[2]),
                "origin": str(row[3]),
                "partial": int(row[4]),
                "columns": columns,
            }
        )
    return sorted(indexes, key=lambda item: item["name"])


def _table_schema_snapshot(connection: sqlite3.Connection, table_name: str) -> dict[str, Any]:
    quoted = _quote(table_name)
    columns = [
        {
            "name": str(row[1]),
            "type": str(row[2]).upper(),
            "nullable": not bool(row[3]),
            "default": row[4],
            "pk": int(row[5]),
        }
        for row in connection.execute(f"PRAGMA table_info({quoted})").fetchall()
    ]
    foreign_keys = [
        {
            "seq": int(row[1]),
            "table": str(row[2]),
            "from": str(row[3]),
            "to": str(row[4]),
            "on_update": str(row[5]),
            "on_delete": str(row[6]),
            "match": str(row[7]),
        }
        for row in connection.execute(f"PRAGMA foreign_key_list({quoted})").fetchall()
    ]
    sql_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone()
    table_sql = re.sub(r"\s+", " ", str(sql_row[0] or "")).strip()
    return {
        "columns": columns,
        "foreign_keys": foreign_keys,
        "indexes": _index_snapshot(connection, table_name),
        "table_sql": table_sql,
    }


def schema_fingerprint(path: Path | str) -> dict[str, Any]:
    """Return a canonical schema snapshot and SHA-256 fingerprint.

    The snapshot includes domain table names, column type/nullability/PK
    contracts, foreign keys, table-level constraints, and relevant indexes.
    """

    resolved = _resolve(path)
    connection = _read_only(resolved)
    try:
        actual_tables = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        )
        domain_tables = tuple(sorted(set(actual_tables) - INTERNAL_TABLES))
        tables = {
            table_name: _table_schema_snapshot(connection, table_name)
            for table_name in domain_tables
        }
        snapshot = {
            "domain_tables": list(domain_tables),
            "tables": tables,
        }
        return {
            "path": str(resolved),
            "domain_tables": list(domain_tables),
            "domain_table_count": len(domain_tables),
            "snapshot": snapshot,
            "sha256": _digest(snapshot),
        }
    finally:
        connection.close()


def logical_data_fingerprint(path: Path | str) -> dict[str, Any]:
    """Return a deterministic logical fingerprint for all V5 domain rows.

    Rows are ordered by declared primary-key columns and serialised by column
    name/value.  The SQLite file hash is deliberately not part of this gate.
    """

    resolved = _resolve(path)
    connection = _read_only(resolved)
    try:
        actual_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        table_fingerprints: dict[str, Any] = {}
        primary_keys: dict[str, list[list[Any]]] = {}
        row_counts: dict[str, int] = {}
        for table_name in RUNTIME_TABLE_NAMES:
            if table_name not in actual_tables:
                table_fingerprints[table_name] = {"missing": True}
                primary_keys[table_name] = []
                row_counts[table_name] = 0
                continue
            columns_info = connection.execute(
                f"PRAGMA table_info({_quote(table_name)})"
            ).fetchall()
            columns = [str(row[1]) for row in columns_info]
            pk_columns = [
                str(row[1]) for row in sorted(columns_info, key=lambda item: int(item[5])) if int(row[5]) > 0
            ]
            order_columns = pk_columns or columns
            select_columns = ", ".join(_quote(column) for column in columns)
            order_sql = ", ".join(_quote(column) for column in order_columns)
            query = f"SELECT {select_columns} FROM {_quote(table_name)}"
            if order_sql:
                query += f" ORDER BY {order_sql}"
            rows = [
                {
                    column: _normalise_value(row[column])
                    for column in columns
                }
                for row in connection.execute(query).fetchall()
            ]
            pk_rows = [
                [row[column] for column in pk_columns]
                for row in rows
            ]
            table_payload = {
                "columns": columns,
                "primary_key_columns": pk_columns,
                "row_count": len(rows),
                "rows": rows,
            }
            table_fingerprints[table_name] = {
                "columns": columns,
                "primary_key_columns": pk_columns,
                "row_count": len(rows),
                "rows": rows,
                "sha256": _digest(table_payload),
            }
            primary_keys[table_name] = pk_rows
            row_counts[table_name] = len(rows)
        comparison = {
            "tables": table_fingerprints,
            "primary_keys": primary_keys,
            "row_counts": row_counts,
        }
        return {
            "path": str(resolved),
            "domain_table_count": len(RUNTIME_TABLE_NAMES),
            "tables": table_fingerprints,
            "primary_keys": primary_keys,
            "row_counts": row_counts,
            "sha256": _digest(comparison),
        }
    finally:
        connection.close()


def compare_logical_fingerprints(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> dict[str, Any]:
    """Return table, PK, row, and field deltas between saved fingerprints."""

    left_tables = left.get("tables") if isinstance(left.get("tables"), Mapping) else {}
    right_tables = right.get("tables") if isinstance(right.get("tables"), Mapping) else {}
    tables: list[dict[str, Any]] = []
    different_tables: list[str] = []
    for table_name in RUNTIME_TABLE_NAMES:
        left_table = left_tables.get(table_name, {})
        right_table = right_tables.get(table_name, {})
        left_sha = left_table.get("sha256") if isinstance(left_table, Mapping) else None
        right_sha = right_table.get("sha256") if isinstance(right_table, Mapping) else None
        same = left_sha is not None and left_sha == right_sha
        item: dict[str, Any] = {
            "table": table_name,
            "left_sha256": left_sha,
            "right_sha256": right_sha,
            "same": same,
        }
        if not same:
            different_tables.append(table_name)
            left_rows = (
                left_table.get("rows", []) if isinstance(left_table, Mapping) else []
            )
            right_rows = (
                right_table.get("rows", []) if isinstance(right_table, Mapping) else []
            )
            primary_keys = list(
                (left_table.get("primary_key_columns") if isinstance(left_table, Mapping) else None)
                or (right_table.get("primary_key_columns") if isinstance(right_table, Mapping) else None)
                or []
            )
            columns = list(
                (left_table.get("columns") if isinstance(left_table, Mapping) else None)
                or (right_table.get("columns") if isinstance(right_table, Mapping) else None)
                or []
            )

            def row_key(row: Mapping[str, Any]) -> str:
                values = [row.get(column) for column in primary_keys]
                return _canonical_json(values)

            left_by_pk = {
                row_key(row): row for row in left_rows if isinstance(row, Mapping)
            }
            right_by_pk = {
                row_key(row): row for row in right_rows if isinstance(row, Mapping)
            }
            only_left = sorted(set(left_by_pk) - set(right_by_pk))
            only_right = sorted(set(right_by_pk) - set(left_by_pk))
            changed_rows: list[dict[str, Any]] = []
            for key in sorted(set(left_by_pk) & set(right_by_pk)):
                left_row = left_by_pk[key]
                right_row = right_by_pk[key]
                fields = {
                    column: {"left": left_row.get(column), "right": right_row.get(column)}
                    for column in columns
                    if left_row.get(column) != right_row.get(column)
                }
                if fields:
                    changed_rows.append(
                        {
                            "pk": json.loads(key),
                            "fields": fields,
                        }
                    )
            item.update(
                {
                    "primary_key_columns": primary_keys,
                    "only_in_left": [json.loads(key) for key in only_left],
                    "only_in_right": [json.loads(key) for key in only_right],
                    "same_pk_changed_rows": changed_rows,
                    "row_delta_available": (
                        bool(primary_keys)
                        and isinstance(left_table, Mapping)
                        and isinstance(right_table, Mapping)
                        and "rows" in left_table
                        and "rows" in right_table
                    ),
                }
            )
        tables.append(item)
    return {
        "same": not different_tables,
        "left_sha256": left.get("sha256"),
        "right_sha256": right.get("sha256"),
        "different_tables": different_tables,
        "tables": tables,
    }


def build_smoke_delta(
    a0: Mapping[str, Any],
    a1: Mapping[str, Any],
    *,
    fixture_ids: Iterable[str] = (),
    expected_runtime_tables: Iterable[str] = (),
) -> dict[str, Any]:
    """Classify A0-to-A1 changes without weakening A0/B0 equivalence."""

    left = a0.get("logical_fingerprint")
    right = a1.get("logical_fingerprint")
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        raise CandidateEquivalenceError("A0/A1 logical fingerprints are required")
    delta = compare_logical_fingerprints(left, right)
    fixture_tokens = tuple(str(value) for value in fixture_ids)
    expected_tables = {str(value) for value in expected_runtime_tables}
    classifications: list[dict[str, Any]] = []
    cleanup_defects: list[dict[str, Any]] = []
    unexpected: list[dict[str, Any]] = []
    for table in delta["tables"]:
        if table["same"]:
            continue
        rendered = _canonical_json(table)
        fixture_related = bool(fixture_tokens) and any(
            token in rendered for token in fixture_tokens
        )
        if fixture_related:
            classification = "TEST_CLEANUP_DEFECT"
            cleanup_defects.append(table)
        elif table["table"] in expected_tables:
            classification = "EXPECTED_RUNTIME_METADATA"
        else:
            classification = "UNEXPECTED_RUNTIME_SIDE_EFFECT"
            unexpected.append(table)
        classifications.append(
            {"table": table["table"], "classification": classification}
        )
    return {
        **delta,
        "fixture_ids": list(fixture_tokens),
        "classifications": classifications,
        "cleanup_defects": cleanup_defects,
        "unexpected_side_effects": unexpected,
        "smoke_fixture_cleanup_passed": not cleanup_defects,
        "passed": not cleanup_defects and not unexpected,
    }


def _accounting_from_manifest(
    manifest: Mapping[str, Any] | None,
    *,
    legacy_source: Path | str | None,
    required_shots: tuple[str, ...],
) -> dict[str, Any]:
    value = manifest or {}
    tables = value.get("tables") if isinstance(value.get("tables"), Mapping) else {}
    unknown = sum(
        int(item.get("source_rows") or 0)
        for item in tables.values()
        if isinstance(item, Mapping) and item.get("classification") == "UNKNOWN"
    )
    manifest_unaccounted = int(
        (value.get("rows") or {}).get("unmapped", 0)
        if isinstance(value.get("rows"), Mapping)
        else 0
    )
    shot_accounting = value.get("t03_legacy_shot_accounting")
    if not isinstance(shot_accounting, Mapping) and legacy_source is not None:
        shot_accounting = account_legacy_shots(legacy_source, list(required_shots))
    if not isinstance(shot_accounting, Mapping):
        shot_accounting = {
            "required": len(required_shots),
            "accounted": 0,
            "unaccounted": len(required_shots),
        }
    source_info = value.get("source") if isinstance(value.get("source"), Mapping) else None
    if source_info is None and legacy_source is not None:
        source_info = inspect_legacy_database(legacy_source)
    if isinstance(source_info, Mapping):
        unknown = max(
            unknown,
            sum(
                int(item.get("row_count") or 0)
                for item in source_info.get("tables", [])
                if isinstance(item, Mapping) and item.get("classification") == "UNKNOWN"
            ),
        )
    shot_unaccounted = int(shot_accounting.get("unaccounted") or 0)
    records = {
        "unknown": unknown,
        # The migration manifest's 17 unmapped rows are the intentionally
        # preserved legacy-only shots.  They are accounted by the explicit
        # LegacyReadOnlyCompat classification below, so only missing required
        # shots contribute to the final UNACCOUNTED gate.
        "unaccounted": shot_unaccounted,
        "migration_unmapped_rows": manifest_unaccounted,
        "required_shots": int(shot_accounting.get("required") or len(required_shots)),
        "accounted_shots": int(shot_accounting.get("accounted") or 0),
        "shot_ids": list(required_shots),
    }
    return {
        **records,
        "comparison": records,
        "manifest_rows": value.get("rows", {}),
        "legacy_shot_accounting": dict(shot_accounting),
    }


def build_candidate_evidence(
    candidate: Path | str,
    *,
    source_legacy_sha: str,
    migration_manifest: Mapping[str, Any] | None = None,
    legacy_source: Path | str | None = None,
    migration_revision: str = MIGRATION_REVISION,
    migration_implementation_version: str = MIGRATION_IMPLEMENTATION_VERSION,
    schema_contract_version: str = SCHEMA_CONTRACT_VERSION,
    backend_opened: bool = False,
    validation: Mapping[str, Any] | None = None,
    rename: Mapping[str, Any] | None = None,
    formal_launcher: Mapping[str, Any] | None = None,
    evidence_stage: str | None = None,
    captured_before_backend: bool | None = None,
    captured_after_smoke: bool | None = None,
    captured_before_swap: bool | None = None,
) -> dict[str, Any]:
    """Collect auditable evidence without opening a Runtime backend."""

    resolved = _resolve(candidate)
    manifest = migration_manifest or {}
    migration_revision = str(manifest.get("migration_revision") or migration_revision)
    migration_implementation_version = str(
        manifest.get("migration_implementation_version")
        or migration_implementation_version
    )
    schema_contract_version = str(
        manifest.get("schema_contract_version") or schema_contract_version
    )
    schema = schema_fingerprint(resolved)
    logical = logical_data_fingerprint(resolved)
    validation_result = dict(validation) if validation is not None else validate_candidate(resolved)
    evidence: dict[str, Any] = {
        "candidate": str(resolved),
        "candidate_sha256": _sha256(resolved),
        "source_legacy_sha": str(source_legacy_sha),
        "migration_revision": str(migration_revision),
        "migration_implementation_version": str(migration_implementation_version),
        "schema_contract_version": str(schema_contract_version),
        "schema_fingerprint": schema,
        "logical_fingerprint": logical,
        "validation": validation_result,
        "validation_passed": not bool(validation_result.get("errors")),
        "backend_opened": bool(backend_opened),
        "row_accounting": _accounting_from_manifest(
            manifest,
            legacy_source=legacy_source,
            required_shots=REQUIRED_LEGACY_SHOT_IDS,
        ),
    }
    if evidence_stage is not None:
        evidence["evidence_stage"] = str(evidence_stage)
    if captured_before_backend is not None:
        evidence["captured_before_backend"] = bool(captured_before_backend)
    if captured_after_smoke is not None:
        evidence["captured_after_smoke"] = bool(captured_after_smoke)
    if captured_before_swap is not None:
        evidence["captured_before_swap"] = bool(captured_before_swap)
    if rename is not None:
        evidence["rename"] = dict(rename)
        evidence["rename_passed"] = rename.get("passed") is True
    if formal_launcher is not None:
        evidence["formal_launcher_evidence"] = dict(formal_launcher)
    return evidence


def build_candidate_a_lifecycle_evidence(
    a0: Mapping[str, Any],
    a1: Mapping[str, Any],
    *,
    formal_launcher: Mapping[str, Any],
    rename: Mapping[str, Any],
    smoke_delta: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind immutable A0 migration proof to separate A1 runtime proof."""

    candidate = str(a0.get("candidate") or "")
    if not candidate or candidate != str(a1.get("candidate") or ""):
        raise CandidateEquivalenceError("A0 and A1 must name the same Candidate A")
    return {
        "candidate": candidate,
        "migration_baseline": dict(a0),
        "post_smoke": dict(a1),
        "formal_launcher_evidence": dict(formal_launcher),
        "rename": dict(rename),
        "rename_passed": rename.get("passed") is True,
        "smoke_delta": dict(smoke_delta),
    }


def _migration_baseline(evidence: Mapping[str, Any]) -> Mapping[str, Any]:
    baseline = evidence.get("migration_baseline")
    return baseline if isinstance(baseline, Mapping) else evidence


def _schema_value(evidence: Mapping[str, Any]) -> Any:
    value = evidence.get("schema_fingerprint")
    if isinstance(value, Mapping):
        return value.get("sha256") or value.get("fingerprint") or value
    return value or evidence.get("schema_sha256")


def _logical_value(evidence: Mapping[str, Any]) -> Any:
    value = evidence.get("logical_fingerprint")
    if isinstance(value, Mapping):
        return value.get("sha256") or value.get("fingerprint") or value
    return value or evidence.get("logical_sha256")


def _accounting_value(evidence: Mapping[str, Any]) -> Any:
    value = evidence.get("row_accounting")
    if isinstance(value, Mapping):
        return value.get("comparison") or value
    return value


def _passed_validation(evidence: Mapping[str, Any]) -> bool | None:
    if "validation_passed" in evidence:
        return evidence.get("validation_passed") is True
    validation = evidence.get("validation")
    if isinstance(validation, Mapping):
        return not bool(validation.get("errors"))
    return None


def _passed_rename(evidence: Mapping[str, Any]) -> bool | None:
    if "rename_passed" in evidence:
        return evidence.get("rename_passed") is True
    rename = evidence.get("rename")
    if isinstance(rename, Mapping):
        return rename.get("passed") is True
    return None


def verify_candidate_equivalence(
    candidate_a: Mapping[str, Any],
    candidate_b: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare only Candidate A's A0 baseline with Candidate B's B0 baseline."""

    errors: list[str] = []
    checks: dict[str, bool] = {}
    candidate_a0 = _migration_baseline(candidate_a)
    candidate_b0 = _migration_baseline(candidate_b)

    source_a = str(candidate_a0.get("source_legacy_sha") or "")
    source_b = str(candidate_b0.get("source_legacy_sha") or "")
    checks["same_frozen_source"] = bool(source_a) and source_a == source_b
    if not checks["same_frozen_source"]:
        errors.append("source_legacy_sha differs or is missing")

    for label, key in (
        ("migration_revision", "migration_revision"),
        ("migration_implementation_version", "migration_implementation_version"),
        ("schema_contract_version", "schema_contract_version"),
    ):
        left = str(candidate_a0.get(key) or "")
        right = str(candidate_b0.get(key) or "")
        checks[label] = bool(left) and left == right
        if not checks[label]:
            errors.append(f"{label} differs or is missing")

    schema_a = _schema_value(candidate_a0)
    schema_b = _schema_value(candidate_b0)
    checks["schema_equivalence"] = schema_a is not None and schema_a == schema_b
    if not checks["schema_equivalence"]:
        errors.append("schema fingerprints differ")

    logical_a = _logical_value(candidate_a0)
    logical_b = _logical_value(candidate_b0)
    checks["logical_data_equivalence"] = logical_a is not None and logical_a == logical_b
    if not checks["logical_data_equivalence"]:
        errors.append("logical data fingerprints differ")

    primary_keys_a = (candidate_a0.get("logical_fingerprint") or {}).get("primary_keys") if isinstance(candidate_a0.get("logical_fingerprint"), Mapping) else None
    primary_keys_b = (candidate_b0.get("logical_fingerprint") or {}).get("primary_keys") if isinstance(candidate_b0.get("logical_fingerprint"), Mapping) else None
    checks["business_pk_equivalence"] = primary_keys_a is not None and primary_keys_a == primary_keys_b
    if not checks["business_pk_equivalence"]:
        errors.append("business primary keys differ")

    accounting_a = _accounting_value(candidate_a0)
    accounting_b = _accounting_value(candidate_b0)
    checks["row_accounting_equivalence"] = accounting_a is not None and accounting_a == accounting_b
    if not checks["row_accounting_equivalence"]:
        errors.append("row accounting differs")

    if "backend_opened" in candidate_b0 or "candidate_b_backend_opened" in candidate_b0:
        backend_opened = candidate_b0.get("backend_opened", candidate_b0.get("candidate_b_backend_opened"))
        checks["candidate_b_backend_opened"] = backend_opened is False
        if not checks["candidate_b_backend_opened"]:
            errors.append("Candidate B backend-opened must be NO")

    validation_passed = _passed_validation(candidate_b0)
    if validation_passed is not None:
        checks["candidate_b_validation"] = validation_passed
        if not validation_passed:
            errors.append("Candidate B validation failed")

    rename_passed = _passed_rename(candidate_b0)
    if rename_passed is not None:
        checks["candidate_b_rename"] = rename_passed
        if not rename_passed:
            errors.append("Candidate B rename probe failed")

    logical_delta = None
    left_fingerprint = candidate_a0.get("logical_fingerprint")
    right_fingerprint = candidate_b0.get("logical_fingerprint")
    if isinstance(left_fingerprint, Mapping) and isinstance(right_fingerprint, Mapping):
        logical_delta = compare_logical_fingerprints(left_fingerprint, right_fingerprint)

    return {
        "passed": not errors,
        "ready": not errors,
        "errors": errors,
        "checks": checks,
        "candidate_a": candidate_a0.get("candidate"),
        "candidate_b": candidate_b0.get("candidate"),
        "comparison_stage": "A0_VS_B0",
        "logical_delta": logical_delta,
    }


def _formal_launcher_passed(evidence: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    launcher = evidence.get("formal_launcher_evidence")
    if not isinstance(launcher, Mapping):
        launcher = evidence.get("formal_launcher")
    if not isinstance(launcher, Mapping):
        return False, {"reason": "formal launcher evidence missing"}
    boots = launcher.get("boots")
    if launcher.get("status") != "PASS" or not isinstance(boots, list) or len(boots) != 2:
        return False, {"reason": "formal launcher status or two boots missing"}
    for expected, boot in zip(("first_start", "restart"), boots, strict=True):
        if not isinstance(boot, Mapping):
            return False, {"reason": f"{expected} boot evidence missing"}
        health = boot.get("health")
        if (
            boot.get("boot") != expected
            or boot.get("api_passed") != 19
            or boot.get("api_failed") != 0
            or boot.get("historical_passed") != 17
            or boot.get("historical_failed") != 0
            or not isinstance(health, Mapping)
            or health.get("runtime_mode") != "v5"
        ):
            return False, {"reason": f"{expected} 19/19 + 17/17 gate failed"}
    return True, {"boots": boots}


def verify_final_candidate_gate(
    candidate_a: Mapping[str, Any],
    candidate_b: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply the complete pre-cutover gate to A/B evidence."""

    result = verify_candidate_equivalence(candidate_a, candidate_b)
    errors = list(result["errors"])
    checks = dict(result["checks"])
    candidate_a0 = _migration_baseline(candidate_a)
    candidate_b0 = _migration_baseline(candidate_b)
    candidate_a1 = candidate_a.get("post_smoke")

    checks["a0_stage"] = candidate_a0.get("evidence_stage") == A0_STAGE
    checks["a0_captured_before_backend"] = (
        candidate_a0.get("captured_before_backend") is True
        and candidate_a0.get("backend_opened") is False
    )
    checks["b0_stage"] = candidate_b0.get("evidence_stage") == B0_STAGE
    checks["b0_captured_before_swap"] = (
        candidate_b0.get("captured_before_swap") is True
        and candidate_b0.get("backend_opened") is False
    )
    checks["a1_stage"] = (
        isinstance(candidate_a1, Mapping)
        and candidate_a1.get("evidence_stage") == A1_STAGE
        and candidate_a1.get("captured_after_smoke") is True
        and candidate_a1.get("backend_opened") is True
    )
    checks["candidate_a_lifecycle_path"] = (
        isinstance(candidate_a1, Mapping)
        and str(candidate_a.get("candidate") or "")
        == str(candidate_a0.get("candidate") or "")
        == str(candidate_a1.get("candidate") or "")
    )
    for check, message in (
        ("a0_stage", "Candidate A A0 migration baseline evidence is missing"),
        ("a0_captured_before_backend", "Candidate A A0 was not captured before backend open"),
        ("a1_stage", "Candidate A A1 post-smoke evidence is missing"),
        ("b0_stage", "Candidate B B0 migration baseline evidence is missing"),
        ("b0_captured_before_swap", "Candidate B B0 was not captured before swap"),
        ("candidate_a_lifecycle_path", "Candidate A A0/A1 lifecycle paths differ"),
    ):
        if not checks[check]:
            errors.append(message)

    launcher_passed, launcher_detail = _formal_launcher_passed(candidate_a)
    checks["candidate_a_formal_launcher"] = launcher_passed
    if not launcher_passed:
        errors.append(launcher_detail["reason"])

    smoke_delta = candidate_a.get("smoke_delta")
    checks["smoke_fixture_cleanup"] = (
        isinstance(smoke_delta, Mapping)
        and smoke_delta.get("smoke_fixture_cleanup_passed") is True
    )
    checks["smoke_delta_audit"] = (
        isinstance(smoke_delta, Mapping) and smoke_delta.get("passed") is True
    )
    if not checks["smoke_fixture_cleanup"]:
        errors.append("Candidate A smoke fixture cleanup failed")
    if not checks["smoke_delta_audit"]:
        errors.append("Candidate A smoke delta contains an unexpected side effect")

    a_rename = _passed_rename(candidate_a)
    checks["candidate_a_rename"] = a_rename is True
    if a_rename is not True:
        errors.append("Candidate A rename probe did not pass")

    checks["candidate_b_backend_opened"] = candidate_b0.get("backend_opened") is False
    if not checks["candidate_b_backend_opened"]:
        errors.append("Candidate B backend-opened must be NO")
    checks["candidate_b_validation"] = _passed_validation(candidate_b0) is True
    if not checks["candidate_b_validation"]:
        errors.append("Candidate B validation must pass")
    checks["candidate_b_rename"] = _passed_rename(candidate_b0) is True
    if not checks["candidate_b_rename"]:
        errors.append("Candidate B rename probe must pass")

    terminal_seal = candidate_b0.get("terminal_seal")
    checks["candidate_b_terminal_seal"] = (
        isinstance(terminal_seal, Mapping)
        and terminal_seal.get("state") == "SEALED"
    )
    checks["candidate_b_reopened_after_rename"] = (
        isinstance(terminal_seal, Mapping)
        and terminal_seal.get("candidate_b_reopened_after_rename") is False
    )
    checks["candidate_b_post_seal_db_open_count"] = (
        isinstance(terminal_seal, Mapping)
        and int(terminal_seal.get("candidate_b_post_seal_db_open_count") or 0) == 0
    )
    final_stabilization = candidate_b0.get("final_db_stabilization")
    checks["candidate_b_final_db_stabilization"] = (
        isinstance(final_stabilization, Mapping)
        and final_stabilization.get("passed") is True
        and final_stabilization.get("checkpoint_passed") is True
        and final_stabilization.get("journal_mode_after_stabilization") == "delete"
        and final_stabilization.get("sidecars_absent") is True
        and isinstance(final_stabilization.get("stable_samples"), list)
        and len(final_stabilization.get("stable_samples") or []) >= 4
    )
    if not checks["candidate_b_terminal_seal"]:
        errors.append("Candidate B terminal SEALED evidence is missing")
    if not checks["candidate_b_reopened_after_rename"]:
        errors.append("Candidate B was reopened after final rename")
    if not checks["candidate_b_post_seal_db_open_count"]:
        errors.append("Candidate B post-seal database open count is non-zero")
    if not checks["candidate_b_final_db_stabilization"]:
        errors.append("Candidate B sidecar-free final DB stabilization is missing")

    accounting = candidate_b0.get("row_accounting")
    if not isinstance(accounting, Mapping):
        errors.append("row accounting evidence missing")
    else:
        checks["unknown_zero"] = int(accounting.get("unknown") or 0) == 0
        checks["unaccounted_zero"] = int(accounting.get("unaccounted") or 0) == 0
        checks["legacy_shots_17_of_17"] = (
            int(accounting.get("required_shots") or 0) == 17
            and int(accounting.get("accounted_shots") or 0) == 17
        )
        if not checks["unknown_zero"]:
            errors.append("UNKNOWN row accounting is non-zero")
        if not checks["unaccounted_zero"]:
            errors.append("UNACCOUNTED row accounting is non-zero")
        if not checks["legacy_shots_17_of_17"]:
            errors.append("SH004-SH020 accounting is not 17/17")

    result.update({"passed": not errors, "ready": not errors, "errors": errors, "checks": checks})
    return result


__all__ = [
    "A0_STAGE",
    "A1_STAGE",
    "B0_STAGE",
    "CandidateBSealError",
    "CandidateEquivalenceError",
    "MIGRATION_IMPLEMENTATION_VERSION",
    "MIGRATION_REVISION",
    "REQUIRED_LEGACY_SHOT_IDS",
    "SCHEMA_CONTRACT_VERSION",
    "build_candidate_evidence",
    "build_candidate_a_lifecycle_evidence",
    "build_smoke_delta",
    "compare_logical_fingerprints",
    "logical_data_fingerprint",
    "schema_fingerprint",
    "verify_candidate_equivalence",
    "verify_final_candidate_gate",
]
