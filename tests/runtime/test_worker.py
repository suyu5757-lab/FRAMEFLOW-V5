from __future__ import annotations

import json
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase

from core.runtime.queue import TaskQueue
from core.runtime.state_store import StateStore, TaskState, TaskStore
from core.runtime.worker import HandlerRegistry, Worker, WorkerOutcome


class StepClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 30, 5, 0, tzinfo=UTC)
        self.lock = threading.Lock()

    def __call__(self) -> datetime:
        with self.lock:
            value = self.current
            self.current += timedelta(seconds=1)
            return value


class StepMonotonic:
    def __init__(self, values: list[float]) -> None:
        self.values = iter(values)
        self.last = 0.0

    def __call__(self) -> float:
        try:
            self.last = next(self.values)
        except StopIteration:
            pass
        return self.last


class InProcessWorkerTests(TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="frameflow-worker-t07-")
        self.database_path = Path(self.temp_dir.name) / "worker.db"
        self.state_store = StateStore(self.database_path, initialize=True)
        self.task_store = TaskStore(self.state_store)
        self.queue = TaskQueue(self.task_store)
        self.state_store.create_project("PRJ_T07", "T07 Project", "16:9", 24, 12)

    def tearDown(self) -> None:
        self.state_store.close()
        self.temp_dir.cleanup()

    def create_task(self, task_id: str, **kwargs):
        return self.task_store.create(
            task_id=task_id,
            task_type=kwargs.pop("task_type", "TEST_SUCCESS"),
            project_id="PRJ_T07",
            **kwargs,
        )

    def enqueue(self, task_id: str) -> None:
        self.queue.enqueue(task_id)

    def make_worker(self, handlers, **kwargs) -> Worker:
        return Worker(
            self.task_store,
            queue=self.queue,
            handlers=handlers,
            worker_id=kwargs.pop("worker_id", "worker-t07-test"),
            clock=kwargs.pop("clock", StepClock()),
            **kwargs,
        )

    def test_t07_01_no_work_returns_idle(self) -> None:
        worker = self.make_worker({})
        result = worker.run_once()
        self.assertEqual(WorkerOutcome.IDLE, result.outcome)
        self.assertIsNone(result.task_id)

    def test_t07_02_successful_task_persists_lifecycle(self) -> None:
        self.create_task("TASK_T07_SUCCESS", task_type="TEST_SUCCESS")
        self.enqueue("TASK_T07_SUCCESS")
        result = self.make_worker(
            {"TEST_SUCCESS": lambda task, context: {"ok": True, "task_id": context.task_id}}
        ).run_once()

        task = self.task_store.get("TASK_T07_SUCCESS")
        self.assertEqual(WorkerOutcome.SUCCEEDED, result.outcome)
        self.assertEqual(TaskState.SUCCEEDED, result.task_status)
        self.assertEqual("SUCCEEDED", task["status"])
        self.assertEqual("worker-t07-test", task["worker"])
        self.assertEqual(1, task["attempt"])
        self.assertIsNotNone(task["started_at"])
        self.assertIsNotNone(task["heartbeat_at"])
        self.assertIsNotNone(task["finished_at"])
        self.assertEqual({"ok": True, "task_id": "TASK_T07_SUCCESS"}, json.loads(task["result_json"]))
        self.assertIsNone(task["error_json"])

    def test_t07_03_attempt_increments_exactly_once_per_execution(self) -> None:
        self.create_task("TASK_T07_ATTEMPT", task_type="TEST_RESULT")
        self.enqueue("TASK_T07_ATTEMPT")
        seen_attempts: list[int] = []

        def handler(task, context):
            seen_attempts.append(context.attempt)
            return {"attempt": context.attempt}

        result = self.make_worker({"TEST_RESULT": handler}).run_once()
        task = self.task_store.get("TASK_T07_ATTEMPT")
        self.assertEqual(WorkerOutcome.SUCCEEDED, result.outcome)
        self.assertEqual([1], seen_attempts)
        self.assertEqual(1, task["attempt"])

    def test_t07_04_retry_requeue_does_not_increment_but_second_execution_does(self) -> None:
        self.create_task("TASK_T07_RETRY", task_type="TEST_RETRY", max_attempts=3)
        self.enqueue("TASK_T07_RETRY")
        seen_attempts: list[int] = []

        def handler(task, context):
            seen_attempts.append(context.attempt)
            if len(seen_attempts) == 1:
                raise RuntimeError("first execution fails")
            return {"ok": True, "attempt": context.attempt}

        worker = self.make_worker({"TEST_RETRY": handler})
        first = worker.run_once()
        failed = self.task_store.get("TASK_T07_RETRY")
        self.assertEqual(WorkerOutcome.FAILED, first.outcome)
        self.assertEqual(1, failed["attempt"])

        queued = self.queue.retry("TASK_T07_RETRY")
        self.assertEqual(1, queued["attempt"])
        self.assertEqual("QUEUED", queued["status"])
        second = worker.run_once()
        final = self.task_store.get("TASK_T07_RETRY")
        self.assertEqual(WorkerOutcome.SUCCEEDED, second.outcome)
        self.assertEqual([1, 2], seen_attempts)
        self.assertEqual(2, final["attempt"])

    def test_t07_05_handler_failure_is_structured_and_worker_survives(self) -> None:
        self.create_task("TASK_T07_FAILURE", task_type="TEST_FAILURE")
        self.enqueue("TASK_T07_FAILURE")

        def handler(task, context):
            raise RuntimeError("upstream token=do-not-store")

        result = self.make_worker({"TEST_FAILURE": handler}).run_once()
        task = self.task_store.get("TASK_T07_FAILURE")
        error = json.loads(task["error_json"])
        self.assertEqual(WorkerOutcome.FAILED, result.outcome)
        self.assertEqual("FAILED", task["status"])
        self.assertEqual("handler_failed", error["code"])
        self.assertEqual("RuntimeError", error["type"])
        self.assertTrue(error["message"].endswith("[REDACTED]"))
        self.assertNotIn("do-not-store", error["message"])
        self.assertEqual("worker-t07-test", error["worker_id"])
        self.assertEqual(1, error["attempt"])
        self.assertFalse(error["retryable"])
        self.assertIsNotNone(task["finished_at"])

    def test_t07_06_unknown_handler_fails_without_dynamic_execution(self) -> None:
        self.create_task(
            "TASK_T07_UNKNOWN",
            task_type="UNKNOWN_HANDLER",
            payload={"callable": "os.system", "command": "must-not-run"},
        )
        self.enqueue("TASK_T07_UNKNOWN")
        result = self.make_worker({}).run_once()
        task = self.task_store.get("TASK_T07_UNKNOWN")
        error = json.loads(task["error_json"])
        self.assertEqual(WorkerOutcome.FAILED, result.outcome)
        self.assertEqual("FAILED", task["status"])
        self.assertEqual("handler_not_registered", error["code"])
        self.assertEqual("UNKNOWN_HANDLER", error["task_type"])
        self.assertFalse(error["retryable"])

    def test_t07_07_complex_json_result_round_trips(self) -> None:
        expected = {
            "nested": [{"number": 3.5, "enabled": True, "missing": None}],
            "items": [1, 2, 3],
        }
        self.create_task("TASK_T07_RESULT", task_type="TEST_RESULT")
        self.enqueue("TASK_T07_RESULT")
        result = self.make_worker({"TEST_RESULT": lambda task, context: expected}).run_once()
        task = self.task_store.get("TASK_T07_RESULT")
        self.assertEqual(WorkerOutcome.SUCCEEDED, result.outcome)
        self.assertEqual(expected, json.loads(task["result_json"]))

    def test_t07_08_reopen_preserves_success_and_failure_lifecycle(self) -> None:
        self.create_task("TASK_T07_REOPEN_SUCCESS", task_type="TEST_SUCCESS", priority=2)
        self.create_task("TASK_T07_REOPEN_FAILURE", task_type="TEST_FAILURE", priority=1)
        self.enqueue("TASK_T07_REOPEN_SUCCESS")
        self.enqueue("TASK_T07_REOPEN_FAILURE")
        worker = self.make_worker(
            {
                "TEST_SUCCESS": lambda task, context: {"persisted": True},
                "TEST_FAILURE": lambda task, context: (_ for _ in ()).throw(RuntimeError("persisted failure")),
            }
        )
        self.assertEqual(WorkerOutcome.SUCCEEDED, worker.run_once().outcome)
        self.assertEqual(WorkerOutcome.FAILED, worker.run_once().outcome)

        self.state_store.close()
        self.state_store = StateStore(self.database_path)
        self.task_store = TaskStore(self.state_store)
        self.queue = TaskQueue(self.task_store)
        success = self.task_store.get("TASK_T07_REOPEN_SUCCESS")
        failure = self.task_store.get("TASK_T07_REOPEN_FAILURE")
        self.assertEqual("SUCCEEDED", success["status"])
        self.assertEqual({"persisted": True}, json.loads(success["result_json"]))
        self.assertEqual("FAILED", failure["status"])
        self.assertEqual("handler_failed", json.loads(failure["error_json"])["code"])

    def test_t07_09_cooperative_timeout_fails_without_unsafe_thread_kill(self) -> None:
        self.create_task("TASK_T07_TIMEOUT", task_type="TEST_TIMEOUT", timeout=1)
        self.enqueue("TASK_T07_TIMEOUT")

        def handler(task, context):
            context.check_cancelled()
            return {"must_not": "complete"}

        worker = self.make_worker(
            {"TEST_TIMEOUT": handler},
            monotonic=StepMonotonic([0.0, 2.0]),
        )
        result = worker.run_once()
        task = self.task_store.get("TASK_T07_TIMEOUT")
        error = json.loads(task["error_json"])
        self.assertEqual(WorkerOutcome.FAILED, result.outcome)
        self.assertEqual("FAILED", task["status"])
        self.assertEqual("timeout", error["code"])
        self.assertIsNone(task["result_json"])
        self.assertIsNotNone(task["finished_at"])

    def test_t07_10_heartbeat_progresses_during_controlled_long_handler(self) -> None:
        self.create_task("TASK_T07_HEARTBEAT", task_type="TEST_HEARTBEAT")
        self.enqueue("TASK_T07_HEARTBEAT")
        handler_started = threading.Event()
        heartbeat_seen = threading.Event()
        release_handler = threading.Event()
        heartbeat_times: list[datetime] = []
        heartbeat_lock = threading.Lock()

        def observe(task):
            with heartbeat_lock:
                heartbeat_times.append(task["heartbeat_at"])
            heartbeat_seen.set()

        def handler(task, context):
            handler_started.set()
            if not heartbeat_seen.wait(timeout=5):
                raise RuntimeError("heartbeat did not progress")
            if not release_handler.wait(timeout=5):
                raise RuntimeError("test did not release handler")
            return {"heartbeat": True}

        worker = self.make_worker(
            {"TEST_HEARTBEAT": handler},
            heartbeat_interval=0.01,
            heartbeat_observer=observe,
        )
        outcome: list = []
        errors: list[BaseException] = []

        def run_worker() -> None:
            try:
                outcome.append(worker.run_once())
            except BaseException as exc:  # pragma: no cover - reports thread failures
                errors.append(exc)

        thread = threading.Thread(target=run_worker)
        thread.start()
        self.assertTrue(handler_started.wait(timeout=5))
        self.assertTrue(heartbeat_seen.wait(timeout=5))
        release_handler.set()
        thread.join(timeout=8)
        task = self.task_store.get("TASK_T07_HEARTBEAT")
        self.assertFalse(thread.is_alive())
        self.assertEqual([], errors)
        self.assertEqual(1, len(outcome))
        self.assertEqual(WorkerOutcome.SUCCEEDED, outcome[0].outcome)
        self.assertGreaterEqual(len(heartbeat_times), 1)
        self.assertGreater(task["heartbeat_at"], task["started_at"])

    def test_t07_11_finalization_failure_never_fakes_success(self) -> None:
        self.create_task("TASK_T07_TX", task_type="TEST_SUCCESS")
        self.enqueue("TASK_T07_TX")
        with self.state_store.transaction() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER fail_worker_finalization "
                "BEFORE UPDATE OF status ON tasks "
                "WHEN NEW.id = 'TASK_T07_TX' AND NEW.status IN ('SUCCEEDED', 'FAILED') "
                "BEGIN SELECT RAISE(ABORT, 'worker finalization failure'); END"
            )
        try:
            result = self.make_worker({"TEST_SUCCESS": lambda task, context: {"ok": True}}).run_once()
            task = self.task_store.get("TASK_T07_TX")
            self.assertEqual(WorkerOutcome.FINALIZATION_FAILED, result.outcome)
            self.assertEqual("RUNNING", task["status"])
            self.assertEqual(1, task["attempt"])
            self.assertIsNone(task["result_json"])
            self.assertIsNone(task["error_json"])
            self.assertNotEqual("SUCCEEDED", task["status"])
        finally:
            with self.state_store.transaction() as connection:
                connection.exec_driver_sql("DROP TRIGGER fail_worker_finalization")

    def test_t07_12_worker_respects_t06_queue_ordering(self) -> None:
        created_at = datetime(2026, 8, 30, 5, 0, tzinfo=UTC)
        self.create_task("TASK_T07_LOW", task_type="TEST_ORDER", priority=1, created_at=created_at)
        self.create_task("TASK_T07_HIGH", task_type="TEST_ORDER", priority=9, created_at=created_at)
        self.enqueue("TASK_T07_LOW")
        self.enqueue("TASK_T07_HIGH")
        invocation_order: list[str] = []

        def handler(task, context):
            invocation_order.append(task["id"])
            return {"id": task["id"]}

        worker = self.make_worker({"TEST_ORDER": handler})
        self.assertEqual(WorkerOutcome.SUCCEEDED, worker.run_once().outcome)
        self.assertEqual(WorkerOutcome.SUCCEEDED, worker.run_once().outcome)
        self.assertEqual(["TASK_T07_HIGH", "TASK_T07_LOW"], invocation_order)

    def test_t07_13_two_workers_two_tasks_have_no_duplicate_execution(self) -> None:
        self.create_task("TASK_T07_TWO_A", task_type="TEST_SHARED")
        self.create_task("TASK_T07_TWO_B", task_type="TEST_SHARED")
        self.enqueue("TASK_T07_TWO_A")
        self.enqueue("TASK_T07_TWO_B")
        store_a = StateStore(self.database_path)
        store_b = StateStore(self.database_path)
        calls: list[str] = []
        call_lock = threading.Lock()
        barrier = threading.Barrier(2)
        results: list = []
        errors: list[BaseException] = []

        def handler(task, context):
            with call_lock:
                calls.append(task["id"])
            return {"id": task["id"]}

        workers = (
            Worker(TaskStore(store_a), handlers={"TEST_SHARED": handler}, worker_id="worker-t07-a"),
            Worker(TaskStore(store_b), handlers={"TEST_SHARED": handler}, worker_id="worker-t07-b"),
        )

        def run(worker):
            try:
                barrier.wait(timeout=5)
                results.append(worker.run_once())
            except BaseException as exc:  # pragma: no cover - assertion reports the concrete error
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(worker,)) for worker in workers]
        try:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=8)
            self.assertEqual([], errors)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(2, len(results))
            self.assertEqual({WorkerOutcome.SUCCEEDED}, {result.outcome for result in results})
            self.assertEqual({"TASK_T07_TWO_A", "TASK_T07_TWO_B"}, set(calls))
            self.assertEqual(2, len(calls))
        finally:
            store_a.close()
            store_b.close()

    def test_t07_14_two_workers_one_task_invoke_handler_once(self) -> None:
        self.create_task("TASK_T07_ONE", task_type="TEST_SHARED")
        self.enqueue("TASK_T07_ONE")
        store_a = StateStore(self.database_path)
        store_b = StateStore(self.database_path)
        call_count = 0
        call_lock = threading.Lock()
        handler_started = threading.Event()
        release_handler = threading.Event()
        barrier = threading.Barrier(2)
        results: list = []
        errors: list[BaseException] = []

        def handler(task, context):
            nonlocal call_count
            with call_lock:
                call_count += 1
            handler_started.set()
            if not release_handler.wait(timeout=5):
                raise RuntimeError("test did not release handler")
            return {"only_once": True}

        workers = (
            Worker(TaskStore(store_a), handlers={"TEST_SHARED": handler}, worker_id="worker-t07-a"),
            Worker(TaskStore(store_b), handlers={"TEST_SHARED": handler}, worker_id="worker-t07-b"),
        )

        def run(worker):
            try:
                barrier.wait(timeout=5)
                results.append(worker.run_once())
            except BaseException as exc:  # pragma: no cover - assertion reports the concrete error
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(worker,)) for worker in workers]
        try:
            for thread in threads:
                thread.start()
            self.assertTrue(handler_started.wait(timeout=5))
            release_handler.set()
            for thread in threads:
                thread.join(timeout=8)
            self.assertEqual([], errors)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(1, call_count)
            self.assertEqual(1, len([result for result in results if result.outcome == WorkerOutcome.SUCCEEDED]))
            self.assertEqual(1, len([result for result in results if result.outcome == WorkerOutcome.IDLE]))
        finally:
            store_a.close()
            store_b.close()

    def test_t07_15_cancelled_task_never_invokes_handler(self) -> None:
        self.create_task("TASK_T07_CANCELLED", task_type="TEST_SUCCESS", status=TaskState.CANCELLED)
        calls: list[str] = []

        def handler(task, context):
            calls.append(task["id"])
            return {"must_not": "run"}

        result = self.make_worker({"TEST_SUCCESS": handler}).run_once()
        self.assertEqual(WorkerOutcome.IDLE, result.outcome)
        self.assertEqual([], calls)
        self.assertEqual("CANCELLED", self.task_store.get("TASK_T07_CANCELLED")["status"])


if __name__ == "__main__":
    import unittest

    unittest.main()
