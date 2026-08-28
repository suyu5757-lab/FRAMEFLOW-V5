from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from core.migration.backup import (
    BackupError,
    PRODUCTION_DATABASE,
    create_backup,
    restore_backup,
    verify_backup,
)
from core.migration.online import downgrade_candidate, upgrade_candidate
from core.migration.v3_to_v5 import (
    classification_counts,
    inspect_legacy_database,
    migrate_v3_to_v5,
)
from core.migration.equivalence import logical_data_fingerprint
from core.migration.validation import validate_candidate
from core.runtime.state_store import StateStore
from core.schemas.runtime_mvp import RUNTIME_TABLE_NAMES
from tests.conftest import isolated_legacy_v3_path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


LEGACY_SHOTS = [
    {
        "id": "SH001",
        "sequenceId": "SQ001",
        "duration": 4,
        "purpose": "Establish the crossing.",
        "characters": [{"id": "C001"}],
        "scene": {"id": "S001"},
        "props": [{"id": "P001"}],
        "action": "Walks into frame.",
        "camera": {"size": "medium", "height": "eye", "angle": "front", "motion": "static"},
        "status": "approved",
    },
    {
        "shotId": "SH002",
        "sequence_id": "SQ001",
        "durationSec": 5,
        "storyPurpose": "Reveal the threat.",
        "characterIds": ["C001", "C002"],
        "sceneId": "S001",
        "propIds": ["P002"],
        "subjectAction": "Turns toward the sound.",
        "startState": {"facing": "left"},
        "endState": {"facing": "right"},
        "firstFrameArtifactId": "ART001",
        "lastFrameArtifactId": "ART002",
        "status": "ready",
        "visualStyle": "cinematic",
    },
    {"id": "SH003", "characters": [], "action": "Hold."},
]


def unique_path(label: str, suffix: str = ".db") -> Path:
    return Path(tempfile.gettempdir()) / f"frameflow-t02-{label}-{uuid.uuid4().hex}{suffix}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_legacy_fixture(path: Path, *, invalid_shot: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    shots = json.loads(json.dumps(LEGACY_SHOTS))
    if invalid_shot:
        shots[0]["duration"] = 0
    document = {
        "id": "PRJ001",
        "name": "Legacy Project",
        "ratio": "16:9",
        "fps": 24,
        "duration": 12,
        "shots": shots,
        "assets": [{"id": "AS_DOC", "type": "character", "status": "LOCKED", "version": 1}],
    }
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
            CREATE TABLE projects (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, document_json TEXT NOT NULL,
                revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                lifecycle_status TEXT NOT NULL
            );
            CREATE TABLE artifacts (
                id TEXT PRIMARY KEY, project_id TEXT, artifact_type TEXT NOT NULL,
                role TEXT, version INTEGER NOT NULL, local_path TEXT NOT NULL,
                sha256 TEXT NOT NULL, metadata_json TEXT NOT NULL, task_id TEXT,
                logical_asset_id TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE asset_versions (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, logical_asset_id TEXT NOT NULL,
                asset_class TEXT NOT NULL, version INTEGER NOT NULL, artifact_id TEXT NOT NULL,
                status TEXT NOT NULL, created_at TEXT NOT NULL, approved_at TEXT
            );
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY, project_id TEXT, task_type TEXT NOT NULL,
                status TEXT NOT NULL, provider_profile_id TEXT, request_json TEXT NOT NULL,
                result_json TEXT, error_kind TEXT, error_message TEXT, attempts INTEGER NOT NULL,
                provider_task_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE audit_events_v16 (
                id TEXT PRIMARY KEY, project_id TEXT, actor TEXT NOT NULL, action TEXT NOT NULL,
                target_type TEXT NOT NULL, target_id TEXT NOT NULL, reason TEXT NOT NULL,
                before_json TEXT NOT NULL, after_json TEXT NOT NULL, result TEXT NOT NULL,
                metadata_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE provider_profiles (
                id TEXT PRIMARY KEY, provider_type TEXT NOT NULL, display_name TEXT NOT NULL
            );
            """
        )
        now = "2026-08-26T00:00:00+00:00"
        connection.execute("INSERT INTO schema_migrations VALUES(16,?)", (now,))
        connection.execute(
            "INSERT INTO projects VALUES(?,?,?,?,?,?,?)",
            ("PRJ001", "Legacy Project", json.dumps(document), 1, now, now, "active"),
        )
        connection.executemany(
            "INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("ART001", "PRJ001", "image", "first_frame", 1, r"D:\media\art001.png", "a" * 64, '{"shot_id":"SH001"}', None, "AS001", "approved", now),
                ("ART002", "PRJ001", "image", "last_frame", 1, r"D:\media\art002.png", "b" * 64, '{"shot_id":"SH002"}', None, "AS001", "approved", now),
            ],
        )
        connection.execute(
            "INSERT INTO asset_versions VALUES(?,?,?,?,?,?,?,?,?)",
            ("ASV001", "PRJ001", "AS001", "character", 1, "ART001", "LOCKED", now, now),
        )
        connection.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("TASK001", "PRJ001", "generation", "queued", None, '{"shot_id":"SH001","idempotency_key":"legacy-key"}', None, None, None, 1, None, now, now),
        )
        connection.execute(
            "INSERT INTO audit_events_v16 VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            ("AUD001", "PRJ001", "tester", "project_import", "project", "PRJ001", "fixture", "{}", "{}", "ok", "{}", now),
        )
        connection.execute("INSERT INTO provider_profiles VALUES(?,?,?)", ("PROV001", "jimeng_cli", "Fixture CLI"))
        connection.commit()
    finally:
        connection.close()


class T02RuntimeMigrationTests(unittest.TestCase):
    def test_repeated_migrations_are_logically_deterministic_across_seconds(self) -> None:
        source = unique_path("deterministic-source")
        candidate_a = unique_path("deterministic-a")
        candidate_b = unique_path("deterministic-b")
        backup_a = unique_path("deterministic-backup-a")
        backup_b = unique_path("deterministic-backup-b")
        create_legacy_fixture(source)
        migrate_v3_to_v5(source, candidate_a, backup_path=backup_a)
        time.sleep(1.1)
        migrate_v3_to_v5(source, candidate_b, backup_path=backup_b)
        self.assertEqual(
            logical_data_fingerprint(candidate_a)["sha256"],
            logical_data_fingerprint(candidate_b)["sha256"],
        )

    def test_legacy_discovery_returns_full_schema_facts_and_classification(self) -> None:
        source = unique_path("discovery")
        create_legacy_fixture(source)
        info = inspect_legacy_database(source)
        self.assertEqual(7, info["table_count"])
        projects = next(item for item in info["tables"] if item["name"] == "projects")
        self.assertEqual(1, projects["row_count"])
        self.assertIn("document_json", {column["name"] for column in projects["columns"]})
        self.assertEqual("MIGRATE", projects["classification"])
        counts = classification_counts(info)
        self.assertEqual(4, counts["MIGRATE"])
        self.assertEqual(1, counts["DERIVE"])
        self.assertEqual(1, counts["ARCHIVE_ONLY"])
        self.assertEqual(1, counts["LEGACY_ONLY"])
        self.assertEqual(0, counts["UNKNOWN"])

    def test_side_by_side_db_migration_preserves_three_shots_and_reads_with_state_store(self) -> None:
        source = unique_path("db-source")
        backup = unique_path("db-backup")
        candidate = unique_path("db-candidate")
        create_legacy_fixture(source)
        before = sha256(source)
        manifest = migrate_v3_to_v5(source, candidate, backup_path=backup)
        self.assertTrue(manifest["source_unchanged"])
        self.assertEqual(before, sha256(source))
        self.assertEqual(1, manifest["tables"]["projects"]["migrated_rows"])
        self.assertEqual(2, manifest["tables"]["artifacts"]["migrated_rows"])
        self.assertEqual(1, manifest["tables"]["tasks"]["migrated_rows"])
        self.assertEqual(1, manifest["tables"]["audit_events_v16"]["derived_rows"])
        self.assertEqual(0, manifest["rows"]["unmapped"])
        self.assertEqual(set(RUNTIME_TABLE_NAMES), set(manifest["candidate"]["domain_tables"]))

        with StateStore(candidate, initialize=False) as store:
            self.assertEqual(set(RUNTIME_TABLE_NAMES), set(store.table_names()) - {"alembic_version"})
            self.assertEqual(1, len(store.list_projects()))
            self.assertEqual(1, len(store.list_sequences()))
            self.assertEqual(["SH001", "SH002", "SH003"], [row["id"] for row in store.list_shots()])
            self.assertEqual(2, len(store.list_artifacts()))
            self.assertEqual(1, len(store.list("tasks")))
            self.assertEqual(1, len(store.list("events")))
            self.assertEqual({"journal_mode": "wal", "foreign_keys": 1, "busy_timeout": 5000}, store.pragmas())

    def test_dry_run_does_not_create_candidate_and_existing_candidate_is_rejected(self) -> None:
        source = unique_path("dry-run-source")
        candidate = unique_path("dry-run-candidate")
        create_legacy_fixture(source)
        manifest = migrate_v3_to_v5(source, dry_run=True)
        self.assertIsNone(manifest["candidate"])
        self.assertFalse(candidate.exists())
        candidate.write_bytes(b"existing candidate")
        with self.assertRaisesRegex(RuntimeError, "overwrite existing candidate"):
            migrate_v3_to_v5(source, candidate, backup_path=unique_path("dry-run-backup"))

    def test_online_upgrade_downgrade_and_upgrade_again_are_real(self) -> None:
        candidate = unique_path("online-cycle")
        upgrade_candidate(candidate)
        first = validate_candidate(candidate)
        self.assertEqual([], first["errors"])
        connection = sqlite3.connect(candidate)
        try:
            self.assertEqual([("20260826_01",)], connection.execute("SELECT version_num FROM alembic_version").fetchall())
        finally:
            connection.close()
        downgrade_candidate(candidate)
        connection = sqlite3.connect(candidate)
        try:
            self.assertEqual([], connection.execute("SELECT version_num FROM alembic_version").fetchall())
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT IN ('alembic_version','sqlite_sequence')").fetchone()[0])
        finally:
            connection.close()
        upgrade_candidate(candidate)
        self.assertEqual([], validate_candidate(candidate)["errors"])

    def test_backup_restore_and_production_path_guards(self) -> None:
        source = unique_path("backup-source")
        backup = unique_path("backup")
        restored = unique_path("restored")
        create_legacy_fixture(source)
        metadata = create_backup(source, backup)
        self.assertEqual("ok", metadata["integrity_check"])
        self.assertEqual(metadata["backup_sha256"], verify_backup(backup)["backup_sha256"])
        restore_backup(backup, restored)
        connection = sqlite3.connect(restored)
        try:
            connection.execute("UPDATE projects SET name='mutated copy' WHERE id='PRJ001'")
            connection.commit()
        finally:
            connection.close()
        restore_backup(backup, restored)
        connection = sqlite3.connect(restored)
        try:
            self.assertEqual("Legacy Project", connection.execute("SELECT name FROM projects WHERE id='PRJ001'").fetchone()[0])
        finally:
            connection.close()
        with self.assertRaises(BackupError):
            create_backup(source, PRODUCTION_DATABASE)
        with self.assertRaises(BackupError):
            restore_backup(backup, PRODUCTION_DATABASE)

    def test_production_backup_is_read_only_and_hash_unchanged(self) -> None:
        legacy_source = isolated_legacy_v3_path("migration-backup-source")
        before = sha256(legacy_source)
        backup = unique_path("production-backup")
        metadata = create_backup(legacy_source, backup)
        after = sha256(legacy_source)
        self.assertEqual(before, after)
        self.assertEqual(verify_backup(legacy_source)["table_count"], metadata["table_count"])
        self.assertEqual("ok", metadata["integrity_check"])

    def test_failure_injection_invalid_shot_leaves_source_untouched(self) -> None:
        source = unique_path("invalid-shot-source")
        backup = unique_path("invalid-shot-backup")
        candidate = unique_path("invalid-shot-candidate")
        create_legacy_fixture(source, invalid_shot=True)
        before = sha256(source)
        with self.assertRaises(RuntimeError):
            migrate_v3_to_v5(source, candidate, backup_path=backup, strict=True)
        self.assertEqual(before, sha256(source))
        connection = sqlite3.connect(candidate)
        try:
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0])
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM shots").fetchone()[0])
        finally:
            connection.close()

    def test_bad_fk_and_schema_drift_are_detected(self) -> None:
        candidate = unique_path("failure-validation")
        upgrade_candidate(candidate)
        connection = sqlite3.connect(candidate)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO resource_locks(resource_id,owner_task_id,acquired_at,heartbeat_at) VALUES(?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                    ("PS", "MISSING_TASK"),
                )
            connection.execute("ALTER TABLE projects ADD COLUMN drift TEXT")
            connection.commit()
        finally:
            connection.close()
        self.assertTrue(validate_candidate(candidate)["errors"])

    def test_corrupt_source_and_production_candidate_abort(self) -> None:
        corrupt = unique_path("corrupt", ".db")
        corrupt.write_bytes(b"not a sqlite database")
        with self.assertRaises(RuntimeError):
            inspect_legacy_database(corrupt)
        with self.assertRaises(BackupError):
            upgrade_candidate(PRODUCTION_DATABASE)


if __name__ == "__main__":
    unittest.main()
