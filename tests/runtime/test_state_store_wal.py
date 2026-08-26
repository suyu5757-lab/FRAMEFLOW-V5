from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path
from unittest import TestCase

from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from core.runtime.state_store import StateStore
from core.schemas.runtime_mvp import RUNTIME_TABLE_NAMES, metadata, projects


class StateStoreWalTests(TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="frameflow-state-store-")
        self.database_path = Path(self.temp_dir.name) / "state.db"
        self.store = StateStore(self.database_path, initialize=True)

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_wal_foreign_keys_and_busy_timeout_are_enabled(self) -> None:
        pragmas = self.store.pragmas()
        self.assertEqual("wal", str(pragmas["journal_mode"]).lower())
        self.assertEqual(1, pragmas["foreign_keys"])
        self.assertEqual(5000, pragmas["busy_timeout"])

    def test_all_11_tables_are_created_in_isolated_database(self) -> None:
        self.assertEqual(set(RUNTIME_TABLE_NAMES), set(self.store.table_names()))
        self.assertEqual(11, len(self.store.table_names()))

    def test_foreign_key_violation_is_rejected(self) -> None:
        with self.assertRaises(IntegrityError):
            self.store.create_sequence("SQ_BAD", "PRJ_MISSING", 1)

    def test_projects_sequences_shots_assets_artifacts_and_generations_crud(self) -> None:
        project = self.store.create_project("PRJ001", "Test", "16:9", 24, 12)
        sequence = self.store.create_sequence("SQ001", "PRJ001", 1)
        shot_spec = {
            "shot_id": "SH001",
            "sequence_id": "SQ001",
            "duration_sec": 4,
            "story_purpose": "Establish",
        }
        shot = self.store.create_shot(
            "SH001",
            "PRJ001",
            "SQ001",
            shot_spec,
            metadata={"source": "fixture"},
        )
        asset = self.store.create_asset("C001", "PRJ001", "character", "v01")
        artifact = self.store.create_artifact(
            "ART001",
            "PRJ001",
            "image",
            "master",
            "projects/PRJ001/assets/C001/v01.png",
            "v01",
            asset_id="C001",
            source_artifacts=[],
        )
        generation = self.store.create_generation("GEN001", "SH001", "ART001", "mock")

        self.assertEqual("Test", project["title"])
        self.assertEqual("PRJ001", sequence["project_id"])
        self.assertEqual(shot_spec, json.loads(shot["shot_spec_json"]))
        self.assertEqual({"source": "fixture"}, json.loads(shot["metadata_json"]))
        self.assertEqual("character", asset["type"])
        self.assertEqual("C001", artifact["asset_id"])
        self.assertEqual("ART001", generation["package_manifest_artifact_id"])

        self.store.update_project("PRJ001", {"title": "Updated"})
        self.store.update_sequence("SQ001", {"order_index": 2})
        self.store.update_shot("SH001", metadata={"source": "updated"})
        self.store.update_asset("C001", {"status": "LOCKED", "master_artifact_id": "ART001"})
        self.store.update_artifact("ART001", {"status": "APPROVED"})
        self.store.update_generation("GEN001", {"status": "RESULT_READY"})

        self.assertEqual("Updated", self.store.get_project("PRJ001")["title"])
        self.assertEqual(2, self.store.get_sequence("SQ001")["order_index"])
        self.assertEqual({"source": "updated"}, json.loads(self.store.get_shot("SH001")["metadata_json"]))
        self.assertEqual("LOCKED", self.store.get_asset("C001")["status"])
        self.assertEqual("APPROVED", self.store.get_artifact("ART001")["status"])
        self.assertEqual("RESULT_READY", self.store.get_generation("GEN001")["status"])
        self.assertEqual(1, len(self.store.list_projects()))
        self.assertEqual(1, len(self.store.list_generations()))

    def test_write_event_is_committed_with_entity(self) -> None:
        event = {
            "id": "EVT_PROJECT_1",
            "trace_id": "TRACE_PROJECT_1",
            "event_type": "project.created",
            "payload": {"actor": "test"},
        }
        self.store.create_project("PRJ001", "Test", "16:9", 24, 12, event=event)
        events = self.store.list("events")
        self.assertEqual(1, len(events))
        self.assertEqual("PRJ001", events[0]["entity_id"])
        self.assertEqual({"actor": "test"}, json.loads(events[0]["payload"]))

    def test_entity_and_event_roll_back_as_one_transaction(self) -> None:
        duplicate_event = {"id": "EVT_DUP", "trace_id": "TRACE_DUP", "event_type": "test"}
        self.store.create_project("PRJ001", "First", "16:9", 24, 12, event=duplicate_event)
        with self.assertRaises(IntegrityError):
            self.store.create_project("PRJ002", "Second", "16:9", 24, 12, event=duplicate_event)
        self.assertIsNone(self.store.get_project("PRJ002"))
        self.assertEqual(1, len(self.store.list("events")))

    def test_projects_and_shots_persist_after_store_restart(self) -> None:
        self.store.create_project("PRJ001", "Persistent", "16:9", 24, 5)
        self.store.create_sequence("SQ001", "PRJ001", 1)
        self.store.create_shot("SH001", "PRJ001", "SQ001", {"shot_id": "SH001"})
        self.store.close()

        restarted = StateStore(self.database_path)
        try:
            self.assertEqual("Persistent", restarted.get_project("PRJ001")["title"])
            self.assertEqual("SH001", restarted.get_shot("SH001")["id"])
        finally:
            restarted.close()

    def test_wal_file_is_observable_during_write(self) -> None:
        connection = self.store.engine.connect()
        transaction = connection.begin()
        try:
            connection.execute(
                insert(projects).values(
                    id="PRJ_WAL",
                    title="WAL",
                    aspect_ratio="16:9",
                    fps=24,
                    target_duration=1,
                )
            )
            self.assertTrue(self.store.wal_file_exists)
        finally:
            transaction.rollback()
            connection.close()

    def test_busy_timeout_allows_second_writer_after_first_releases_lock(self) -> None:
        first_connection = self.store.engine.connect()
        first_transaction = first_connection.begin()
        first_connection.execute(
            insert(projects).values(
                id="PRJ_LOCKED",
                title="Lock holder",
                aspect_ratio="16:9",
                fps=24,
                target_duration=1,
            )
        )
        started = threading.Event()
        result: dict[str, object] = {}

        def write_second_project() -> None:
            started.set()
            start = time.monotonic()
            try:
                self.store.create_project("PRJ_SECOND", "Second", "16:9", 24, 1)
                result["error"] = None
            except Exception as exc:  # pragma: no cover - assertion reports the concrete error
                result["error"] = exc
            finally:
                result["elapsed"] = time.monotonic() - start

        writer = threading.Thread(target=write_second_project)
        writer.start()
        self.assertTrue(started.wait(timeout=2))
        time.sleep(0.15)
        first_transaction.rollback()
        first_connection.close()
        writer.join(timeout=6)

        self.assertFalse(writer.is_alive())
        self.assertIsNone(result.get("error"))
        self.assertGreaterEqual(float(result["elapsed"]), 0.1)
        self.assertIsNotNone(self.store.get_project("PRJ_SECOND"))
