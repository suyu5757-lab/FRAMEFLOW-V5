from __future__ import annotations

import json
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase

from sqlalchemy.exc import IntegrityError

from core.runtime.event_log import EventLog
from core.runtime.queue import TaskQueue
from core.runtime.state_store import StateStore, TaskState, TaskStore
from core.runtime.worker import Worker, WorkerOutcome


class StepClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
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


class TaskEventLogIntegrationTests(TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="frameflow-task-event-t10-")
        self.database_path = Path(self.temp_dir.name) / "task-events.db"
        self.state_store = StateStore(self.database_path, initialize=True)
        self.event_log = EventLog(self.state_store, clock=StepClock())
        self.task_store = TaskStore(self.state_store, event_log=self.event_log)
        self.queue = TaskQueue(self.task_store)
        self.state_store.create_project("PRJ_T10_CLOSURE", "T10 Closure", "16:9", 24, 12)

    def tearDown(self) -> None:
        self.state_store.close()
        self.temp_dir.cleanup()

    def create_task(self, task_id: str, **kwargs):
        return self.task_store.create(
            task_id=task_id,
            task_type=kwargs.pop("task_type", "TEST_T10"),
            project_id="PRJ_T10_CLOSURE",
            **kwargs,
        )

    def events(self, task_id: str) -> list[dict]:
        return self.event_log.by_trace(task_id)

    @staticmethod
    def payload(event: dict) -> dict:
        return json.loads(event["payload"])

    def state_payloads(self, task_id: str) -> list[dict]:
        return [
            self.payload(event)
            for event in self.events(task_id)
            if event["event_type"] == "TASK_STATE_CHANGED"
        ]

    def create_state_event_failure_trigger(
        self,
        task_id: str,
        trigger_name: str,
        *,
        allow_claim: bool = False,
    ) -> None:
        allow_claim_sql = " AND NEW.payload NOT LIKE '%\"to_status\":\"RUNNING\"%'" if allow_claim else ""
        with self.state_store.transaction() as connection:
            connection.exec_driver_sql(
                f"""CREATE TRIGGER {trigger_name}
                BEFORE INSERT ON events
                WHEN NEW.entity_type = 'TASK'
                  AND NEW.entity_id = '{task_id}'
                  AND NEW.event_type = 'TASK_STATE_CHANGED'
                  {allow_claim_sql}
                BEGIN SELECT RAISE(ABORT, 'T10 state event failure'); END"""
            )

    def drop_trigger(self, trigger_name: str) -> None:
        with self.state_store.transaction() as connection:
            connection.exec_driver_sql(f"DROP TRIGGER {trigger_name}")

    def test_t10_c01_task_create_emits_one_transactional_event(self) -> None:
        task = self.create_task("TASK_T10_CREATE", task_type="TEST_CREATE")
        events = self.events(task["id"])

        self.assertEqual(["TASK_CREATED"], [event["event_type"] for event in events])
        event = events[0]
        self.assertEqual(task["id"], event["entity_id"])
        self.assertEqual(task["id"], event["trace_id"])
        self.assertEqual("TASK", event["entity_type"])
        self.assertEqual(
            {
                "task_id": "TASK_T10_CREATE",
                "task_type": "TEST_CREATE",
                "initial_status": "CREATED",
                "project_id": "PRJ_T10_CLOSURE",
                "shot_id": None,
            },
            self.payload(event),
        )

    def test_t10_c02_create_rolls_back_when_created_event_fails(self) -> None:
        trigger_name = "fail_t10_created_event"
        with self.state_store.transaction() as connection:
            connection.exec_driver_sql(
                f"""CREATE TRIGGER {trigger_name}
                BEFORE INSERT ON events
                WHEN NEW.entity_id = 'TASK_T10_CREATE_ROLLBACK'
                  AND NEW.event_type = 'TASK_CREATED'
                BEGIN SELECT RAISE(ABORT, 'T10 created event failure'); END"""
            )
        try:
            with self.assertRaises(IntegrityError):
                self.create_task("TASK_T10_CREATE_ROLLBACK")
            self.assertIsNone(self.task_store.get("TASK_T10_CREATE_ROLLBACK"))
            self.assertEqual([], self.events("TASK_T10_CREATE_ROLLBACK"))
        finally:
            self.drop_trigger(trigger_name)

    def test_t10_c03_enqueue_and_noop_enqueue_have_one_state_event(self) -> None:
        self.create_task("TASK_T10_ENQUEUE")
        self.queue.enqueue("TASK_T10_ENQUEUE")
        self.queue.enqueue("TASK_T10_ENQUEUE")

        payloads = self.state_payloads("TASK_T10_ENQUEUE")
        self.assertEqual(1, len(payloads))
        self.assertEqual(
            {"task_id": "TASK_T10_ENQUEUE", "from_status": "CREATED", "to_status": "QUEUED"},
            payloads[0],
        )

    def test_t10_c04_claim_cancel_and_retry_are_state_events(self) -> None:
        self.create_task("TASK_T10_CLAIM")
        self.queue.enqueue("TASK_T10_CLAIM")
        self.assertEqual("RUNNING", self.queue.claim_next()["status"])

        self.create_task("TASK_T10_CANCEL")
        self.queue.cancel("TASK_T10_CANCEL")

        self.create_task("TASK_T10_RETRY", status=TaskState.FAILED, attempt=1)
        self.queue.retry("TASK_T10_RETRY")

        self.assertEqual(
            [("CREATED", "QUEUED"), ("QUEUED", "RUNNING")],
            [(item["from_status"], item["to_status"]) for item in self.state_payloads("TASK_T10_CLAIM")],
        )
        self.assertEqual(
            [("CREATED", "CANCELLED")],
            [(item["from_status"], item["to_status"]) for item in self.state_payloads("TASK_T10_CANCEL")],
        )
        retry = self.state_payloads("TASK_T10_RETRY")
        self.assertEqual([("FAILED", "QUEUED")], [(item["from_status"], item["to_status"]) for item in retry])
        self.assertEqual(1, self.task_store.get("TASK_T10_RETRY")["attempt"])

    def test_t10_c05_worker_success_and_heartbeat_emit_only_state_changes(self) -> None:
        self.create_task("TASK_T10_SUCCESS", task_type="TEST_SUCCESS")
        self.queue.enqueue("TASK_T10_SUCCESS")
        def success_handler(task, context):
            context.heartbeat()
            return {"ok": True}

        worker = Worker(
            self.task_store,
            queue=self.queue,
            handlers={"TEST_SUCCESS": success_handler},
            worker_id="worker-t10-success",
            heartbeat_interval=0.01,
            clock=StepClock(),
        )

        result = worker.run_once()
        self.assertEqual(WorkerOutcome.SUCCEEDED, result.outcome)
        self.assertEqual(
            ["TASK_CREATED", "TASK_STATE_CHANGED", "TASK_STATE_CHANGED", "TASK_STATE_CHANGED"],
            [event["event_type"] for event in self.events("TASK_T10_SUCCESS")],
        )
        self.assertEqual(
            [("CREATED", "QUEUED"), ("QUEUED", "RUNNING"), ("RUNNING", "SUCCEEDED")],
            [
                (item["from_status"], item["to_status"])
                for item in self.state_payloads("TASK_T10_SUCCESS")
            ],
        )

    def test_t10_c06_worker_failure_unknown_and_timeout_record_reason_codes(self) -> None:
        self.create_task("TASK_T10_FAILURE", task_type="TEST_FAILURE", priority=3)
        self.create_task("TASK_T10_UNKNOWN", task_type="TEST_UNKNOWN", priority=2)
        self.create_task("TASK_T10_TIMEOUT", task_type="TEST_TIMEOUT", timeout=1, priority=1)
        for task_id in ("TASK_T10_FAILURE", "TASK_T10_UNKNOWN", "TASK_T10_TIMEOUT"):
            self.queue.enqueue(task_id)

        worker = Worker(
            self.task_store,
            queue=self.queue,
            handlers={
                "TEST_FAILURE": lambda task, context: (_ for _ in ()).throw(RuntimeError("boom")),
                "TEST_TIMEOUT": lambda task, context: context.check_cancelled(),
            },
            worker_id="worker-t10-failure",
            clock=StepClock(),
            monotonic=StepMonotonic([0.0, 2.0]),
        )
        self.assertEqual(WorkerOutcome.FAILED, worker.run_once().outcome)
        self.assertEqual(WorkerOutcome.FAILED, worker.run_once().outcome)
        self.assertEqual(WorkerOutcome.FAILED, worker.run_once().outcome)

        self.assertEqual("handler_failed", self.state_payloads("TASK_T10_FAILURE")[-1]["reason_code"])
        self.assertEqual("handler_not_registered", self.state_payloads("TASK_T10_UNKNOWN")[-1]["reason_code"])
        self.assertEqual("timeout", self.state_payloads("TASK_T10_TIMEOUT")[-1]["reason_code"])

    def test_t10_c07_failure_retry_success_preserves_order_and_attempts(self) -> None:
        self.create_task("TASK_T10_RETRY_LIFECYCLE", task_type="TEST_RETRY", max_attempts=3)
        self.queue.enqueue("TASK_T10_RETRY_LIFECYCLE")
        calls: list[int] = []

        def handler(task, context):
            calls.append(context.attempt)
            if len(calls) == 1:
                raise RuntimeError("first attempt")
            return {"attempt": context.attempt}

        worker = Worker(
            self.task_store,
            queue=self.queue,
            handlers={"TEST_RETRY": handler},
            worker_id="worker-t10-retry",
            clock=StepClock(),
        )
        self.assertEqual(WorkerOutcome.FAILED, worker.run_once().outcome)
        self.queue.retry("TASK_T10_RETRY_LIFECYCLE")
        self.assertEqual(WorkerOutcome.SUCCEEDED, worker.run_once().outcome)

        events = self.events("TASK_T10_RETRY_LIFECYCLE")
        self.assertEqual(
            ["TASK_CREATED"] + ["TASK_STATE_CHANGED"] * 6,
            [event["event_type"] for event in events],
        )
        self.assertEqual(
            [
                ("CREATED", "QUEUED"),
                ("QUEUED", "RUNNING"),
                ("RUNNING", "FAILED"),
                ("FAILED", "QUEUED"),
                ("QUEUED", "RUNNING"),
                ("RUNNING", "SUCCEEDED"),
            ],
            [
                (item["from_status"], item["to_status"])
                for item in self.state_payloads("TASK_T10_RETRY_LIFECYCLE")
            ],
        )
        self.assertEqual([1, 2], calls)
        self.assertEqual(2, self.task_store.get("TASK_T10_RETRY_LIFECYCLE")["attempt"])

    def test_t10_c08_queue_claim_event_failure_keeps_task_queued(self) -> None:
        task_id = "TASK_T10_CLAIM_ATOMIC"
        trigger_name = "fail_t10_claim_event"
        self.create_task(task_id)
        self.queue.enqueue(task_id)
        self.create_state_event_failure_trigger(task_id, trigger_name)
        try:
            with self.assertRaises(IntegrityError):
                self.queue.claim_next()
            self.assertEqual("QUEUED", self.task_store.get(task_id)["status"])
            self.assertEqual(
                [("CREATED", "QUEUED")],
                [(item["from_status"], item["to_status"]) for item in self.state_payloads(task_id)],
            )
        finally:
            self.drop_trigger(trigger_name)

    def test_t10_c09_worker_success_event_failure_keeps_running_without_result(self) -> None:
        task_id = "TASK_T10_SUCCESS_ATOMIC"
        trigger_name = "fail_t10_success_event"
        self.create_task(task_id, task_type="TEST_SUCCESS")
        self.queue.enqueue(task_id)
        self.create_state_event_failure_trigger(task_id, trigger_name, allow_claim=True)
        try:
            result = Worker(
                self.task_store,
                queue=self.queue,
                handlers={"TEST_SUCCESS": lambda task, context: {"ok": True}},
                worker_id="worker-t10-success-atomic",
                clock=StepClock(),
            ).run_once()
            task = self.task_store.get(task_id)
            self.assertEqual(WorkerOutcome.FINALIZATION_FAILED, result.outcome)
            self.assertEqual("RUNNING", task["status"])
            self.assertIsNone(task["result_json"])
            self.assertIsNone(task["finished_at"])
            self.assertEqual([("CREATED", "QUEUED"), ("QUEUED", "RUNNING")], [
                (item["from_status"], item["to_status"])
                for item in self.state_payloads(task_id)
            ])
        finally:
            self.drop_trigger(trigger_name)

    def test_t10_c10_worker_failure_event_failure_keeps_running_without_error(self) -> None:
        task_id = "TASK_T10_FAILURE_ATOMIC"
        trigger_name = "fail_t10_failure_event"
        self.create_task(task_id, task_type="TEST_FAILURE")
        self.queue.enqueue(task_id)
        self.create_state_event_failure_trigger(task_id, trigger_name, allow_claim=True)
        try:
            result = Worker(
                self.task_store,
                queue=self.queue,
                handlers={"TEST_FAILURE": lambda task, context: (_ for _ in ()).throw(RuntimeError("boom"))},
                worker_id="worker-t10-failure-atomic",
                clock=StepClock(),
            ).run_once()
            task = self.task_store.get(task_id)
            self.assertEqual(WorkerOutcome.FINALIZATION_FAILED, result.outcome)
            self.assertEqual("RUNNING", task["status"])
            self.assertIsNone(task["error_json"])
            self.assertIsNone(task["finished_at"])
            self.assertEqual([("CREATED", "QUEUED"), ("QUEUED", "RUNNING")], [
                (item["from_status"], item["to_status"])
                for item in self.state_payloads(task_id)
            ])
        finally:
            self.drop_trigger(trigger_name)

    def test_t10_c11_two_workers_one_task_emit_one_claim_and_one_completion(self) -> None:
        task_id = "TASK_T10_ONE_WINNER"
        self.create_task(task_id, task_type="TEST_SHARED")
        self.queue.enqueue(task_id)
        store_a = StateStore(self.database_path)
        store_b = StateStore(self.database_path)
        handler_started = threading.Event()
        release_handler = threading.Event()
        calls: list[str] = []
        call_lock = threading.Lock()
        results: list = []
        errors: list[BaseException] = []

        def handler(task, context):
            with call_lock:
                calls.append(str(task["id"]))
            handler_started.set()
            release_handler.wait(timeout=5)
            return {"only_once": True}

        workers = [
            Worker(TaskStore(store_a), handlers={"TEST_SHARED": handler}, worker_id="worker-t10-a"),
            Worker(TaskStore(store_b), handlers={"TEST_SHARED": handler}, worker_id="worker-t10-b"),
        ]

        def run(worker: Worker) -> None:
            try:
                results.append(worker.run_once())
            except BaseException as exc:  # pragma: no cover - reports thread failure
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
            self.assertEqual(1, len(calls))
            self.assertEqual(1, len([item for item in self.events(task_id) if item["event_type"] == "TASK_CREATED"]))
            state_events = self.state_payloads(task_id)
            self.assertEqual(1, len([item for item in state_events if item["to_status"] == "RUNNING"]))
            self.assertEqual(1, len([item for item in state_events if item["to_status"] == "SUCCEEDED"]))
        finally:
            store_a.close()
            store_b.close()

    def test_t10_c12_event_sequence_survives_reopen(self) -> None:
        task_id = "TASK_T10_REOPEN"
        self.create_task(task_id, task_type="TEST_REOPEN")
        self.queue.enqueue(task_id)
        result = Worker(
            self.task_store,
            queue=self.queue,
            handlers={"TEST_REOPEN": lambda task, context: {"persisted": True}},
            worker_id="worker-t10-reopen",
            clock=StepClock(),
        ).run_once()
        self.assertEqual(WorkerOutcome.SUCCEEDED, result.outcome)
        before = [(event["event_type"], self.payload(event)) for event in self.events(task_id)]

        self.state_store.close()
        self.state_store = StateStore(self.database_path)
        self.event_log = EventLog(self.state_store)
        self.task_store = TaskStore(self.state_store, event_log=self.event_log)
        after = [(event["event_type"], self.payload(event)) for event in self.events(task_id)]
        self.assertEqual(before, after)
        self.assertEqual("SUCCEEDED", self.task_store.get(task_id)["status"])


if __name__ == "__main__":
    import unittest

    unittest.main()
