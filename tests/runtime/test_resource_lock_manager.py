from __future__ import annotations

import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase

from sqlalchemy.exc import IntegrityError

from core.runtime.resource_locks import (
    Compatibility,
    InvalidResourceError,
    LeaseExpiredError,
    LockStatus,
    NotLockOwnerError,
    OwnerTaskNotFoundError,
    ResourceBusyError,
    ResourceCompatibilityUndefined,
    ResourceLockManager,
)
from core.runtime.state_store import StateStore, TaskStore


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 30, 6, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


class ResourceLockManagerTests(TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="frameflow-resource-lock-t08-")
        self.database_path = Path(self.temp_dir.name) / "resource-locks.db"
        self.state_store = StateStore(self.database_path, initialize=True)
        self.task_store = TaskStore(self.state_store)
        self.state_store.create_project("PRJ_T08", "T08 Project", "16:9", 24, 12)
        self.create_task("TASK_T08_A")
        self.create_task("TASK_T08_B")
        self.clock = FakeClock()
        self.manager = ResourceLockManager(self.state_store, clock=self.clock)

    def tearDown(self) -> None:
        self.state_store.close()
        self.temp_dir.cleanup()

    def create_task(self, task_id: str) -> None:
        self.task_store.create(
            task_id=task_id,
            task_type="TEST_RESOURCE_LOCK",
            project_id="PRJ_T08",
        )

    def test_t08_01_basic_acquire_persists_frozen_lease_contract(self) -> None:
        lock = self.manager.acquire("PHOTOSHOP", "TASK_T08_A")
        self.assertEqual(
            {
                "resource_id": "PHOTOSHOP",
                "owner_task_id": "TASK_T08_A",
                "lease_timeout": 300,
                "status": "HELD",
            },
            {key: lock[key] for key in ("resource_id", "owner_task_id", "lease_timeout", "status")},
        )
        self.assertIsNotNone(lock["acquired_at"])
        self.assertIsNotNone(lock["heartbeat_at"])

    def test_t08_02_persistence_survives_reopen(self) -> None:
        self.manager.acquire("PHOTOSHOP", "TASK_T08_A")
        self.state_store.close()
        self.state_store = StateStore(self.database_path)
        self.manager = ResourceLockManager(self.state_store, clock=self.clock)
        lock = self.manager.get("PHOTOSHOP")
        self.assertEqual("TASK_T08_A", lock["owner_task_id"])
        self.assertEqual("HELD", lock["status"])

    def test_t08_03_same_resource_is_exclusive(self) -> None:
        self.manager.acquire("PHOTOSHOP", "TASK_T08_A")
        with self.assertRaises(ResourceBusyError):
            self.manager.acquire("PHOTOSHOP", "TASK_T08_B")

    def test_t08_04_concurrent_same_resource_has_one_winner(self) -> None:
        store_a = StateStore(self.database_path)
        store_b = StateStore(self.database_path)
        manager_a = ResourceLockManager(store_a, clock=self.clock)
        manager_b = ResourceLockManager(store_b, clock=self.clock)
        barrier = threading.Barrier(2)
        winners: list[dict] = []
        denied: list[BaseException] = []
        errors: list[BaseException] = []

        def acquire(manager, owner):
            try:
                barrier.wait(timeout=5)
                winners.append(manager.acquire("RESOLVE", owner))
            except ResourceBusyError as exc:
                denied.append(exc)
            except BaseException as exc:  # pragma: no cover - assertion reports the concrete error
                errors.append(exc)

        first = threading.Thread(target=acquire, args=(manager_a, "TASK_T08_A"))
        second = threading.Thread(target=acquire, args=(manager_b, "TASK_T08_B"))
        first.start()
        second.start()
        first.join(timeout=8)
        second.join(timeout=8)
        try:
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual([], errors)
            self.assertEqual(1, len(winners))
            self.assertEqual(1, len(denied))
            self.assertEqual(1, len(self.manager.list_active()))
        finally:
            store_a.close()
            store_b.close()

    def test_t08_05_same_owner_reacquire_is_idempotent(self) -> None:
        first = self.manager.acquire("PHOTOSHOP", "TASK_T08_A")
        second = self.manager.acquire("PHOTOSHOP", "TASK_T08_A")
        self.assertEqual(first, second)
        self.assertEqual(1, len(self.manager.list_active()))

    def test_t08_06_photoshop_and_after_effects_conflict(self) -> None:
        self.manager.acquire("PHOTOSHOP", "TASK_T08_A")
        with self.assertRaises(ResourceBusyError):
            self.manager.acquire("AFTER_EFFECTS", "TASK_T08_B")

    def test_t08_07_photoshop_and_resolve_conflict(self) -> None:
        self.manager.acquire("PHOTOSHOP", "TASK_T08_A")
        with self.assertRaises(ResourceBusyError):
            self.manager.acquire("RESOLVE", "TASK_T08_B")

    def test_t08_08_after_effects_and_resolve_conflict(self) -> None:
        self.manager.acquire("AFTER_EFFECTS", "TASK_T08_A")
        with self.assertRaises(ResourceBusyError):
            self.manager.acquire("RESOLVE", "TASK_T08_B")

    def test_t08_09_comfy_gpu_and_photoshop_are_allowed(self) -> None:
        self.manager.acquire("PHOTOSHOP", "TASK_T08_A")
        comfy = self.manager.acquire("COMFY_GPU", "TASK_T08_B")
        self.assertEqual("TASK_T08_B", comfy["owner_task_id"])
        self.assertEqual(2, len(self.manager.list_active()))

    def test_t08_10_comfy_gpu_conflicts_with_after_effects_and_resolve(self) -> None:
        self.manager.acquire("COMFY_GPU", "TASK_T08_A")
        self.assertEqual(Compatibility.CONFLICT, self.manager.check_compatibility("AFTER_EFFECTS"))
        self.assertEqual(Compatibility.CONFLICT, self.manager.check_compatibility("RESOLVE"))
        with self.assertRaises(ResourceBusyError):
            self.manager.acquire("AFTER_EFFECTS", "TASK_T08_B")
        with self.assertRaises(ResourceBusyError):
            self.manager.acquire("RESOLVE", "TASK_T08_B")

        self.manager.release("COMFY_GPU", "TASK_T08_A")
        self.manager.acquire("AFTER_EFFECTS", "TASK_T08_A")
        self.assertEqual(Compatibility.CONFLICT, self.manager.check_compatibility("COMFY_GPU"))
        with self.assertRaises(ResourceBusyError):
            self.manager.acquire("COMFY_GPU", "TASK_T08_B")

        self.manager.release("AFTER_EFFECTS", "TASK_T08_A")
        self.manager.acquire("RESOLVE", "TASK_T08_A")
        self.assertEqual(Compatibility.CONFLICT, self.manager.check_compatibility("COMFY_GPU"))
        with self.assertRaises(ResourceBusyError):
            self.manager.acquire("COMFY_GPU", "TASK_T08_B")

    def test_t08_m01_to_m06_complete_matrix_is_symmetric(self) -> None:
        matrix = (
            ("PHOTOSHOP", "AFTER_EFFECTS", Compatibility.CONFLICT),
            ("PHOTOSHOP", "RESOLVE", Compatibility.CONFLICT),
            ("AFTER_EFFECTS", "RESOLVE", Compatibility.CONFLICT),
            ("COMFY_GPU", "PHOTOSHOP", Compatibility.ALLOW),
            ("COMFY_GPU", "AFTER_EFFECTS", Compatibility.CONFLICT),
            ("COMFY_GPU", "RESOLVE", Compatibility.CONFLICT),
        )
        for left, right, expected in matrix:
            for first, second in ((left, right), (right, left)):
                with self.subTest(first=first, second=second):
                    self.manager.acquire(first, "TASK_T08_A")
                    self.assertEqual(expected, self.manager.check_compatibility(second))
                    if expected is Compatibility.ALLOW:
                        self.manager.acquire(second, "TASK_T08_B")
                        self.manager.release(second, "TASK_T08_B")
                    else:
                        with self.assertRaises(ResourceBusyError):
                            self.manager.acquire(second, "TASK_T08_B")
                    self.manager.release(first, "TASK_T08_A")

    def test_t08_11_current_owner_heartbeat_updates_lease(self) -> None:
        lock = self.manager.acquire("COMFY_GPU", "TASK_T08_A")
        self.clock.advance(30)
        renewed = self.manager.heartbeat("COMFY_GPU", "TASK_T08_A")
        self.assertGreater(renewed["heartbeat_at"], lock["heartbeat_at"])
        self.assertEqual("TASK_T08_A", renewed["owner_task_id"])
        self.assertEqual(300, renewed["lease_timeout"])

    def test_t08_12_wrong_owner_heartbeat_is_rejected(self) -> None:
        lock = self.manager.acquire("COMFY_GPU", "TASK_T08_A")
        self.clock.advance(30)
        with self.assertRaises(NotLockOwnerError):
            self.manager.heartbeat("COMFY_GPU", "TASK_T08_B")
        self.assertEqual(lock["heartbeat_at"], self.manager.get("COMFY_GPU")["heartbeat_at"])
        self.assertEqual("TASK_T08_A", self.manager.get("COMFY_GPU")["owner_task_id"])

    def test_t08_13_heartbeat_prevents_expiry(self) -> None:
        self.manager.acquire("COMFY_GPU", "TASK_T08_A")
        self.clock.advance(299)
        self.manager.heartbeat("COMFY_GPU", "TASK_T08_A")
        self.clock.advance(299)
        self.assertEqual(1, len(self.manager.list_active()))
        self.clock.advance(2)
        self.assertEqual([], self.manager.list_active())

    def test_t08_14_lease_expiration_is_inspectable_without_task_recovery(self) -> None:
        self.manager.acquire("PHOTOSHOP", "TASK_T08_A")
        self.clock.advance(300)
        expired = self.manager.inspect_expired()
        self.assertEqual(["PHOTOSHOP"], [lock["resource_id"] for lock in expired])
        self.assertEqual("HELD", self.manager.get("PHOTOSHOP")["status"])
        self.assertEqual([], self.manager.list_active())

    def test_t08_15_expired_lock_can_be_taken_over(self) -> None:
        self.manager.acquire("PHOTOSHOP", "TASK_T08_A")
        self.clock.advance(301)
        takeover = self.manager.acquire("PHOTOSHOP", "TASK_T08_B")
        self.assertEqual("TASK_T08_B", takeover["owner_task_id"])
        self.assertEqual("HELD", takeover["status"])

    def test_t08_16_stale_owner_heartbeat_is_rejected_after_takeover(self) -> None:
        self.manager.acquire("PHOTOSHOP", "TASK_T08_A")
        self.clock.advance(301)
        self.manager.acquire("PHOTOSHOP", "TASK_T08_B")
        with self.assertRaises(NotLockOwnerError):
            self.manager.heartbeat("PHOTOSHOP", "TASK_T08_A")
        self.assertEqual("TASK_T08_B", self.manager.get("PHOTOSHOP")["owner_task_id"])

    def test_t08_17_stale_owner_release_cannot_release_new_owner(self) -> None:
        self.manager.acquire("PHOTOSHOP", "TASK_T08_A")
        self.clock.advance(301)
        self.manager.acquire("PHOTOSHOP", "TASK_T08_B")
        with self.assertRaises(NotLockOwnerError):
            self.manager.release("PHOTOSHOP", "TASK_T08_A")
        self.assertEqual("TASK_T08_B", self.manager.get("PHOTOSHOP")["owner_task_id"])
        self.assertEqual("HELD", self.manager.get("PHOTOSHOP")["status"])

    def test_t08_18_valid_release_makes_resource_available(self) -> None:
        self.manager.acquire("RESOLVE", "TASK_T08_A")
        released = self.manager.release("RESOLVE", "TASK_T08_A")
        self.assertEqual(LockStatus.RELEASED.value, released["status"])
        self.assertEqual([], self.manager.list_active())
        reacquired = self.manager.acquire("RESOLVE", "TASK_T08_B")
        self.assertEqual("TASK_T08_B", reacquired["owner_task_id"])

    def test_t08_19_wrong_owner_release_is_rejected(self) -> None:
        self.manager.acquire("PHOTOSHOP", "TASK_T08_A")
        with self.assertRaises(NotLockOwnerError):
            self.manager.release("PHOTOSHOP", "TASK_T08_B")
        self.assertEqual("TASK_T08_A", self.manager.get("PHOTOSHOP")["owner_task_id"])

    def test_t08_20_acquire_transaction_failure_has_no_partial_lock(self) -> None:
        with self.state_store.transaction() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER fail_resource_acquire "
                "BEFORE INSERT ON resource_locks "
                "BEGIN SELECT RAISE(ABORT, 'resource acquire failure'); END"
            )
        try:
            with self.assertRaises(IntegrityError):
                self.manager.acquire("PHOTOSHOP", "TASK_T08_A")
            self.assertIsNone(self.manager.get("PHOTOSHOP"))
            self.assertEqual([], self.manager.list_active())
        finally:
            with self.state_store.transaction() as connection:
                connection.exec_driver_sql("DROP TRIGGER fail_resource_acquire")

    def test_t08_21_release_transaction_failure_preserves_owner(self) -> None:
        self.manager.acquire("PHOTOSHOP", "TASK_T08_A")
        with self.state_store.transaction() as connection:
            connection.exec_driver_sql(
                "CREATE TRIGGER fail_resource_release "
                "BEFORE UPDATE OF status ON resource_locks "
                "WHEN NEW.status = 'RELEASED' "
                "BEGIN SELECT RAISE(ABORT, 'resource release failure'); END"
            )
        try:
            with self.assertRaises(IntegrityError):
                self.manager.release("PHOTOSHOP", "TASK_T08_A")
            lock = self.manager.get("PHOTOSHOP")
            self.assertEqual("TASK_T08_A", lock["owner_task_id"])
            self.assertEqual("HELD", lock["status"])
        finally:
            with self.state_store.transaction() as connection:
                connection.exec_driver_sql("DROP TRIGGER fail_resource_release")

    def test_t08_22_invalid_resource_and_missing_owner_are_rejected(self) -> None:
        with self.assertRaises(InvalidResourceError):
            self.manager.acquire("../../foo", "TASK_T08_A")
        with self.assertRaises(OwnerTaskNotFoundError):
            self.manager.acquire("PHOTOSHOP", "TASK_MISSING")

    def test_t08_23_expired_owner_cannot_heartbeat_or_release(self) -> None:
        self.manager.acquire("PHOTOSHOP", "TASK_T08_A")
        self.clock.advance(300)
        with self.assertRaises(LeaseExpiredError):
            self.manager.heartbeat("PHOTOSHOP", "TASK_T08_A")
        with self.assertRaises(LeaseExpiredError):
            self.manager.release("PHOTOSHOP", "TASK_T08_A")


if __name__ == "__main__":
    import unittest

    unittest.main()
