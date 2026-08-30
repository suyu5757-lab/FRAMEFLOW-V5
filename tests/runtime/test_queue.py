from __future__ import annotations

import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase

from sqlalchemy.exc import IntegrityError

from core.runtime.queue import RetryNotEligible, TaskNotCancellable, TaskQueue
from core.runtime.state_store import StateStore, TaskState, TaskStore


class QueueMvpTests(TestCase):
    def setUp(self) -> None:
        test_root = Path(os.environ.get("FRAMEFLOW_TEST_TMP", Path(".tmp") / "tests"))
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=test_root, prefix="queue-t06-")
        self.database_path = Path(self.temp_dir.name) / "queue.db"
        self.state_store = StateStore(self.database_path, initialize=True)
        self.task_store = TaskStore(self.state_store)
        self.queue = TaskQueue(self.task_store)
        self.state_store.create_project("PRJ_T06", "T06 Project", "16:9", 24, 12)

    def tearDown(self) -> None:
        self.state_store.close()
        self.temp_dir.cleanup()

    def create_task(self, task_id: str, **kwargs):
        return self.task_store.create(
            task_id=task_id,
            task_type=kwargs.pop("task_type", "queue-test"),
            project_id="PRJ_T06",
            **kwargs,
        )

    def test_t06_01_enqueue_persists_across_reopen(self) -> None:
        self.create_task("TASK_T06_01")
        queued = self.queue.enqueue("TASK_T06_01")
        self.assertEqual("QUEUED", queued["status"])
        self.assertEqual(0, queued["attempt"])
        self.state_store.close()
        self.state_store = StateStore(self.database_path)
        self.task_store = TaskStore(self.state_store)
        self.queue = TaskQueue(self.task_store)
        self.assertEqual("QUEUED", self.task_store.get("TASK_T06_01")["status"])

    def test_t06_02_priority_ordering(self) -> None:
        created_at = datetime(2026, 8, 30, 3, 0, tzinfo=UTC)
        for task_id, priority in (("TASK_LOW", 1), ("TASK_HIGH", 9), ("TASK_MID", 4)):
            self.create_task(task_id, priority=priority, created_at=created_at)
            self.queue.enqueue(task_id)
        self.assertEqual("TASK_HIGH", self.queue.peek()["id"])
        self.assertEqual("TASK_HIGH", self.queue.claim_next()["id"])
        self.assertEqual("TASK_MID", self.queue.claim_next()["id"])
        self.assertEqual("TASK_LOW", self.queue.claim_next()["id"])

    def test_t06_03_same_priority_uses_fifo_then_id(self) -> None:
        created_at = datetime(2026, 8, 30, 3, 0, tzinfo=UTC)
        for task_id in ("TASK_A", "TASK_B"):
            self.create_task(task_id, priority=5, created_at=created_at)
            self.queue.enqueue(task_id)
        self.assertEqual("TASK_A", self.queue.peek()["id"])
        self.assertEqual("TASK_A", self.queue.claim_next()["id"])
        self.assertEqual("TASK_B", self.queue.claim_next()["id"])

    def test_t06_04_peek_is_read_only(self) -> None:
        self.create_task("TASK_T06_04")
        self.queue.enqueue("TASK_T06_04")
        before = self.task_store.get("TASK_T06_04")
        self.assertEqual("TASK_T06_04", self.queue.peek()["id"])
        self.assertEqual(before, self.task_store.get("TASK_T06_04"))

    def test_t06_05_claim_ignores_ineligible_states(self) -> None:
        self.create_task("TASK_CANCEL", status=TaskState.CANCELLED)
        self.create_task("TASK_DONE", status=TaskState.SUCCEEDED)
        self.create_task("TASK_RUNNING", status=TaskState.RUNNING)
        self.create_task("TASK_QUEUE")
        self.queue.enqueue("TASK_QUEUE")
        claimed = self.queue.claim_next()
        self.assertEqual("TASK_QUEUE", claimed["id"])
        self.assertEqual("RUNNING", self.task_store.get("TASK_QUEUE")["status"])

    def test_t06_06_atomic_double_claim_has_one_winner(self) -> None:
        self.create_task("TASK_SINGLE")
        self.queue.enqueue("TASK_SINGLE")
        store_a = StateStore(self.database_path)
        store_b = StateStore(self.database_path)
        queue_a = TaskQueue(TaskStore(store_a))
        queue_b = TaskQueue(TaskStore(store_b))
        barrier = threading.Barrier(2)
        results: list[dict | None] = []
        errors: list[BaseException] = []

        def claim(queue: TaskQueue) -> None:
            try:
                barrier.wait(timeout=5)
                results.append(queue.claim_next())
            except BaseException as exc:  # pragma: no cover - assertion reports the concrete error
                errors.append(exc)

        first = threading.Thread(target=claim, args=(queue_a,))
        second = threading.Thread(target=claim, args=(queue_b,))
        first.start()
        second.start()
        first.join(timeout=8)
        second.join(timeout=8)
        try:
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual([], errors)
            winners = [task for task in results if task is not None]
            self.assertEqual(1, len(winners))
            self.assertEqual("TASK_SINGLE", winners[0]["id"])
            self.assertIsNone(self.queue.claim_next())
        finally:
            store_a.close()
            store_b.close()

    def test_t06_07_cancel_queued_removes_eligibility(self) -> None:
        self.create_task("TASK_CANCEL_QUEUED")
        self.queue.enqueue("TASK_CANCEL_QUEUED")
        cancelled = self.queue.cancel("TASK_CANCEL_QUEUED")
        self.assertEqual("CANCELLED", cancelled["status"])
        self.assertIsNone(self.queue.peek())
        self.assertIsNone(self.queue.claim_next())

    def test_t06_08_invalid_cancel_is_rejected(self) -> None:
        self.create_task("TASK_INVALID_CANCEL", status=TaskState.SUCCEEDED)
        with self.assertRaises(TaskNotCancellable):
            self.queue.cancel("TASK_INVALID_CANCEL")
        self.assertEqual("SUCCEEDED", self.task_store.get("TASK_INVALID_CANCEL")["status"])

    def test_t06_09_retry_eligible_does_not_increment_attempt(self) -> None:
        self.create_task("TASK_RETRY", status=TaskState.FAILED, attempt=1, max_attempts=3)
        queued = self.queue.retry("TASK_RETRY")
        self.assertEqual("QUEUED", queued["status"])
        self.assertEqual(1, queued["attempt"])

    def test_t06_10_retry_limit_is_enforced(self) -> None:
        self.create_task("TASK_RETRY_LIMIT", status=TaskState.INTERRUPTED, attempt=3, max_attempts=3)
        with self.assertRaises(RetryNotEligible):
            self.queue.retry("TASK_RETRY_LIMIT")
        self.assertEqual("INTERRUPTED", self.task_store.get("TASK_RETRY_LIMIT")["status"])

    def test_t06_11_failed_queue_write_rolls_back(self) -> None:
        self.create_task("TASK_ROLLBACK")
        self.queue.enqueue("TASK_ROLLBACK")
        with self.state_store.transaction() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER fail_queue_cancel BEFORE UPDATE OF status ON tasks "
                "WHEN NEW.id = 'TASK_ROLLBACK' BEGIN SELECT RAISE(ABORT, 'queue failure'); END"
            )
        try:
            with self.assertRaises(IntegrityError):
                self.queue.cancel("TASK_ROLLBACK")
        finally:
            with self.state_store.transaction() as connection:
                connection.exec_driver_sql("DROP TRIGGER fail_queue_cancel")
        self.assertEqual("QUEUED", self.task_store.get("TASK_ROLLBACK")["status"])

    def test_t06_12_reopen_preserves_queue_order(self) -> None:
        created_at = datetime(2026, 8, 30, 3, 0, tzinfo=UTC)
        for task_id, priority in (("TASK_REOPEN_LOW", 1), ("TASK_REOPEN_HIGH", 2)):
            self.create_task(task_id, priority=priority, created_at=created_at)
            self.queue.enqueue(task_id)
        self.state_store.close()
        self.state_store = StateStore(self.database_path)
        self.task_store = TaskStore(self.state_store)
        self.queue = TaskQueue(self.task_store)
        self.assertEqual("TASK_REOPEN_HIGH", self.queue.peek()["id"])
        self.assertEqual(2, self.queue.count_queued())

    def test_t06_14_runtime_contract_is_unchanged(self) -> None:
        self.assertEqual(
            {"journal_mode": "wal", "foreign_keys": 1, "busy_timeout": 5000},
            self.state_store.pragmas(),
        )
        self.assertEqual(11, len(self.state_store.table_names()))


if __name__ == "__main__":
    import unittest

    unittest.main()
