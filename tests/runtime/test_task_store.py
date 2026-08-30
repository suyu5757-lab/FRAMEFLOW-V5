from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from core.runtime.state_store import StateStore, TaskState, TaskStore


class TaskStoreTests(TestCase):
    def setUp(self) -> None:
        test_root = Path(os.environ.get("FRAMEFLOW_TEST_TMP", Path(".tmp") / "tests"))
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(
            dir=test_root,
            prefix="task-store-t05-",
        )
        self.database_path = Path(self.temp_dir.name) / "tasks.db"
        self.state_store = StateStore(self.database_path, initialize=True)
        self.task_store = TaskStore(self.state_store)
        self.state_store.create_project("PRJ_T05", "T05 Project", "16:9", 24, 12)

    def tearDown(self) -> None:
        self.state_store.close()
        self.temp_dir.cleanup()

    def test_t05_01_create_and_read(self) -> None:
        created_at = datetime(2026, 8, 30, 2, 0, tzinfo=UTC)
        payload = {"shot_id": "SH_T05", "parameters": {"quality": "draft", "frames": [1, 2]}}
        task = self.task_store.create(
            task_id="TASK_T05_01",
            task_type="prepare_reference",
            project_id="PRJ_T05",
            priority=7,
            idempotency_key="t05-create-01",
            attempt=1,
            max_attempts=4,
            timeout=90,
            worker="manual",
            payload=payload,
            created_at=created_at,
        )

        self.assertEqual("TASK_T05_01", task["id"])
        self.assertEqual("prepare_reference", task["type"])
        self.assertEqual("PRJ_T05", task["project_id"])
        self.assertEqual("CREATED", task["status"])
        self.assertEqual(7, task["priority"])
        self.assertEqual(1, task["attempt"])
        self.assertEqual(4, task["max_attempts"])
        self.assertEqual(payload, json.loads(task["payload_json"]))
        self.assertEqual(task, self.task_store.get("TASK_T05_01"))
        self.assertIsNone(self.task_store.get("TASK_MISSING"))

    def test_t05_02_persistence_across_reopen(self) -> None:
        self.task_store.create(
            task_id="TASK_T05_02",
            task_type="persist",
            project_id="PRJ_T05",
            payload={"nested": [True, {"value": 3}]},
        )
        self.state_store.close()
        self.state_store = StateStore(self.database_path)
        self.task_store = TaskStore(self.state_store)

        reopened = self.task_store.get("TASK_T05_02")
        self.assertIsNotNone(reopened)
        self.assertEqual({"nested": [True, {"value": 3}]}, json.loads(reopened["payload_json"]))

    def test_t05_03_state_and_lifecycle_fields_persist(self) -> None:
        self.task_store.create(task_id="TASK_T05_03", task_type="lifecycle", project_id="PRJ_T05")
        base = datetime(2026, 8, 30, 2, 0, tzinfo=UTC)
        transitions = (
            (TaskState.QUEUED, {"attempt": 1}),
            (TaskState.RUNNING, {"worker": "worker-t05", "started_at": base, "heartbeat_at": base}),
            (
                TaskState.SUCCEEDED,
                {"heartbeat_at": base + timedelta(seconds=5), "finished_at": base + timedelta(seconds=6)},
            ),
        )
        for status, changes in transitions:
            self.task_store.update("TASK_T05_03", status=status, **changes)

        task = self.task_store.get("TASK_T05_03")
        self.assertEqual("SUCCEEDED", task["status"])
        self.assertEqual("worker-t05", task["worker"])
        self.assertEqual(1, task["attempt"])
        self.assertIsNotNone(task["started_at"])
        self.assertIsNotNone(task["heartbeat_at"])
        self.assertIsNotNone(task["finished_at"])

    def test_t05_04_payload_round_trip(self) -> None:
        payload = {"unicode": "镜头", "nullable": None, "items": [1, 2, {"ok": True}]}
        self.task_store.create(task_id="TASK_T05_04", task_type="payload", project_id="PRJ_T05", payload=payload)
        self.task_store.update("TASK_T05_04", payload={"replaced": ["payload"]})
        task = self.task_store.get("TASK_T05_04")
        self.assertEqual({"replaced": ["payload"]}, json.loads(task["payload_json"]))

    def test_t05_05_result_round_trip(self) -> None:
        self.task_store.create(task_id="TASK_T05_05", task_type="result", project_id="PRJ_T05")
        result = {"artifact_ids": ["ART_001"], "metrics": {"duration_ms": 42}}
        self.task_store.update("TASK_T05_05", status=TaskState.SUCCEEDED, result=result)
        task = self.task_store.get("TASK_T05_05")
        self.assertEqual(result, json.loads(task["result_json"]))

    def test_t05_06_error_round_trip(self) -> None:
        self.task_store.create(task_id="TASK_T05_06", task_type="error", project_id="PRJ_T05")
        error = {"kind": "provider_timeout", "message": "upstream timed out", "retryable": True}
        self.task_store.update("TASK_T05_06", status=TaskState.FAILED, error=error)
        task = self.task_store.get("TASK_T05_06")
        self.assertEqual(error, json.loads(task["error_json"]))

    def test_t05_07_nullable_shot_and_nonnullable_project_contract(self) -> None:
        task = self.task_store.create(task_id="TASK_T05_07", task_type="nullable", project_id="PRJ_T05")
        self.assertIsNone(task["shot_id"])
        with self.assertRaises(IntegrityError):
            self.task_store.create(task_id="TASK_T05_07_BAD", task_type="nullable", project_id=None)
        self.assertIsNone(self.task_store.get("TASK_T05_07_BAD"))

    def test_t05_08_invalid_task_state_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.task_store.create(
                task_id="TASK_T05_08",
                task_type="invalid-state",
                project_id="PRJ_T05",
                status="NOT_A_REAL_STATE",
            )
        self.assertIsNone(self.task_store.get("TASK_T05_08"))

    def test_t05_09_failed_write_rolls_back_without_partial_task(self) -> None:
        self.task_store.create(task_id="TASK_T05_09", task_type="rollback", project_id="PRJ_T05")
        with self.assertRaises(IntegrityError):
            self.task_store.create(
                task_id="TASK_T05_09",
                task_type="rollback-retry",
                project_id="PRJ_T05",
                payload={"must_not": "replace"},
            )
        task = self.task_store.get("TASK_T05_09")
        self.assertEqual("rollback", task["type"])
        self.assertEqual({}, json.loads(task["payload_json"]))

    def test_t05_10_minimal_query_filters(self) -> None:
        self.task_store.create(task_id="TASK_T05_10_A", task_type="query", project_id="PRJ_T05")
        self.task_store.create(task_id="TASK_T05_10_B", task_type="query", project_id="PRJ_T05", status=TaskState.RUNNING)
        self.task_store.create(task_id="TASK_T05_10_C", task_type="query", project_id="PRJ_T05", status=TaskState.RUNNING)

        self.assertEqual(
            ["TASK_T05_10_B", "TASK_T05_10_C"],
            [task["id"] for task in self.task_store.list(status=TaskState.RUNNING, project_id="PRJ_T05")],
        )
        self.assertEqual(
            ["TASK_T05_10_A"],
            [task["id"] for task in self.task_store.list(status=TaskState.CREATED, shot_id=None)],
        )

    def test_t05_11_all_contract_states_are_persistable(self) -> None:
        for index, state in enumerate(TaskState):
            task_id = f"TASK_T05_11_{index}"
            self.task_store.create(task_id=task_id, task_type="state", project_id="PRJ_T05", status=state)
            self.assertEqual(state.value, self.task_store.get(task_id)["status"])


if __name__ == "__main__":
    import unittest

    unittest.main()
