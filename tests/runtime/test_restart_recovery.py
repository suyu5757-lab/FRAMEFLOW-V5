from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase

from core.runtime.event_log import EventLog
from core.runtime.idempotency import ProviderSubmissionStore, SubmissionStatus
from core.runtime.persistence import RuntimeStartupConfig, write_runtime_startup_config
from core.runtime.queue import TaskQueue
from core.runtime.recovery import RecoveryError, RestartRecovery
from core.runtime.resource_locks import ResourceId, ResourceLockManager
from core.runtime.state_store import StateStore, TaskState, TaskStore
from core.runtime.worker import Worker, WorkerOutcome
from tests.conftest import isolated_legacy_v3_path


class StepClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
        self.lock = threading.Lock()

    def __call__(self) -> datetime:
        with self.lock:
            value = self.current
            self.current += timedelta(seconds=1)
            return value


class SnapshotStub:
    def __init__(self) -> None:
        self.calls = 0

    def snapshot(self) -> dict:
        self.calls += 1
        return {}


class RestartRecoveryTests(TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="frameflow-recovery-t12-")
        self.database_path = Path(self.temp_dir.name) / "recovery.db"
        self.state_store = StateStore(self.database_path, initialize=True)
        self.event_log = EventLog(self.state_store, clock=StepClock())
        self.task_store = TaskStore(self.state_store, event_log=self.event_log)
        self.queue = TaskQueue(self.task_store)
        self.state_store.create_project("PRJ_T12", "T12 Recovery", "16:9", 24, 12)

    def tearDown(self) -> None:
        self.state_store.close()
        self.temp_dir.cleanup()

    def create_task(self, task_id: str, **kwargs):
        return self.task_store.create(
            task_id=task_id,
            task_type=kwargs.pop("task_type", "TEST_T12"),
            project_id="PRJ_T12",
            **kwargs,
        )

    def events(self, task_id: str) -> list[dict]:
        return self.event_log.by_trace(task_id)

    @staticmethod
    def payload(event: dict) -> dict:
        return json.loads(event["payload"])

    def state_events(self, task_id: str) -> list[dict]:
        return [event for event in self.events(task_id) if event["event_type"] == "TASK_STATE_CHANGED"]

    def recovery(self, supervisor=None) -> RestartRecovery:
        return RestartRecovery(
            self.task_store,
            supervisor=supervisor or SnapshotStub(),
            clock=StepClock(),
        )

    def test_t12_01_basic_cold_restart_interruption_preserves_attempt(self) -> None:
        task_id = "TASK_T12_BASIC"
        self.create_task(task_id, status=TaskState.RUNNING, worker="old-worker", attempt=1)

        report = self.recovery().recover_startup()
        task = self.task_store.get(task_id)
        error = json.loads(task["error_json"])

        self.assertEqual(1, report["running_scanned"])
        self.assertEqual([task_id], report["interrupted"])
        self.assertEqual("INTERRUPTED", task["status"])
        self.assertEqual(1, task["attempt"])
        self.assertEqual("old-worker", task["worker"])
        self.assertEqual("runtime_restart_interrupted", error["code"])
        self.assertTrue(error["retryable"])
        self.assertEqual("old-worker", error["previous_worker"])
        self.assertIsNotNone(task["finished_at"])

    def test_t12_02_missing_worker_owner_is_interrupted_with_reason(self) -> None:
        task_id = "TASK_T12_NO_OWNER"
        self.create_task(task_id, status=TaskState.RUNNING, worker=None, attempt=2)

        self.recovery().recover_startup()
        task = self.task_store.get(task_id)
        error = json.loads(task["error_json"])
        event = self.state_events(task_id)[0]

        self.assertEqual("INTERRUPTED", task["status"])
        self.assertEqual(2, task["attempt"])
        self.assertIsNone(task["worker"])
        self.assertEqual("missing_worker_owner", error["code"])
        self.assertEqual("missing_worker_owner", self.payload(event)["reason_code"])

    def test_t12_03_interruption_emits_exactly_one_transactional_event(self) -> None:
        task_id = "TASK_T12_EVENT"
        self.create_task(task_id, status=TaskState.RUNNING, worker="old-worker")

        self.recovery().recover_startup()
        state_events = self.state_events(task_id)

        self.assertEqual(1, len(state_events))
        self.assertEqual(
            {
                "task_id": task_id,
                "from_status": "RUNNING",
                "to_status": "INTERRUPTED",
                "reason_code": "runtime_restart_interrupted",
            },
            self.payload(state_events[0]),
        )

    def test_t12_04_event_failure_rolls_back_task_interruption(self) -> None:
        task_id = "TASK_T12_EVENT_FAILURE"
        trigger_name = "fail_t12_interruption_event"
        self.create_task(task_id, status=TaskState.RUNNING, worker="old-worker")
        with self.state_store.transaction() as connection:
            connection.exec_driver_sql(
                f"""CREATE TRIGGER {trigger_name}
                BEFORE INSERT ON events
                WHEN NEW.entity_id = '{task_id}'
                  AND NEW.event_type = 'TASK_STATE_CHANGED'
                BEGIN SELECT RAISE(ABORT, 'T12 interruption event failure'); END"""
            )
        try:
            with self.assertRaises(RecoveryError) as raised:
                self.recovery().recover_startup()
            task = self.task_store.get(task_id)
            self.assertEqual("RUNNING", task["status"])
            self.assertIsNone(task["error_json"])
            self.assertIsNone(task["finished_at"])
            self.assertEqual([], self.state_events(task_id))
            self.assertEqual([task_id], [item["task_id"] for item in raised.exception.report["errors"]])
        finally:
            with self.state_store.transaction() as connection:
                connection.exec_driver_sql(f"DROP TRIGGER {trigger_name}")

    def test_t12_05_second_startup_is_idempotent(self) -> None:
        task_id = "TASK_T12_IDEMPOTENT"
        self.create_task(task_id, status=TaskState.RUNNING, worker="old-worker")
        recovery = self.recovery()

        first = recovery.recover_startup()
        second = recovery.recover_startup()

        self.assertEqual([task_id], first["interrupted"])
        self.assertEqual(0, second["running_scanned"])
        self.assertEqual([], second["interrupted"])
        self.assertEqual(1, len(self.state_events(task_id)))

    def test_t12_06_only_running_state_is_scanned(self) -> None:
        states = (
            TaskState.CREATED,
            TaskState.QUEUED,
            TaskState.WAITING_FOR_RESOURCE,
            TaskState.RUNNING,
            TaskState.SUCCEEDED,
            TaskState.FAILED,
            TaskState.INTERRUPTED,
            TaskState.CANCELLED,
        )
        for state in states:
            self.create_task(f"TASK_T12_STATE_{state.value}", status=state, worker="old-worker", attempt=1)

        report = self.recovery().recover_startup()

        self.assertEqual(1, report["running_scanned"])
        self.assertEqual(["TASK_T12_STATE_RUNNING"], report["interrupted"])
        for state in states:
            task = self.task_store.get(f"TASK_T12_STATE_{state.value}")
            expected = "INTERRUPTED" if state is TaskState.RUNNING else state.value
            self.assertEqual(expected, task["status"])
            if state is not TaskState.RUNNING:
                self.assertEqual(1, task["attempt"])

    def test_t12_07_multiple_running_tasks_each_get_one_event(self) -> None:
        task_ids = [f"TASK_T12_MULTI_{index}" for index in range(3)]
        for task_id in task_ids:
            self.create_task(task_id, status=TaskState.RUNNING, worker="old-worker")

        report = self.recovery().recover_startup()

        self.assertEqual(3, report["running_scanned"])
        self.assertEqual(task_ids, report["interrupted"])
        for task_id in task_ids:
            self.assertEqual(1, len(self.state_events(task_id)))

    def test_t12_08_active_worker_context_preserves_running_task(self) -> None:
        task_id = "TASK_T12_ACTIVE"
        self.create_task(task_id, status=TaskState.RUNNING, worker="active-worker", attempt=2)

        report = self.recovery().reconcile_running_tasks({"active-worker"})
        task = self.task_store.get(task_id)

        self.assertEqual([task_id], report["preserved"])
        self.assertEqual([], report["interrupted"])
        self.assertEqual("RUNNING", task["status"])
        self.assertEqual(2, task["attempt"])
        self.assertEqual([], self.state_events(task_id))

    def test_t12_09_explicit_retry_and_next_execution_increment_once(self) -> None:
        task_id = "TASK_T12_RETRY"
        self.create_task(task_id, status=TaskState.RUNNING, worker="old-worker", task_type="TEST_RETRY", attempt=1)
        self.recovery().recover_startup()
        interrupted = self.task_store.get(task_id)
        self.assertEqual(1, interrupted["attempt"])

        queued = self.queue.retry(task_id)
        worker = Worker(
            self.task_store,
            queue=self.queue,
            handlers={"TEST_RETRY": lambda task, context: {"attempt": context.attempt}},
            worker_id="new-worker",
            clock=StepClock(),
        )
        result = worker.run_once()
        final = self.task_store.get(task_id)

        self.assertEqual("QUEUED", queued["status"])
        self.assertEqual(1, queued["attempt"])
        self.assertEqual(WorkerOutcome.SUCCEEDED, result.outcome)
        self.assertEqual("SUCCEEDED", final["status"])
        self.assertEqual(2, final["attempt"])
        self.assertEqual(
            [
                ("RUNNING", "INTERRUPTED"),
                ("INTERRUPTED", "QUEUED"),
                ("QUEUED", "RUNNING"),
                ("RUNNING", "SUCCEEDED"),
            ],
            [(self.payload(event)["from_status"], self.payload(event)["to_status"]) for event in self.state_events(task_id)],
        )

    def test_t12_10_full_recovery_lifecycle_order_is_persistent(self) -> None:
        task_id = "TASK_T12_FULL"
        self.create_task(task_id, task_type="TEST_FULL")
        self.queue.enqueue(task_id)
        claimed = self.queue.claim_next()
        self.assertEqual("RUNNING", claimed["status"])
        self.task_store.begin_execution(
            task_id,
            worker="old-worker",
            started_at=datetime(2026, 8, 30, 10, 30, tzinfo=UTC),
        )
        self.recovery().recover_startup()
        self.queue.retry(task_id)
        worker = Worker(
            self.task_store,
            queue=self.queue,
            handlers={"TEST_FULL": lambda task, context: {"ok": True}},
            worker_id="new-worker",
            clock=StepClock(),
        )
        self.assertEqual(WorkerOutcome.SUCCEEDED, worker.run_once().outcome)
        before = [(event["event_type"], self.payload(event)) for event in self.events(task_id)]

        self.state_store.close()
        self.state_store = StateStore(self.database_path)
        self.event_log = EventLog(self.state_store)
        self.task_store = TaskStore(self.state_store, event_log=self.event_log)
        after = [(event["event_type"], self.payload(event)) for event in self.events(task_id)]

        self.assertEqual(before, after)
        self.assertEqual(
            ["TASK_CREATED"] + ["TASK_STATE_CHANGED"] * 6,
            [event[0] for event in after],
        )

    def test_t12_11_resource_lock_is_not_released(self) -> None:
        task_id = "TASK_T12_LOCK"
        self.create_task(task_id, status=TaskState.RUNNING, worker="old-worker")
        locks = ResourceLockManager(self.state_store, clock=StepClock())
        before = locks.acquire(ResourceId.PHOTOSHOP, task_id)

        self.recovery().recover_startup()
        after = locks.get(ResourceId.PHOTOSHOP)

        self.assertEqual("INTERRUPTED", self.task_store.get(task_id)["status"])
        self.assertEqual(before, after)
        self.assertEqual("HELD", after["status"])
        self.assertEqual(task_id, after["owner_task_id"])

    def test_t12_12_provider_submission_is_untouched(self) -> None:
        task_id = "TASK_T12_PROVIDER"
        self.create_task(task_id, status=TaskState.RUNNING, worker="old-worker")
        self.state_store.create_sequence("SQ_T12_PROVIDER", "PRJ_T12", 1)
        self.state_store.create_shot("SHOT_T12_PROVIDER", "PRJ_T12", "SQ_T12_PROVIDER", {"duration_sec": 1})
        self.state_store.create_artifact(
            "ART_T12_PROVIDER",
            "PRJ_T12",
            "video",
            "master",
            "generated/t12.mp4",
            "v1",
            shot_id="SHOT_T12_PROVIDER",
        )
        self.state_store.create_generation(
            "GEN_T12_PROVIDER",
            "SHOT_T12_PROVIDER",
            "ART_T12_PROVIDER",
            "mock",
        )
        submissions = ProviderSubmissionStore(self.state_store, clock=StepClock())
        reservation = submissions.prepare_intent(
            generation_id="GEN_T12_PROVIDER",
            project_id="PRJ_T12",
            shot_id="SHOT_T12_PROVIDER",
            provider="mock",
            idempotency_key="T12_PROVIDER_KEY",
            request_hash="T12_PROVIDER_HASH",
        )
        submitting = submissions.mark_submitting(reservation.submission["id"])
        before = submissions.mark_unknown(submitting["id"])
        self.assertEqual(SubmissionStatus.UNKNOWN.value, before["status"])

        self.recovery().recover_startup()
        after = submissions.get(before["id"])

        self.assertEqual(before, after)

    def test_t12_13_supervisor_is_diagnostic_only_and_called_once(self) -> None:
        task_id = "TASK_T12_SUPERVISOR"
        self.create_task(task_id, status=TaskState.RUNNING, worker="old-worker")
        supervisor = SnapshotStub()
        before_event_count = len(self.event_log.list())
        locks = ResourceLockManager(self.state_store, clock=StepClock())
        locks_before = locks.get(ResourceId.PHOTOSHOP)

        report = self.recovery(supervisor).recover_startup()

        self.assertEqual(1, supervisor.calls)
        self.assertEqual(1, report["interrupted_count"])
        self.assertEqual(before_event_count + 1, len(self.event_log.list()))
        self.assertEqual(locks_before, locks.get(ResourceId.PHOTOSHOP))

    def test_t12_14_recovery_report_has_accurate_structured_fields(self) -> None:
        self.create_task("TASK_T12_REPORT_A", status=TaskState.RUNNING, worker="old-worker")
        self.create_task("TASK_T12_REPORT_B", status=TaskState.SUCCEEDED, worker="old-worker")

        report = self.recovery().recover_startup()

        for field in ("observed_at", "running_scanned", "interrupted", "preserved", "errors", "supervisor_snapshot"):
            self.assertIn(field, report)
        self.assertEqual(1, report["running_scanned"])
        self.assertEqual(1, report["interrupted_count"])
        self.assertEqual(0, report["preserved_count"])
        self.assertEqual(0, report["error_count"])
        self.assertTrue(report["completed"])

    def test_t12_15_canonical_startup_hook_recovers_before_health(self) -> None:
        root = Path(self.temp_dir.name) / "startup"
        root.mkdir()
        candidate = root / "candidate.db"
        legacy = isolated_legacy_v3_path("t12-startup-hook")
        config = root / "runtime-startup.json"
        write_runtime_startup_config(
            RuntimeStartupConfig.build(
                runtime_mode="v5",
                runtime_db=candidate,
                legacy_readonly_db=legacy,
                production=False,
                generated_by="tests.runtime.test_restart_recovery",
                cutover_run_id="t12-startup-hook",
            ),
            config,
        )
        store = StateStore(candidate, initialize=True)
        tasks = TaskStore(store)
        store.create_project("PRJ_T12_STARTUP", "T12 Startup", "16:9", 24, 12)
        tasks.create(
            task_id="TASK_T12_STARTUP",
            task_type="TEST_STARTUP",
            project_id="PRJ_T12_STARTUP",
            status=TaskState.RUNNING,
            worker="previous-process-worker",
            attempt=1,
        )
        self.assertEqual("RUNNING", tasks.get("TASK_T12_STARTUP")["status"])
        store.close()

        script = """
import json
from fastapi.testclient import TestClient
import server
with TestClient(server.app) as client:
    health = client.get('/api/health')
    from core.runtime.state_store import TaskStore
    task = TaskStore(server.app.state.persistence.store).get('TASK_T12_STARTUP')
    print(json.dumps({'health_status': health.status_code, 'health': health.json(), 'report': server.app.state.startup_recovery, 'db': str(server.app.state.persistence.path), 'task_status': task['status']}))
"""
        environment = os.environ.copy()
        for key in ("FRAMEFLOW_RUNTIME_CONFIG", "FRAMEFLOW_DB_PATH", "FRAMEFLOW_V5_DB", "FRAMEFLOW_LEGACY_READONLY_DB"):
            environment.pop(key, None)
        environment.update(
            {
                "FRAMEFLOW_RUNTIME_CONFIG": str(config),
                "FRAMEFLOW_RUNTIME_MODE": "v5",
                "FRAMEFLOW_DB_PATH": str(candidate),
                "FRAMEFLOW_V5_DB": str(candidate),
                "FRAMEFLOW_V5_PRODUCTION": "0",
                "FRAMEFLOW_V5_PRODUCTION_SIMULATION": "0",
                "FRAMEFLOW_LEGACY_READONLY_DB": str(legacy),
                "FRAMEFLOW_BIND_HOST": "127.0.0.1",
            }
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(200, payload["health_status"])
        self.assertTrue(payload["health"]["ready"])
        self.assertEqual(["TASK_T12_STARTUP"], payload["report"]["interrupted"], payload)
        self.assertEqual("INTERRUPTED", payload["task_status"])

        reopened = StateStore(candidate)
        try:
            self.assertEqual("INTERRUPTED", TaskStore(reopened).get("TASK_T12_STARTUP")["status"])
        finally:
            reopened.close()

    def test_t12_16_startup_recovery_failure_is_surfaced_before_ready(self) -> None:
        root = Path(self.temp_dir.name) / "startup-failure"
        root.mkdir()
        candidate = root / "candidate.db"
        legacy = isolated_legacy_v3_path("t12-startup-failure")
        config = root / "runtime-startup.json"
        write_runtime_startup_config(
            RuntimeStartupConfig.build(
                runtime_mode="v5",
                runtime_db=candidate,
                legacy_readonly_db=legacy,
                production=False,
                generated_by="tests.runtime.test_restart_recovery",
                cutover_run_id="t12-startup-failure",
            ),
            config,
        )
        store = StateStore(candidate, initialize=True)
        tasks = TaskStore(store)
        store.create_project("PRJ_T12_FAILURE", "T12 Failure", "16:9", 24, 12)
        tasks.create(
            task_id="TASK_T12_STARTUP_FAILURE",
            task_type="TEST_STARTUP",
            project_id="PRJ_T12_FAILURE",
            status=TaskState.RUNNING,
            worker="previous-process-worker",
        )
        with store.transaction() as connection:
            connection.exec_driver_sql(
                """CREATE TRIGGER fail_t12_startup_event
                BEFORE INSERT ON events
                WHEN NEW.entity_id = 'TASK_T12_STARTUP_FAILURE'
                  AND NEW.event_type = 'TASK_STATE_CHANGED'
                BEGIN SELECT RAISE(ABORT, 'T12 startup event failure'); END"""
            )
        store.close()

        script = """
from fastapi.testclient import TestClient
import server
try:
    with TestClient(server.app):
        print('UNEXPECTED_READY')
except Exception as exc:
    print(type(exc).__name__)
"""
        environment = os.environ.copy()
        for key in ("FRAMEFLOW_RUNTIME_CONFIG", "FRAMEFLOW_DB_PATH", "FRAMEFLOW_V5_DB", "FRAMEFLOW_LEGACY_READONLY_DB"):
            environment.pop(key, None)
        environment.update(
            {
                "FRAMEFLOW_RUNTIME_CONFIG": str(config),
                "FRAMEFLOW_RUNTIME_MODE": "v5",
                "FRAMEFLOW_DB_PATH": str(candidate),
                "FRAMEFLOW_V5_DB": str(candidate),
                "FRAMEFLOW_V5_PRODUCTION": "0",
                "FRAMEFLOW_V5_PRODUCTION_SIMULATION": "0",
                "FRAMEFLOW_LEGACY_READONLY_DB": str(legacy),
                "FRAMEFLOW_BIND_HOST": "127.0.0.1",
            }
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertNotIn("UNEXPECTED_READY", completed.stdout, completed.stderr)
        self.assertIn("RecoveryError", completed.stdout)
        self.assertTrue(completed.stdout.strip())

        reopened = StateStore(candidate)
        try:
            self.assertEqual("RUNNING", TaskStore(reopened).get("TASK_T12_STARTUP_FAILURE")["status"])
        finally:
            with reopened.transaction() as connection:
                connection.exec_driver_sql("DROP TRIGGER fail_t12_startup_event")
            reopened.close()


if __name__ == "__main__":
    import unittest

    unittest.main()
