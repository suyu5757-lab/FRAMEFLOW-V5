from __future__ import annotations

import json
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from core.runtime.event_log import EventLog, EventLogError, InvalidEventError
from core.runtime.state_store import StateStore, TaskStore
from core.schemas.runtime_mvp import metadata


class StepClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 30, 7, 0, tzinfo=UTC)
        self.lock = threading.Lock()

    def __call__(self) -> datetime:
        with self.lock:
            value = self.current
            self.current += timedelta(seconds=1)
            return value


class EventLogTests(TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="frameflow-event-log-t10-")
        self.database_path = Path(self.temp_dir.name) / "events.db"
        self.state_store = StateStore(self.database_path, initialize=True)
        self.event_log = EventLog(self.state_store, clock=StepClock())
        self.state_store.create_project("PRJ_T10", "T10 Project", "16:9", 24, 12)

    def tearDown(self) -> None:
        self.state_store.close()
        self.temp_dir.cleanup()

    def test_t10_01_append_persists_canonical_event(self) -> None:
        event = self.event_log.append(
            trace_id="TRACE_T10_01",
            entity_type="project",
            entity_id="PRJ_T10",
            event_type="project.checked",
            payload={"b": 2, "a": 1},
            event_id="EVT_T10_01",
        )
        self.assertEqual("EVT_T10_01", event["id"])
        self.assertEqual("TRACE_T10_01", event["trace_id"])
        self.assertEqual('{"a":1,"b":2}', event["payload"])
        self.assertEqual(event, self.event_log.get("EVT_T10_01"))

    def test_t10_02_query_filters_trace_entity_and_type(self) -> None:
        self.event_log.append(
            trace_id="TRACE_T10_02",
            entity_type="task",
            entity_id="TASK_T10",
            event_type="task.started",
            payload={"step": 1},
            event_id="EVT_T10_02_A",
        )
        self.event_log.append(
            trace_id="TRACE_T10_02",
            entity_type="task",
            entity_id="TASK_T10",
            event_type="task.finished",
            payload={"step": 2},
            event_id="EVT_T10_02_B",
        )
        self.event_log.append(
            trace_id="TRACE_OTHER",
            entity_type="project",
            entity_id="PRJ_T10",
            event_type="project.checked",
            event_id="EVT_T10_02_C",
        )

        self.assertEqual(
            ["EVT_T10_02_A", "EVT_T10_02_B"],
            [event["id"] for event in self.event_log.by_trace("TRACE_T10_02")],
        )
        self.assertEqual(
            ["EVT_T10_02_A", "EVT_T10_02_B"],
            [event["id"] for event in self.event_log.for_entity("task", "TASK_T10")],
        )
        self.assertEqual(
            ["EVT_T10_02_B"],
            [
                event["id"]
                for event in self.event_log.list(
                    entity_type="task",
                    entity_id="TASK_T10",
                    event_type="task.finished",
                )
            ],
        )

    def test_t10_03_secret_keys_are_redacted_at_event_boundary(self) -> None:
        event = self.event_log.append(
            trace_id="TRACE_T10_03",
            entity_type="task",
            entity_id="TASK_T10",
            event_type="task.failed",
            payload={"token": "do-not-store", "nested": {"password": "hidden"}},
        )
        payload = json.loads(event["payload"])
        self.assertEqual("[REDACTED]", payload["token"])
        self.assertEqual("[REDACTED]", payload["nested"]["password"])
        self.assertNotIn("do-not-store", event["payload"])
        self.assertNotIn("hidden", event["payload"])

    def test_t10_04_task_and_event_commit_together(self) -> None:
        task_store = TaskStore(self.state_store)
        task_store.create(task_id="TASK_T10_04", task_type="TEST_EVENT", project_id="PRJ_T10")
        tasks = metadata.tables["tasks"]
        with self.event_log.transaction() as connection:
            connection.execute(
                update(tasks)
                .where(tasks.c.id == "TASK_T10_04")
                .values(status="RUNNING")
            )
            self.event_log.append_in_transaction(
                connection,
                trace_id="TRACE_T10_04",
                entity_type="task",
                entity_id="TASK_T10_04",
                event_type="task.started",
                payload={"status": "RUNNING"},
                event_id="EVT_T10_04",
            )
        self.assertEqual("RUNNING", task_store.get("TASK_T10_04")["status"])
        self.assertIsNotNone(self.event_log.get("EVT_T10_04"))

    def test_t10_05_task_and_event_rollback_together(self) -> None:
        task_store = TaskStore(self.state_store)
        task_store.create(task_id="TASK_T10_05", task_type="TEST_EVENT", project_id="PRJ_T10")
        tasks = metadata.tables["tasks"]
        with self.assertRaises(RuntimeError):
            with self.event_log.transaction() as connection:
                connection.execute(
                    update(tasks)
                    .where(tasks.c.id == "TASK_T10_05")
                    .values(status="RUNNING")
                )
                self.event_log.append_in_transaction(
                    connection,
                    trace_id="TRACE_T10_05",
                    entity_type="task",
                    entity_id="TASK_T10_05",
                    event_type="task.started",
                    event_id="EVT_T10_05",
                )
                raise RuntimeError("rollback test")
        self.assertEqual("CREATED", task_store.get("TASK_T10_05")["status"])
        self.assertIsNone(self.event_log.get("EVT_T10_05"))

    def test_t10_06_duplicate_event_id_rolls_back_second_append(self) -> None:
        self.event_log.append(
            trace_id="TRACE_T10_06",
            entity_type="project",
            entity_id="PRJ_T10",
            event_type="project.checked",
            event_id="EVT_T10_06",
        )
        with self.assertRaises(IntegrityError):
            self.event_log.append(
                trace_id="TRACE_OTHER",
                entity_type="project",
                entity_id="PRJ_T10",
                event_type="project.duplicate",
                event_id="EVT_T10_06",
            )
        self.assertEqual(1, len(self.event_log.list(trace_id="TRACE_T10_06")))
        self.assertEqual([], self.event_log.list(trace_id="TRACE_OTHER"))

    def test_t10_07_concurrent_clients_append_without_lost_events(self) -> None:
        store_a = StateStore(self.database_path)
        store_b = StateStore(self.database_path)
        log_a = EventLog(store_a, clock=StepClock())
        log_b = EventLog(store_b, clock=StepClock())
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def append(log: EventLog, event_id: str) -> None:
            try:
                barrier.wait(timeout=5)
                log.append(
                    trace_id="TRACE_T10_07",
                    entity_type="task",
                    entity_id="TASK_T10",
                    event_type="task.progress",
                    payload={"event_id": event_id},
                    event_id=event_id,
                )
            except BaseException as exc:  # pragma: no cover - assertion reports the concrete error
                errors.append(exc)

        first = threading.Thread(target=append, args=(log_a, "EVT_T10_07_A"))
        second = threading.Thread(target=append, args=(log_b, "EVT_T10_07_B"))
        first.start()
        second.start()
        first.join(timeout=8)
        second.join(timeout=8)
        try:
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual([], errors)
            self.assertEqual(
                ["EVT_T10_07_A", "EVT_T10_07_B"],
                sorted(event["id"] for event in self.event_log.by_trace("TRACE_T10_07")),
            )
        finally:
            store_a.close()
            store_b.close()

    def test_t10_08_reopen_preserves_event_log(self) -> None:
        self.event_log.append(
            trace_id="TRACE_T10_08",
            entity_type="project",
            entity_id="PRJ_T10",
            event_type="project.checked",
            payload={"persisted": True},
            event_id="EVT_T10_08",
        )
        self.state_store.close()
        self.state_store = StateStore(self.database_path)
        self.event_log = EventLog(self.state_store, clock=StepClock())
        self.assertEqual({"persisted": True}, json.loads(self.event_log.get("EVT_T10_08")["payload"]))

    def test_t10_09_invalid_payload_and_limit_are_rejected(self) -> None:
        with self.assertRaises(InvalidEventError):
            self.event_log.append(
                entity_type="project",
                entity_id="PRJ_T10",
                event_type="project.invalid",
                payload={"not_json": {1, 2}},
            )
        with self.assertRaises(EventLogError):
            self.event_log.list(limit=0)
        with self.assertRaises(EventLogError):
            self.event_log.list(limit=1001)


if __name__ == "__main__":
    import unittest

    unittest.main()
