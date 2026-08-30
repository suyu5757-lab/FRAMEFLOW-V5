"""T04 project manifest exporter.

The exporter is deliberately a projection of the V5 Runtime database.  It
does not create a second source of truth and it never writes to SQLite.  The
file writer is separate so that the byte-preserving failure contract can be
tested without involving the database.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import select

from core.schemas.runtime_mvp import metadata
from frameflow.idempotency import canonical_json


PROJECT_MANIFEST_VERSION = 1
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
_JSON_COLUMNS = frozenset(
    {"shot_spec_json", "metadata_json", "source_artifacts_json", "qa_json"}
)
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|auth(?:orization)?|credential|password|secret|token)",
    re.IGNORECASE,
)


class ManifestExportError(RuntimeError):
    """Raised when a manifest cannot be safely built or atomically written."""

    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


def _safe_id(value: str) -> str:
    value = str(value)
    if not _SAFE_ID.fullmatch(value):
        raise ManifestExportError("INVALID_PROJECT_ID", "project_id is not a safe identifier.", {"project_id": value})
    return value


def _safe_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): None if _SENSITIVE_KEY.search(str(key)) else _safe_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not _SENSITIVE_KEY.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


def _decode_json(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return _safe_value(value)
    try:
        return _safe_value(json.loads(value))
    except json.JSONDecodeError:
        return _safe_value(value)


def _record(row: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in row.items():
        if _SENSITIVE_KEY.search(str(key)):
            continue
        result[str(key)] = _decode_json(value) if key in _JSON_COLUMNS else _safe_value(value)
    return result


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class AtomicJsonWriter:
    """Write one canonical JSON document using temp-file replacement."""

    def write(self, path: Path | str, payload: Mapping[str, Any]) -> Path:
        final_path = Path(path).resolve(strict=False)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = final_path.with_name(f".{final_path.name}.{uuid4().hex}.tmp")
        try:
            with temp_path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(canonical_json(payload))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, final_path)
            return final_path
        except Exception:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
            raise


class ManifestExporter:
    """Export the authoritative project/shot asset and review snapshot."""

    def __init__(
        self,
        store: Any,
        *,
        projects_root: Path | str | None = None,
        writer: AtomicJsonWriter | None = None,
    ) -> None:
        self.store = store
        self.projects_root = (
            Path(projects_root).resolve(strict=False)
            if projects_root is not None
            else (Path(store.path).parent / "projects").resolve(strict=False)
        )
        self.writer = writer or AtomicJsonWriter()

    def project_root(self, project_id: str) -> Path:
        project_id = _safe_id(project_id)
        root = (self.projects_root / project_id).resolve(strict=False)
        if root.parent != self.projects_root:
            raise ManifestExportError("UNSAFE_PROJECT_PATH", "Project path escaped projects root.")
        return root

    def build_manifest(self, project_id: str) -> dict[str, Any]:
        project_id = _safe_id(project_id)
        table = metadata.tables
        with self.store.connection() as connection:
            project_row = connection.execute(
                select(table["projects"]).where(table["projects"].c.id == project_id)
            ).mappings().first()
            if project_row is None:
                raise ManifestExportError("PROJECT_NOT_FOUND", "Project does not exist.", {"project_id": project_id})

            sequence_rows = connection.execute(
                select(table["sequences"])
                .where(table["sequences"].c.project_id == project_id)
                .order_by(table["sequences"].c.order_index, table["sequences"].c.id)
            ).mappings().all()
            shot_rows = connection.execute(
                select(table["shots"])
                .where(table["shots"].c.project_id == project_id)
                .order_by(table["shots"].c.id)
            ).mappings().all()
            asset_rows = connection.execute(
                select(table["assets"])
                .where(table["assets"].c.project_id == project_id)
                .order_by(table["assets"].c.id)
            ).mappings().all()
            artifact_rows = connection.execute(
                select(table["artifacts"])
                .where(table["artifacts"].c.project_id == project_id)
                .order_by(table["artifacts"].c.id)
            ).mappings().all()
            shot_ids = [str(row["id"]) for row in shot_rows]
            generation_rows = (
                connection.execute(
                    select(table["generations"])
                    .where(table["generations"].c.shot_id.in_(shot_ids))
                    .order_by(table["generations"].c.created_at, table["generations"].c.id)
                ).mappings().all()
                if shot_ids
                else []
            )
            review_rows = (
                connection.execute(
                    select(table["reviews"])
                    .where(table["reviews"].c.shot_id.in_(shot_ids))
                    .order_by(table["reviews"].c.created_at, table["reviews"].c.id)
                ).mappings().all()
                if shot_ids
                else []
            )

        # The allow-list above intentionally excludes tasks, event payloads,
        # provider submission request data, and resource-lock state.
        return {
            "manifest_type": "FRAMEFLOW_V5_PROJECT_MANIFEST",
            "manifest_version": PROJECT_MANIFEST_VERSION,
            "project_id": project_id,
            "project": _record(project_row),
            "sequences": [_record(row) for row in sequence_rows],
            "shots": [_record(row) for row in shot_rows],
            "assets": [_record(row) for row in asset_rows],
            "artifacts": [_record(row) for row in artifact_rows],
            "generations": [_record(row) for row in generation_rows],
            "reviews": [_record(row) for row in review_rows],
        }

    def export_project(self, project_id: str, destination: Path | str | None = None) -> dict[str, Any]:
        project_id = _safe_id(project_id)
        project_root = self.project_root(project_id)
        final_path = (
            project_root / "project_manifest.json"
            if destination is None
            else Path(destination).resolve(strict=False)
        )
        if not _within(final_path, project_root):
            raise ManifestExportError(
                "MANIFEST_PATH_ESCAPE",
                "Manifest destination must stay inside the project root.",
                {"path": str(final_path), "project_root": str(project_root)},
            )
        manifest = self.build_manifest(project_id)
        written = self.writer.write(final_path, manifest)
        digest = hashlib.sha256(written.read_bytes()).hexdigest()
        return {
            "status": "EXPORTED",
            "project_id": project_id,
            "manifest_path": str(written),
            "manifest_sha256": digest,
            "manifest": manifest,
        }


__all__ = [
    "AtomicJsonWriter",
    "ManifestExportError",
    "ManifestExporter",
    "PROJECT_MANIFEST_VERSION",
]
