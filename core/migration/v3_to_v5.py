"""Side-by-side V3 (41-table) to V5 (11-table) migration.

The source is always opened read-only.  A consistent backup is required for a
real migration, and the candidate is created from an empty path through the
online Alembic revision before any rows are transformed.  This module never
opens the production database for writing and never moves project media.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from jsonschema import Draft202012Validator

from core.schemas.runtime_mvp import RUNTIME_TABLE_NAMES
from scripts.migrate_shot_spec_v1_to_v2_2 import migrate_shot_spec_v1_to_v2_2

from .backup import PRODUCTION_DATABASE, BackupError, create_backup, write_manifest
from .online import upgrade_candidate
from .candidate_b_lifecycle import assert_candidate_b_database_open_allowed
from .validation import assert_candidate_valid


SHOT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "shot_spec_v2.2.schema.json"
SHOT_VALIDATOR = Draft202012Validator(json.loads(SHOT_SCHEMA_PATH.read_text(encoding="utf-8")))

SOURCE_CLASSIFICATION: dict[str, str] = {
    "agent_candidate_versions_v5": "LEGACY_ONLY",
    "agent_plan_events_v5": "LEGACY_ONLY",
    "agent_plans_v5": "LEGACY_ONLY",
    "approval_gates_v3": "LEGACY_ONLY",
    "approvals": "ARCHIVE_ONLY",
    "artifact_lineage_v3": "ARCHIVE_ONLY",
    "artifacts": "MIGRATE",
    "asset_boards_v7": "ARCHIVE_ONLY",
    "asset_comparisons_v4": "ARCHIVE_ONLY",
    "asset_dependencies_v4": "ARCHIVE_ONLY",
    "asset_events": "DERIVE",
    "asset_qa_runs": "ARCHIVE_ONLY",
    "asset_reference_roles_v4": "ARCHIVE_ONLY",
    "asset_versions": "MIGRATE",
    "audit_events_v16": "DERIVE",
    "backup_records_v11": "ARCHIVE_ONLY",
    "capability_bindings": "ARCHIVE_ONLY",
    "conversations": "ARCHIVE_ONLY",
    "generation_snapshots_v9": "ARCHIVE_ONLY",
    "media_proxies_v6": "ARCHIVE_ONLY",
    "messages": "ARCHIVE_ONLY",
    "node_runs_v3": "ARCHIVE_ONLY",
    "projects": "MIGRATE",
    "prompt_versions": "ARCHIVE_ONLY",
    "provider_profiles": "ARCHIVE_ONLY",
    "recovery_plans_v11": "ARCHIVE_ONLY",
    "render_jobs_v6": "ARCHIVE_ONLY",
    "schema_migrations": "LEGACY_ONLY",
    "sqlite_sequence": "LEGACY_ONLY",
    "story_versions": "ARCHIVE_ONLY",
    "story_workflow_chains": "ARCHIVE_ONLY",
    "task_events": "DERIVE",
    "tasks": "MIGRATE",
    "timeline_events_v6": "DERIVE",
    "timelines_v3": "ARCHIVE_ONLY",
    "workflow_graph_events": "DERIVE",
    "workflow_graphs": "ARCHIVE_ONLY",
    "workflow_run_events_v3": "DERIVE",
    "workflow_runs": "ARCHIVE_ONLY",
    "workflow_runs_v3": "ARCHIVE_ONLY",
    "workflow_templates_v3": "ARCHIVE_ONLY",
}

DERIVED_EVENT_TABLES = {
    "asset_events",
    "audit_events_v16",
    "task_events",
    "timeline_events_v6",
    "workflow_graph_events",
    "workflow_run_events_v3",
}

DETERMINISTIC_TIMESTAMP_FALLBACK = "1970-01-01T00:00:00+00:00"


class MigrationError(RuntimeError):
    """Raised when a legacy-to-candidate migration must abort safely."""


def _resolve(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise MigrationError(f"legacy database does not exist: {path}")
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True
        )
        connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
    except sqlite3.DatabaseError as exc:
        if connection is not None:
            connection.close()
        raise MigrationError(f"legacy database is corrupt or incompatible: {path}") from exc
    connection.row_factory = sqlite3.Row
    return connection


def _json(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list, tuple, int, float, bool)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def _json_text(value: Any, default: Any) -> str:
    return json.dumps(_json(value, default), ensure_ascii=False, separators=(",", ":"))


def _value(row: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row.keys() and row[name] is not None:
            return row[name]
    return default


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return value if isinstance(value, str) else str(value)


def _stable_timestamp(value: Any, fallback: Any = None) -> str:
    """Return a source-derived timestamp without consulting wall-clock time."""

    return _text(value, _text(fallback, DETERMINISTIC_TIMESTAMP_FALLBACK))


def _number(value: Any, default: float, warnings: list[str], label: str) -> float:
    if value is None or value == "":
        warnings.append(f"{label}: missing; used explicit fallback {default}")
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        warnings.append(f"{label}: invalid value {value!r}; used explicit fallback {default}")
        return default


def _project_status(value: Any) -> str:
    status = _text(value, "DRAFT").strip().upper().replace(" ", "_")
    aliases = {"ACTIVE": "DRAFT", "READY": "SPEC_READY", "APPROVED": "QA_APPROVED"}
    return aliases.get(status, status or "DRAFT")[:32]


def _task_status(value: Any) -> str:
    status = _text(value, "CREATED").strip().upper().replace(" ", "_")
    aliases = {
        "QUEUED": "QUEUED",
        "AWAITING_CONFIRMATION": "WAITING_FOR_RESOURCE",
        "SUCCEEDED": "SUCCEEDED",
        "COMPLETED": "SUCCEEDED",
        "CANCELED": "CANCELLED",
        "CANCELLED": "CANCELLED",
    }
    return aliases.get(status, status if status in {"CREATED", "RUNNING", "FAILED", "INTERRUPTED"} else "CREATED")


def _table_columns(connection: sqlite3.Connection, table_name: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(f"PRAGMA table_info({_quote(table_name)})").fetchall()]


def _table_indexes(connection: sqlite3.Connection, table_name: str) -> list[dict[str, Any]]:
    result = []
    for row in connection.execute(f"PRAGMA index_list({_quote(table_name)})").fetchall():
        item = dict(row)
        item["columns"] = [
            dict(index_row)
            for index_row in connection.execute(f"PRAGMA index_info({_quote(str(row['name']))})").fetchall()
        ]
        result.append(item)
    return result


def inspect_legacy_database(path: Path | str) -> dict[str, Any]:
    """Return full table/column/PK/FK/index/row-count facts without writing."""

    source = _resolve(path)
    connection = _read_only(source)
    try:
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        details = []
        for table_name in tables:
            quoted = _quote(table_name)
            foreign_keys = [
                dict(row) for row in connection.execute(f"PRAGMA foreign_key_list({quoted})").fetchall()
            ]
            details.append(
                {
                    "name": table_name,
                    "row_count": int(connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]),
                    "classification": SOURCE_CLASSIFICATION.get(table_name, "UNKNOWN"),
                    "columns": _table_columns(connection, table_name),
                    "foreign_keys": foreign_keys,
                    "indexes": _table_indexes(connection, table_name),
                }
            )
        schema_version: int | str | None = None
        if "schema_migrations" in tables:
            values = [row[0] for row in connection.execute("SELECT version FROM schema_migrations").fetchall()]
            if values:
                schema_version = max(int(value) for value in values)
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key_check = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()]
        return {
            "path": str(source),
            "schema_version": schema_version,
            "table_count": len(tables),
            "tables": details,
            "pragmas": {
                "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
                "foreign_keys": connection.execute("PRAGMA foreign_keys").fetchone()[0],
                "busy_timeout": connection.execute("PRAGMA busy_timeout").fetchone()[0],
            },
            "integrity_check": integrity,
            "foreign_key_violations": foreign_key_check,
        }
    finally:
        connection.close()


def _empty_accounting(info: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for table in info["tables"]:
        source_rows = int(table["row_count"])
        classification = "EMPTY" if source_rows == 0 else table["classification"]
        result[table["name"]] = {
            "classification": classification,
            "source_rows": source_rows,
            "migrated_rows": 0,
            "derived_rows": 0,
            "archived_rows": 0,
            "unmapped_rows": 0,
        }
    return result


def _rows(connection: sqlite3.Connection, table_name: str) -> list[sqlite3.Row]:
    columns = connection.execute(f"PRAGMA table_info({_quote(table_name)})").fetchall()
    primary_keys = [
        str(row[1])
        for row in sorted(columns, key=lambda item: int(item[5]))
        if int(row[5]) > 0
    ]
    order_by = ", ".join(_quote(column) for column in primary_keys) or "rowid"
    return connection.execute(
        f"SELECT * FROM {_quote(table_name)} ORDER BY {order_by}"
    ).fetchall()


def _project_timestamps(
    candidate: sqlite3.Connection, project_id: str
) -> tuple[str, str]:
    row = candidate.execute(
        "SELECT created_at, updated_at FROM projects WHERE id=?", (project_id,)
    ).fetchone()
    if row is None:
        return DETERMINISTIC_TIMESTAMP_FALLBACK, DETERMINISTIC_TIMESTAMP_FALLBACK
    created = _stable_timestamp(row[0])
    return created, _stable_timestamp(row[1], created)


def _stable_row_token(table_name: str, row: Mapping[str, Any], ordinal: int) -> str:
    payload = {
        "table": table_name,
        "ordinal": ordinal,
        "row": {key: row[key] for key in sorted(row.keys())},
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()[:32]


def _document(row: Mapping[str, Any]) -> dict[str, Any]:
    value = _json(_value(row, "document_json", default={}), {})
    return value if isinstance(value, dict) else {}


def _shot_list(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = document.get("shots")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _asset_list(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = document.get("assets")
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _sequence_id(shot: Mapping[str, Any], project_id: str) -> str:
    value = _value(shot, "sequence_id", "sequenceId")
    del project_id
    return _text(value, "SQ001")


def _insert_project(
    candidate: sqlite3.Connection,
    row: Mapping[str, Any],
    warnings: list[str],
) -> str:
    project_id = _text(_value(row, "id"))
    if not project_id:
        raise MigrationError("projects row has no stable id")
    document = _document(row)
    title = _text(_value(row, "name"), _text(document.get("name"), project_id))
    aspect_ratio = _text(
        document.get("ratio") or document.get("aspectRatio") or document.get("aspect_ratio"),
        "16:9",
    )
    fps = _number(document.get("fps") or document.get("frameRate"), 24.0, warnings, f"project {project_id}.fps")
    duration = _number(
        document.get("duration") or document.get("target_duration"),
        0.0,
        warnings,
        f"project {project_id}.target_duration",
    )
    created = _stable_timestamp(
        _value(row, "created_at", default=document.get("createdAt"))
    )
    updated = _stable_timestamp(
        _value(row, "updated_at", default=document.get("updatedAt")), created
    )
    status = _project_status(_value(row, "lifecycle_status", default=document.get("lifecycleStatus")))
    candidate.execute(
        "INSERT INTO projects(id,title,aspect_ratio,fps,target_duration,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (project_id, title[:255], aspect_ratio[:32], fps, duration, status, created, updated),
    )
    return project_id


def _insert_sequences_and_shots(
    legacy: sqlite3.Connection,
    candidate: sqlite3.Connection,
    project_ids: set[str],
    accounting: dict[str, dict[str, Any]],
    warnings: list[str],
    unmapped: list[dict[str, Any]],
    strict: bool,
) -> tuple[int, int]:
    projects = {str(row["id"]): _document(row) for row in _rows(legacy, "projects")}
    sequence_count = 0
    shot_count = 0
    for project_id, document in projects.items():
        if project_id not in project_ids:
            continue
        shots = _shot_list(document)
        sequence_ids: list[str] = []
        for shot in shots:
            sid = _sequence_id(shot, project_id)
            if sid not in sequence_ids:
                sequence_ids.append(sid)
        project_created, project_updated = _project_timestamps(candidate, project_id)
        for order_index, sequence_id in enumerate(sequence_ids, start=1):
            candidate.execute(
                "INSERT INTO sequences(id,project_id,order_index,created_at) VALUES(?,?,?,?)",
                (sequence_id, project_id, order_index, project_created),
            )
            sequence_count += 1
        sequence_lookup = {sid: sid for sid in sequence_ids}
        for shot in shots:
            shot_id = _text(_value(shot, "id", "shot_id", "shotId"))
            if not shot_id:
                accounting["projects"]["unmapped_rows"] += 1
                warnings.append(f"project {project_id} contains a shot without a stable id")
                unmapped.append({"table": "projects", "project_id": project_id, "reason": "embedded shot has no stable id"})
                continue
            try:
                spec = migrate_shot_spec_v1_to_v2_2(shot)
                errors = list(SHOT_VALIDATOR.iter_errors(spec))
                if errors:
                    raise MigrationError(f"{shot_id} ShotSpec validation failed: {errors[0].message}")
                sequence_id = _sequence_id(shot, project_id)
                candidate.execute(
                    "INSERT INTO shots(id,project_id,sequence_id,shot_spec_json,metadata_json,continuity_in,continuity_out,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        shot_id,
                        project_id,
                        sequence_lookup[sequence_id],
                        json.dumps(spec, ensure_ascii=False, separators=(",", ":")),
                        _json_text(_value(shot, "metadata_json", "metadata", default={}), {}),
                        _json_text(spec.get("continuity_state_in"), None) if spec.get("continuity_state_in") is not None else None,
                        _json_text(spec.get("continuity_state_out"), None) if spec.get("continuity_state_out") is not None else None,
                        _stable_timestamp(
                            _value(shot, "created_at", "createdAt"), project_created
                        ),
                        _stable_timestamp(
                            _value(shot, "updated_at", "updatedAt"), project_updated
                        ),
                    ),
                )
                shot_count += 1
            except Exception as exc:
                accounting["projects"]["unmapped_rows"] += 1
                detail = {"table": "projects", "project_id": project_id, "shot_id": shot_id, "reason": str(exc)}
                unmapped.append(detail)
                warnings.append(f"UNMAPPED {shot_id}: {exc}")
                if strict:
                    raise MigrationError(f"{shot_id} migration failed: {exc}") from exc
    return sequence_count, shot_count


def _insert_document_assets(
    legacy: sqlite3.Connection,
    candidate: sqlite3.Connection,
    project_ids: set[str],
    accounting: dict[str, dict[str, Any]],
    unmapped: list[dict[str, Any]],
) -> int:
    seen: set[str] = set()
    count = 0
    for row in _rows(legacy, "projects"):
        project_id = _text(_value(row, "id"))
        if project_id not in project_ids:
            continue
        for asset in _asset_list(_document(row)):
            asset_id = _text(_value(asset, "id", "asset_id", "assetId"))
            if not asset_id or asset_id in seen:
                if not asset_id:
                    accounting["projects"]["unmapped_rows"] += 1
                    unmapped.append({"table": "projects", "project_id": project_id, "reason": "embedded asset has no stable id"})
                continue
            status = _project_status(_value(asset, "status", default="DRAFT"))
            if _text(_value(asset, "status")).upper() == "LOCKED":
                status = "LOCKED"
            version = _text(_value(asset, "version", default="1"), "1")
            project_created, _project_updated = _project_timestamps(candidate, project_id)
            candidate.execute(
                "INSERT INTO assets(id,project_id,type,status,version,master_artifact_id,locked_at,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    asset_id,
                    project_id,
                    _text(_value(asset, "type", "asset_type", default="unknown"), "unknown")[:64],
                    status[:32],
                    version[:64],
                    _value(asset, "master_artifact_id", "masterArtifactId"),
                    _value(asset, "locked_at", "lockedAt"),
                    _stable_timestamp(
                        _value(asset, "created_at", "createdAt"), project_created
                    ),
                ),
            )
            seen.add(asset_id)
            count += 1
    return count


def _insert_asset_versions(
    legacy: sqlite3.Connection,
    candidate: sqlite3.Connection,
    project_ids: set[str],
    accounting: dict[str, dict[str, Any]],
    unmapped: list[dict[str, Any]],
) -> int:
    if "asset_versions" not in accounting:
        return 0
    count = 0
    for row in _rows(legacy, "asset_versions"):
        project_id = _text(_value(row, "project_id"))
        logical_id = _text(_value(row, "logical_asset_id"))
        if not project_id or project_id not in project_ids or not logical_id:
            accounting["asset_versions"]["unmapped_rows"] += 1
            unmapped.append({"table": "asset_versions", "row_id": _value(row, "id"), "reason": "missing project_id or logical_asset_id"})
            continue
        existing = candidate.execute("SELECT id FROM assets WHERE id=?", (logical_id,)).fetchone()
        if existing:
            accounting["asset_versions"]["migrated_rows"] += 1
            count += 1
            continue
        status = _text(_value(row, "status", default="DRAFT"), "DRAFT").upper()[:32]
        project_created, _project_updated = _project_timestamps(candidate, project_id)
        candidate.execute(
            "INSERT INTO assets(id,project_id,type,status,version,master_artifact_id,locked_at,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                logical_id,
                project_id,
                _text(_value(row, "asset_class", default="unknown"), "unknown")[:64],
                "LOCKED" if status == "LOCKED" else status,
                _text(_value(row, "version", default="1"), "1")[:64],
                _value(row, "artifact_id"),
                _value(row, "approved_at") if status in {"APPROVED", "LOCKED"} else None,
                _stable_timestamp(_value(row, "created_at"), project_created),
            ),
        )
        accounting["asset_versions"]["migrated_rows"] += 1
        count += 1
    return count


def _artifact_shot_id(row: Mapping[str, Any], shot_ids: set[str]) -> str | None:
    metadata = _json(_value(row, "metadata_json", default={}), {})
    if not isinstance(metadata, dict):
        metadata = {}
    candidate = _value(row, "shot_id", default=metadata.get("shot_id") or metadata.get("shotId"))
    candidate = _text(candidate) if candidate is not None else ""
    return candidate if candidate in shot_ids else None


def _insert_artifacts(
    legacy: sqlite3.Connection,
    candidate: sqlite3.Connection,
    project_ids: set[str],
    shot_ids: set[str],
    asset_ids: set[str],
    accounting: dict[str, dict[str, Any]],
    unmapped: list[dict[str, Any]],
) -> int:
    count = 0
    for row in _rows(legacy, "artifacts"):
        artifact_id = _text(_value(row, "id"))
        project_id = _text(_value(row, "project_id"))
        path = _value(row, "local_path", "path")
        if not artifact_id or not project_id or project_id not in project_ids or not path:
            accounting["artifacts"]["unmapped_rows"] += 1
            unmapped.append({"table": "artifacts", "row_id": artifact_id or None, "reason": "missing stable id, project, or path"})
            continue
        asset_id = _text(_value(row, "logical_asset_id", "asset_id")) or None
        if asset_id not in asset_ids:
            if asset_id:
                unmapped.append({"table": "artifacts", "row_id": artifact_id, "reason": f"asset reference not found: {asset_id}"})
            asset_id = None
        metadata = _json(_value(row, "metadata_json", default={}), {})
        source_artifacts = metadata.get("source_artifacts", []) if isinstance(metadata, dict) else []
        project_created, _project_updated = _project_timestamps(candidate, project_id)
        candidate.execute(
            "INSERT INTO artifacts(id,project_id,shot_id,asset_id,type,role,path,sha256,version,source_task_id,source_artifacts_json,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                artifact_id,
                project_id,
                _artifact_shot_id(row, shot_ids),
                asset_id,
                _text(_value(row, "artifact_type", "type", default="unknown"), "unknown")[:64],
                _text(_value(row, "role", default="artifact"), "artifact")[:64],
                _text(path),
                _value(row, "sha256"),
                _text(_value(row, "version", default="1"), "1")[:64],
                _value(row, "task_id", "source_task_id"),
                _json_text(source_artifacts, []),
                _text(_value(row, "status", default="DRAFT"), "DRAFT")[:32],
                _stable_timestamp(_value(row, "created_at"), project_created),
            ),
        )
        accounting["artifacts"]["migrated_rows"] += 1
        count += 1
    return count


def _task_shot_id(row: Mapping[str, Any], shot_ids: set[str]) -> str | None:
    request = _json(_value(row, "request_json", "payload_json", default={}), {})
    candidate = _value(row, "shot_id", default=request.get("shot_id") if isinstance(request, dict) else None)
    candidate = _text(candidate) if candidate is not None else ""
    return candidate if candidate in shot_ids else None


def _insert_tasks(
    legacy: sqlite3.Connection,
    candidate: sqlite3.Connection,
    project_ids: set[str],
    shot_ids: set[str],
    accounting: dict[str, dict[str, Any]],
    unmapped: list[dict[str, Any]],
) -> int:
    count = 0
    for row in _rows(legacy, "tasks"):
        task_id = _text(_value(row, "id"))
        project_id = _text(_value(row, "project_id")) or None
        if not task_id or project_id not in project_ids:
            accounting["tasks"]["unmapped_rows"] += 1
            unmapped.append({"table": "tasks", "row_id": task_id or None, "reason": "missing stable id or project_id"})
            continue
        request = _json(_value(row, "request_json", default={}), {})
        error = None
        if _value(row, "error_kind", "error_message") is not None:
            error = {"kind": _value(row, "error_kind"), "message": _value(row, "error_message")}
        project_created, _project_updated = _project_timestamps(candidate, project_id)
        candidate.execute(
            "INSERT INTO tasks(id,type,project_id,shot_id,status,priority,idempotency_key,attempt,max_attempts,timeout,worker,payload_json,result_json,error_json,created_at,started_at,heartbeat_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                _text(_value(row, "task_type", "type", default="legacy"), "legacy")[:64],
                project_id,
                _task_shot_id(row, shot_ids),
                _task_status(_value(row, "status")),
                0,
                request.get("idempotency_key") if isinstance(request, dict) else None,
                int(_value(row, "attempts", "attempt", default=0) or 0),
                3,
                None,
                _value(row, "provider_profile_id"),
                _json_text(request, {}),
                _value(row, "result_json"),
                _json_text(error, None) if error else None,
                _stable_timestamp(_value(row, "created_at"), project_created),
                None,
                None,
                _value(row, "updated_at"),
            ),
        )
        accounting["tasks"]["migrated_rows"] += 1
        count += 1
    return count


def _derived_entity(row: Mapping[str, Any], table_name: str) -> tuple[str, str, str]:
    entity_type = _text(_value(row, "target_type", "entity_type", default=table_name), table_name)
    entity_id = _text(_value(row, "target_id", "entity_id", "project_id", "task_id", "run_id", "id"), "unknown")
    event_type = _text(_value(row, "action", "event_type", "to_status", default="legacy_import"), "legacy_import")
    return entity_type[:64], entity_id[:120], event_type[:120]


def _derive_events(
    legacy: sqlite3.Connection,
    candidate: sqlite3.Connection,
    accounting: dict[str, dict[str, Any]],
) -> int:
    count = 0
    for table_name in DERIVED_EVENT_TABLES:
        if table_name not in accounting:
            continue
        for ordinal, row in enumerate(_rows(legacy, table_name)):
            entity_type, entity_id, event_type = _derived_entity(row, table_name)
            stable_token = _stable_row_token(table_name, row, ordinal)
            source_id = _text(_value(row, "id"), stable_token)
            event_id = f"EVT_LEGACY_{table_name}_{source_id}"[:120]
            payload = {
                key: row[key]
                for key in row.keys()
                if key in {"detail_json", "before_json", "after_json", "reason", "result", "metadata_json"}
            }
            candidate.execute(
                "INSERT INTO events(id,trace_id,entity_type,entity_id,event_type,payload,created_at) VALUES(?,?,?,?,?,?,?)",
                (
                    event_id,
                    f"TRACE_LEGACY_{table_name}_{source_id}"[:120],
                    entity_type,
                    entity_id,
                    event_type,
                    _json_text(payload, {}),
                    _stable_timestamp(_value(row, "created_at")),
                ),
            )
            accounting[table_name]["derived_rows"] += 1
            count += 1
    return count


def _archive_non_runtime_tables(accounting: dict[str, dict[str, Any]]) -> None:
    for item in accounting.values():
        if item["source_rows"] == 0:
            continue
        if item["classification"] in {"ARCHIVE_ONLY", "LEGACY_ONLY", "UNKNOWN"}:
            item["archived_rows"] = item["source_rows"]


def _manifest_summary(accounting: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {
        "migrated": sum(item["migrated_rows"] for item in accounting.values()),
        "derived": sum(item["derived_rows"] for item in accounting.values()),
        "archived": sum(item["archived_rows"] for item in accounting.values()),
        "unmapped": sum(item["unmapped_rows"] for item in accounting.values()),
    }


def migrate_v3_to_v5(
    source_path: Path | str,
    candidate_path: Path | str | None = None,
    *,
    backup_path: Path | str | None = None,
    dry_run: bool = False,
    run_id: str | None = None,
    strict: bool = False,
    manifest_path: Path | str | None = None,
) -> dict[str, Any]:
    """Migrate a legacy snapshot to a new candidate and return an audit manifest."""

    source = _resolve(source_path)
    source_before = _resolve(source)
    source_sha_before = _sha256(source_before)
    source_info = inspect_legacy_database(source)
    accounting = _empty_accounting(source_info)
    manifest: dict[str, Any] = {
        "run_id": run_id or f"t02-{uuid4().hex}",
        "source": source_info,
        "backup": None,
        "candidate": None,
        "tables": accounting,
        "rows": {"migrated": 0, "derived": 0, "archived": 0, "unmapped": 0},
        "unmapped": [],
        "warnings": [],
        "errors": [],
        "started_at": datetime.now(UTC).isoformat(),
    }
    if dry_run:
        _archive_non_runtime_tables(accounting)
        manifest["rows"] = _manifest_summary(accounting)
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        return manifest
    if candidate_path is None:
        raise MigrationError("candidate_path is required unless dry_run=True")
    candidate = _resolve(candidate_path)
    assert_candidate_b_database_open_allowed(candidate)
    if candidate == PRODUCTION_DATABASE:
        raise MigrationError("production database cannot be a T02-R candidate")
    if candidate.exists():
        raise MigrationError(f"refusing to overwrite existing candidate: {candidate}")
    if backup_path is None:
        raise MigrationError("backup_path is required for a real migration")
    backup = _resolve(backup_path)
    try:
        manifest["backup"] = create_backup(source, backup)
        migration_source = backup
        upgrade_candidate(candidate)
        legacy: sqlite3.Connection | None = None
        target: sqlite3.Connection | None = None
        try:
            legacy = _read_only(migration_source)
            assert_candidate_b_database_open_allowed(candidate)
            target = sqlite3.connect(candidate)
            target.execute("PRAGMA foreign_keys=ON")
            target.execute("PRAGMA busy_timeout=5000")
            warnings: list[str] = []
            project_ids: set[str] = set()
            for row in _rows(legacy, "projects"):
                try:
                    project_ids.add(_insert_project(target, row, warnings))
                    accounting["projects"]["migrated_rows"] += 1
                except Exception:
                    accounting["projects"]["unmapped_rows"] += 1
                    raise
            _, shot_count = _insert_sequences_and_shots(
                legacy, target, project_ids, accounting, warnings, manifest["unmapped"], strict
            )
            asset_count = _insert_document_assets(legacy, target, project_ids, accounting, manifest["unmapped"])
            if "asset_versions" in accounting:
                _insert_asset_versions(legacy, target, project_ids, accounting, manifest["unmapped"])
            shot_ids = {
                str(row[0]) for row in target.execute("SELECT id FROM shots").fetchall()
            }
            asset_ids = {
                str(row[0]) for row in target.execute("SELECT id FROM assets").fetchall()
            }
            _insert_artifacts(legacy, target, project_ids, shot_ids, asset_ids, accounting, manifest["unmapped"])
            _insert_tasks(legacy, target, project_ids, shot_ids, accounting, manifest["unmapped"])
            _derive_events(legacy, target, accounting)
            target.commit()
        except Exception as exc:
            if target is not None:
                target.rollback()
            manifest["errors"].append(str(exc))
            raise
        finally:
            if target is not None:
                target.close()
            if legacy is not None:
                legacy.close()
        _archive_non_runtime_tables(accounting)
        manifest["warnings"] = warnings
        manifest["candidate"] = assert_candidate_valid(candidate)
        manifest["candidate"]["embedded_shot_count"] = shot_count
        manifest["candidate"]["embedded_asset_count"] = asset_count
        manifest["rows"] = _manifest_summary(accounting)
    except (BackupError, MigrationError):
        raise
    finally:
        source_sha_after = _sha256(source_before)
        manifest["source_sha256_before"] = source_sha_before
        manifest["source_sha256_after"] = source_sha_after
        manifest["source_unchanged"] = source_sha_before == source_sha_after
        manifest["finished_at"] = datetime.now(UTC).isoformat()
        if manifest_path is not None:
            write_manifest(manifest_path, manifest)
    if not manifest["source_unchanged"]:
        raise MigrationError("source database changed during side-by-side migration")
    return manifest


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classification_counts(info: Mapping[str, Any]) -> dict[str, int]:
    """Count the six required classifications from a discovery result."""

    counts = {name: 0 for name in ("MIGRATE", "DERIVE", "ARCHIVE_ONLY", "LEGACY_ONLY", "EMPTY", "UNKNOWN")}
    for table in info["tables"]:
        classification = "EMPTY" if int(table["row_count"]) == 0 else table["classification"]
        counts[classification] = counts.get(classification, 0) + 1
    return counts
