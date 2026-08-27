"""Minimal SQLite WAL StateStore for FRAMEFLOW V5.3.2 T03.

The store owns state persistence only. It deliberately does not implement a
TaskStore, queue, worker, provider submitter, or scheduler. Schema creation is
available for isolated test databases; production initialization is refused so
T03 cannot migrate the existing V3 database accidentally.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping
from uuid import uuid4

from sqlalchemy import Engine, create_engine, event, inspect, insert, select, text, update
from sqlalchemy.engine import Connection

from core.schemas.runtime_mvp import metadata


DEFAULT_DATABASE_PATH = Path(
    r"D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db"
)
_JSON_COLUMNS = {
    "shot_spec_json",
    "metadata_json",
    "source_artifacts_json",
    "payload_json",
    "result_json",
    "error_json",
    "qa_json",
    "payload",
}


def _database_url(path: Path | str) -> str:
    if str(path) == ":memory:":
        return "sqlite:///:memory:"
    return f"sqlite:///{Path(path).resolve(strict=False).as_posix()}"


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    return dict(value)


class StateStore:
    """Small transactional CRUD facade over the T02 Runtime MVP metadata."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        initialize: bool = False,
        echo: bool = False,
    ) -> None:
        raw_path = path if path is not None else DEFAULT_DATABASE_PATH
        self.path = raw_path if str(raw_path) == ":memory:" else Path(raw_path).resolve(strict=False)
        self.database_url = _database_url(raw_path)
        self._closed = False
        self.engine = create_engine(
            self.database_url,
            echo=echo,
            connect_args={"check_same_thread": False, "timeout": 5},
            pool_pre_ping=True,
        )
        event.listen(self.engine, "connect", self._configure_connection)
        if initialize:
            try:
                self.initialize()
            except Exception:
                self.dispose()
                raise

    @staticmethod
    def _configure_connection(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.fetchone()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()

    @property
    def wal_path(self) -> Path | None:
        if str(self.path) == ":memory:":
            return None
        return Path(f"{self.path}-wal")

    @property
    def wal_file_exists(self) -> bool:
        return bool(self.wal_path and self.wal_path.exists())

    def initialize(self) -> None:
        """Create the declared tables in an isolated database only."""

        if str(self.path).casefold() == str(DEFAULT_DATABASE_PATH.resolve()).casefold():
            raise RuntimeError(
                "T03 refuses online initialization of the production database; "
                "use a temporary test path"
            )
        with self.engine.begin() as connection:
            metadata.create_all(connection)

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        """Borrow a pooled connection and always return it to the engine."""

        if self._closed:
            raise RuntimeError("StateStore is closed")
        connection = self.engine.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        """Run a caller-supplied operation inside one explicit transaction."""

        if self._closed:
            raise RuntimeError("StateStore is closed")
        with self.engine.begin() as connection:
            yield connection

    def close(self) -> None:
        self.dispose()

    def dispose(self) -> None:
        """Close pooled DBAPI connections deterministically and idempotently."""

        if self._closed:
            return
        self.engine.dispose(close=True)
        self._closed = True

    def __enter__(self) -> "StateStore":
        return self

    def __exit__(self, _exc_type: Any, _exc_value: Any, _traceback: Any) -> None:
        self.close()

    def pragmas(self) -> dict[str, Any]:
        with self.connection() as connection:
            return {
                "journal_mode": connection.exec_driver_sql("PRAGMA journal_mode").scalar(),
                "foreign_keys": connection.exec_driver_sql("PRAGMA foreign_keys").scalar(),
                "busy_timeout": connection.exec_driver_sql("PRAGMA busy_timeout").scalar(),
            }

    def table_names(self) -> tuple[str, ...]:
        with self.connection() as connection:
            return tuple(sorted(inspect(connection).get_table_names()))

    @staticmethod
    def _normalize_values(values: Mapping[str, Any]) -> dict[str, Any]:
        normalized = dict(values)
        for key in _JSON_COLUMNS:
            if key in normalized and normalized[key] is not None:
                normalized[key] = _json_text(normalized[key])
        return normalized

    @staticmethod
    def _row(row: Any) -> dict[str, Any] | None:
        return dict(row._mapping) if row is not None else None

    @staticmethod
    def _event_values(
        event_spec: Mapping[str, Any],
        *,
        entity_type: str,
        entity_id: str,
        default_event_type: str,
    ) -> dict[str, Any]:
        values = dict(event_spec)
        values.setdefault("id", f"EVT_{uuid4().hex}")
        values.setdefault("trace_id", f"TRACE_{uuid4().hex}")
        values.setdefault("entity_type", entity_type)
        values.setdefault("entity_id", entity_id)
        values.setdefault("event_type", default_event_type)
        values.setdefault("payload", {})
        return StateStore._normalize_values(values)

    def _write_event(
        self,
        connection: Connection,
        event_spec: Mapping[str, Any] | None,
        *,
        entity_type: str,
        entity_id: str,
        default_event_type: str,
    ) -> None:
        if event_spec is None:
            return
        values = self._event_values(
            event_spec,
            entity_type=entity_type,
            entity_id=entity_id,
            default_event_type=default_event_type,
        )
        connection.execute(insert(metadata.tables["events"]).values(**values))

    def _create(
        self,
        table_name: str,
        values: Mapping[str, Any],
        *,
        entity_id: str,
        event: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        table = metadata.tables[table_name]
        normalized = self._normalize_values(values)
        with self.transaction() as connection:
            connection.execute(insert(table).values(**normalized))
            self._write_event(
                connection,
                event,
                entity_type=table_name,
                entity_id=entity_id,
                default_event_type=f"{table_name}.created",
            )
        result = self.get(table_name, entity_id)
        if result is None:
            raise RuntimeError(f"created {table_name} {entity_id} could not be read back")
        return result

    def get(self, table_name: str, entity_id: str) -> dict[str, Any] | None:
        table = metadata.tables[table_name]
        with self.connection() as connection:
            row = connection.execute(select(table).where(table.c.id == entity_id)).first()
        return self._row(row)

    def list(self, table_name: str) -> list[dict[str, Any]]:
        table = metadata.tables[table_name]
        with self.connection() as connection:
            rows = connection.execute(select(table).order_by(table.c.id)).all()
        return [self._row(row) for row in rows if row is not None]

    def _update(
        self,
        table_name: str,
        entity_id: str,
        changes: Mapping[str, Any] | None,
        *,
        event: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        table = metadata.tables[table_name]
        values = self._normalize_values(_mapping(changes))
        values.pop("id", None)
        if not values:
            result = self.get(table_name, entity_id)
            if result is None:
                raise KeyError(f"{table_name} not found: {entity_id}")
            return result
        with self.transaction() as connection:
            result = connection.execute(update(table).where(table.c.id == entity_id).values(**values))
            if result.rowcount != 1:
                raise KeyError(f"{table_name} not found: {entity_id}")
            self._write_event(
                connection,
                event,
                entity_type=table_name,
                entity_id=entity_id,
                default_event_type=f"{table_name}.updated",
            )
        updated = self.get(table_name, entity_id)
        if updated is None:
            raise RuntimeError(f"updated {table_name} {entity_id} could not be read back")
        return updated

    # Projects
    def create_project(
        self,
        project_id: str,
        title: str,
        aspect_ratio: str,
        fps: float,
        target_duration: float,
        *,
        status: str = "DRAFT",
        event: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._create(
            "projects",
            {
                "id": project_id,
                "title": title,
                "aspect_ratio": aspect_ratio,
                "fps": fps,
                "target_duration": target_duration,
                "status": status,
            },
            entity_id=project_id,
            event=event,
        )

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        return self.get("projects", project_id)

    def list_projects(self) -> list[dict[str, Any]]:
        return self.list("projects")

    def update_project(
        self,
        project_id: str,
        changes: Mapping[str, Any] | None = None,
        *,
        event: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self._update("projects", project_id, {**_mapping(changes), **kwargs}, event=event)

    # Sequences
    def create_sequence(
        self,
        sequence_id: str,
        project_id: str,
        order_index: int,
        *,
        event: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._create(
            "sequences",
            {"id": sequence_id, "project_id": project_id, "order_index": order_index},
            entity_id=sequence_id,
            event=event,
        )

    def get_sequence(self, sequence_id: str) -> dict[str, Any] | None:
        return self.get("sequences", sequence_id)

    def list_sequences(self) -> list[dict[str, Any]]:
        return self.list("sequences")

    def update_sequence(
        self,
        sequence_id: str,
        changes: Mapping[str, Any] | None = None,
        *,
        event: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self._update("sequences", sequence_id, {**_mapping(changes), **kwargs}, event=event)

    # Shots
    def create_shot(
        self,
        shot_id: str,
        project_id: str,
        sequence_id: str,
        shot_spec: Any,
        *,
        metadata: Any | None = None,
        continuity_in: Any | None = None,
        continuity_out: Any | None = None,
        event: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._create(
            "shots",
            {
                "id": shot_id,
                "project_id": project_id,
                "sequence_id": sequence_id,
                "shot_spec_json": shot_spec,
                "metadata_json": {} if metadata is None else metadata,
                "continuity_in": continuity_in,
                "continuity_out": continuity_out,
            },
            entity_id=shot_id,
            event=event,
        )

    def get_shot(self, shot_id: str) -> dict[str, Any] | None:
        return self.get("shots", shot_id)

    def list_shots(self) -> list[dict[str, Any]]:
        return self.list("shots")

    def update_shot(
        self,
        shot_id: str,
        changes: Mapping[str, Any] | None = None,
        *,
        event: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        merged = {**_mapping(changes), **kwargs}
        if "shot_spec" in merged:
            merged["shot_spec_json"] = merged.pop("shot_spec")
        if "metadata" in merged:
            merged["metadata_json"] = merged.pop("metadata")
        return self._update("shots", shot_id, merged, event=event)

    # Assets
    def create_asset(
        self,
        asset_id: str,
        project_id: str,
        asset_type: str,
        version: str,
        *,
        status: str = "DRAFT",
        master_artifact_id: str | None = None,
        locked_at: Any | None = None,
        event: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._create(
            "assets",
            {
                "id": asset_id,
                "project_id": project_id,
                "type": asset_type,
                "status": status,
                "version": version,
                "master_artifact_id": master_artifact_id,
                "locked_at": locked_at,
            },
            entity_id=asset_id,
            event=event,
        )

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        return self.get("assets", asset_id)

    def list_assets(self) -> list[dict[str, Any]]:
        return self.list("assets")

    def update_asset(
        self,
        asset_id: str,
        changes: Mapping[str, Any] | None = None,
        *,
        event: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self._update("assets", asset_id, {**_mapping(changes), **kwargs}, event=event)

    # Artifacts
    def create_artifact(
        self,
        artifact_id: str,
        project_id: str,
        artifact_type: str,
        role: str,
        path: str,
        version: str,
        *,
        shot_id: str | None = None,
        asset_id: str | None = None,
        sha256: str | None = None,
        source_task_id: str | None = None,
        source_artifacts: Any | None = None,
        status: str = "DRAFT",
        event: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._create(
            "artifacts",
            {
                "id": artifact_id,
                "project_id": project_id,
                "shot_id": shot_id,
                "asset_id": asset_id,
                "type": artifact_type,
                "role": role,
                "path": path,
                "sha256": sha256,
                "version": version,
                "source_task_id": source_task_id,
                "source_artifacts_json": [] if source_artifacts is None else source_artifacts,
                "status": status,
            },
            entity_id=artifact_id,
            event=event,
        )

    def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        return self.get("artifacts", artifact_id)

    def list_artifacts(self) -> list[dict[str, Any]]:
        return self.list("artifacts")

    def update_artifact(
        self,
        artifact_id: str,
        changes: Mapping[str, Any] | None = None,
        *,
        event: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self._update("artifacts", artifact_id, {**_mapping(changes), **kwargs}, event=event)

    # Generations (package manifests remain Artifact-linked)
    def create_generation(
        self,
        generation_id: str,
        shot_id: str,
        package_manifest_artifact_id: str,
        provider: str,
        *,
        status: str = "CREATED",
        event: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._create(
            "generations",
            {
                "id": generation_id,
                "shot_id": shot_id,
                "package_manifest_artifact_id": package_manifest_artifact_id,
                "provider": provider,
                "status": status,
            },
            entity_id=generation_id,
            event=event,
        )

    def get_generation(self, generation_id: str) -> dict[str, Any] | None:
        return self.get("generations", generation_id)

    def list_generations(self) -> list[dict[str, Any]]:
        return self.list("generations")

    def update_generation(
        self,
        generation_id: str,
        changes: Mapping[str, Any] | None = None,
        *,
        event: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self._update("generations", generation_id, {**_mapping(changes), **kwargs}, event=event)
