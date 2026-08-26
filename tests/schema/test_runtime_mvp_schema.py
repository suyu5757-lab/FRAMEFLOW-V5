from __future__ import annotations

from unittest import TestCase

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect

from core.schemas.runtime_mvp import (
    PROVIDER_CAPABILITY_V22_DEFAULTS,
    PROVIDER_CAPABILITY_V22_FIELDS,
    RUNTIME_PRAGMA_STATEMENTS,
    RUNTIME_TABLE_NAMES,
    metadata,
)


EXPECTED_COLUMNS = {
    "projects": {"id", "title", "aspect_ratio", "fps", "target_duration", "status", "created_at", "updated_at"},
    "sequences": {"id", "project_id", "order_index", "created_at"},
    "shots": {"id", "project_id", "sequence_id", "shot_spec_json", "metadata_json", "continuity_in", "continuity_out", "created_at", "updated_at"},
    "assets": {"id", "project_id", "type", "status", "version", "master_artifact_id", "locked_at", "created_at"},
    "artifacts": {"id", "project_id", "shot_id", "asset_id", "type", "role", "path", "sha256", "version", "source_task_id", "source_artifacts_json", "status", "created_at"},
    "tasks": {"id", "type", "project_id", "shot_id", "status", "priority", "idempotency_key", "attempt", "max_attempts", "timeout", "worker", "payload_json", "result_json", "error_json", "created_at", "started_at", "heartbeat_at", "finished_at"},
    "events": {"id", "trace_id", "entity_type", "entity_id", "event_type", "payload", "created_at"},
    "resource_locks": {"resource_id", "owner_task_id", "acquired_at", "heartbeat_at", "lease_timeout", "status"},
    "generations": {"id", "shot_id", "package_manifest_artifact_id", "provider", "status", "created_at"},
    "provider_submissions": {"id", "generation_id", "provider", "idempotency_key", "request_hash", "external_task_id", "attempt", "status", "submitted_at"},
    "reviews": {"id", "shot_id", "generation_id", "qa_json", "decision", "created_at"},
}


class RuntimeMvpSchemaTests(TestCase):
    def test_exactly_11_tables_are_declared(self) -> None:
        self.assertEqual(set(RUNTIME_TABLE_NAMES), set(metadata.tables))
        self.assertEqual(11, len(metadata.tables))
        for table_name, expected in EXPECTED_COLUMNS.items():
            self.assertEqual(expected, set(metadata.tables[table_name].columns.keys()))

    def test_v532_correction_columns_and_states_are_present(self) -> None:
        self.assertIn("metadata_json", metadata.tables["shots"].c)
        self.assertIn("master_artifact_id", metadata.tables["assets"].c)
        self.assertIn("asset_id", metadata.tables["artifacts"].c)
        self.assertIn("source_artifacts_json", metadata.tables["artifacts"].c)
        self.assertIn("payload_json", metadata.tables["tasks"].c)
        self.assertIn("result_json", metadata.tables["tasks"].c)
        self.assertIn("error_json", metadata.tables["tasks"].c)
        self.assertIn("resource_locks", metadata.tables)
        self.assertIn("package_manifest_artifact_id", metadata.tables["generations"].c)
        self.assertNotIn("package_id", metadata.tables["generations"].c)
        self.assertIn("shot_spec_version", metadata.tables["provider_submissions"].c.idempotency_key.comment)
        task_constraints = " ".join(str(constraint.sqltext) for constraint in metadata.tables["tasks"].constraints if hasattr(constraint, "sqltext"))
        self.assertIn("WAITING_FOR_RESOURCE", task_constraints)
        self.assertIn("CANCELLED", task_constraints)

    def test_pragmas_are_declared(self) -> None:
        self.assertEqual(
            (
                "PRAGMA journal_mode=WAL;",
                "PRAGMA foreign_keys=ON;",
                "PRAGMA busy_timeout=5000;",
            ),
            RUNTIME_PRAGMA_STATEMENTS,
        )

    def test_provider_capability_cost_fields_are_declared_outside_runtime_tables(self) -> None:
        self.assertIn("estimated_cost_per_submit", PROVIDER_CAPABILITY_V22_FIELDS)
        self.assertIn("last_verified_at", PROVIDER_CAPABILITY_V22_FIELDS)
        self.assertIsNone(PROVIDER_CAPABILITY_V22_DEFAULTS["estimated_cost_per_submit"])
        self.assertIsNone(PROVIDER_CAPABILITY_V22_DEFAULTS["last_verified_at"])

    def test_declaration_creates_11_tables_in_memory_only(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            metadata.create_all(connection)
            table_names = set(inspect(connection).get_table_names())
        self.assertEqual(set(RUNTIME_TABLE_NAMES), table_names)

    def test_every_table_compiles_for_sqlite(self) -> None:
        dialect = sqlite_dialect()
        for table in metadata.sorted_tables:
            ddl = str(CreateTable(table).compile(dialect=dialect))
            self.assertIn(f"CREATE TABLE {table.name}", ddl)
