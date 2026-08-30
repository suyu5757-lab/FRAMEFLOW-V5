from __future__ import annotations

import importlib
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import psutil

from core.runtime.state_store import StateStore
from core.runtime.supervisor import (
    LivenessState,
    ProcessRecord,
    Supervisor,
    SupervisorTarget,
    UnsupportedTargetError,
    WindowsProcessInspector,
)


supervisor_module = importlib.import_module("core.runtime.supervisor.supervisor")


class StepClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)
        self.lock = threading.Lock()

    def __call__(self) -> datetime:
        with self.lock:
            value = self.current
            self.current += timedelta(seconds=1)
            return value


class FakeProcessInspector:
    def __init__(self, records=(), *, error: BaseException | None = None) -> None:
        self.records = records
        self.error = error
        self.calls = 0

    def list_processes(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.records


class TaskSupervisorTests(TestCase):
    def test_t11_01_photoshop_running(self) -> None:
        inspector = FakeProcessInspector([ProcessRecord(101, "Photoshop.exe")])
        result = Supervisor(inspector, clock=StepClock()).probe(SupervisorTarget.PHOTOSHOP)

        self.assertEqual(LivenessState.RUNNING, result.state)
        self.assertEqual((ProcessRecord(101, "Photoshop.exe"),), result.matched_processes)
        self.assertEqual(SupervisorTarget.PHOTOSHOP, result.target)

    def test_t11_02_photoshop_not_running(self) -> None:
        inspector = FakeProcessInspector([ProcessRecord(101, "Illustrator.exe")])
        result = Supervisor(inspector, clock=StepClock()).probe(SupervisorTarget.PHOTOSHOP)

        self.assertEqual(LivenessState.NOT_RUNNING, result.state)
        self.assertEqual((), result.matched_processes)

    def test_t11_03_after_effects_ui_running(self) -> None:
        result = Supervisor(
            FakeProcessInspector([ProcessRecord(201, "AfterFX.exe", r"C:\Adobe\AfterFX.exe")]),
            clock=StepClock(),
        ).probe(SupervisorTarget.AFTER_EFFECTS)

        self.assertEqual(LivenessState.RUNNING, result.state)
        self.assertEqual(201, result.matched_processes[0].pid)

    def test_t11_04_aerender_is_after_effects_liveness(self) -> None:
        result = Supervisor(
            FakeProcessInspector([ProcessRecord(202, "aerender.exe")]),
            clock=StepClock(),
        ).probe(SupervisorTarget.AFTER_EFFECTS)

        self.assertEqual(LivenessState.RUNNING, result.state)
        self.assertEqual("aerender.exe", result.matched_processes[0].executable_name)

    def test_t11_05_resolve_running(self) -> None:
        result = Supervisor(
            FakeProcessInspector([ProcessRecord(301, "Resolve.exe")]),
            clock=StepClock(),
        ).probe(SupervisorTarget.RESOLVE)

        self.assertEqual(LivenessState.RUNNING, result.state)

    def test_t11_06_snapshot_all_targets_uses_one_enumeration(self) -> None:
        inspector = FakeProcessInspector(
            [ProcessRecord(101, "Photoshop.exe"), ProcessRecord(202, "aerender.exe")]
        )
        results = Supervisor(inspector, clock=StepClock()).snapshot()

        self.assertEqual(1, inspector.calls)
        self.assertEqual(
            set(SupervisorTarget),
            set(results),
        )
        self.assertEqual(LivenessState.RUNNING, results[SupervisorTarget.PHOTOSHOP].state)
        self.assertEqual(LivenessState.RUNNING, results[SupervisorTarget.AFTER_EFFECTS].state)
        self.assertEqual(LivenessState.NOT_RUNNING, results[SupervisorTarget.RESOLVE].state)
        self.assertEqual(
            {result.observed_at for result in results.values()},
            {datetime(2026, 8, 30, 9, 0, tzinfo=UTC)},
        )

    def test_t11_07_exact_matching_rejects_false_positives(self) -> None:
        records = [
            ProcessRecord(1, "FakePhotoshop.exe"),
            ProcessRecord(2, "photoshop-helper-not-real.exe"),
            ProcessRecord(3, "ResolveHelperFake.exe"),
        ]
        results = Supervisor(FakeProcessInspector(records), clock=StepClock()).snapshot()

        self.assertEqual(LivenessState.NOT_RUNNING, results[SupervisorTarget.PHOTOSHOP].state)
        self.assertEqual(LivenessState.NOT_RUNNING, results[SupervisorTarget.RESOLVE].state)

    def test_t11_08_matching_is_case_insensitive(self) -> None:
        result = Supervisor(
            FakeProcessInspector([ProcessRecord(101, "pHoToShOp.ExE")]),
            clock=StepClock(),
        ).probe(SupervisorTarget.PHOTOSHOP)

        self.assertEqual(LivenessState.RUNNING, result.state)

    def test_t11_09_multiple_matching_processes_are_returned_sorted(self) -> None:
        records = [
            ProcessRecord(505, "Photoshop.exe"),
            ProcessRecord(101, "Photoshop.exe"),
        ]
        result = Supervisor(FakeProcessInspector(records), clock=StepClock()).probe(
            SupervisorTarget.PHOTOSHOP
        )

        self.assertEqual(LivenessState.RUNNING, result.state)
        self.assertEqual((101, 505), tuple(item.pid for item in result.matched_processes))

    def test_t11_10_process_disappearing_during_scan_does_not_crash(self) -> None:
        def source():
            yield ProcessRecord(1, "Unrelated.exe")
            raise psutil.NoSuchProcess(2)

        result = Supervisor(FakeProcessInspector(source()), clock=StepClock()).probe(
            SupervisorTarget.PHOTOSHOP
        )

        self.assertEqual(LivenessState.NOT_RUNNING, result.state)

    def test_t11_11_partial_access_denied_does_not_crash(self) -> None:
        def source():
            yield ProcessRecord(1, "Unrelated.exe")
            raise psutil.AccessDenied(2)

        result = Supervisor(FakeProcessInspector(source()), clock=StepClock()).probe(
            SupervisorTarget.RESOLVE
        )

        self.assertEqual(LivenessState.NOT_RUNNING, result.state)

    def test_t11_12_backend_failure_is_unknown(self) -> None:
        result = Supervisor(
            FakeProcessInspector(error=RuntimeError("backend offline")),
            clock=StepClock(),
        ).probe(SupervisorTarget.PHOTOSHOP)

        self.assertEqual(LivenessState.UNKNOWN, result.state)
        self.assertEqual("enumeration_failed", result.error_code)
        self.assertEqual((), result.matched_processes)

    def test_t11_13_unsupported_string_is_rejected_before_os_query(self) -> None:
        inspector = FakeProcessInspector()
        supervisor = Supervisor(inspector, clock=StepClock())

        with self.assertRaises(UnsupportedTargetError):
            supervisor.probe("PHOTOSHOP")  # type: ignore[arg-type]
        self.assertEqual(0, inspector.calls)

    def test_t11_14_probe_has_no_runtime_database_side_effects(self) -> None:
        temp_dir = tempfile.TemporaryDirectory(prefix="frameflow-supervisor-t11-")
        database_path = Path(temp_dir.name) / "supervisor.db"
        store = StateStore(database_path, initialize=True)

        def counts() -> tuple[int, int, int]:
            with store.connection() as connection:
                return tuple(
                    int(
                        connection.exec_driver_sql(
                            f"SELECT COUNT(*) FROM {table}"
                        ).scalar_one()
                    )
                    for table in ("tasks", "resource_locks", "events")
                )

        try:
            before = counts()
            Supervisor(
                FakeProcessInspector([ProcessRecord(101, "Photoshop.exe")]),
                clock=StepClock(),
            ).snapshot()
            after = counts()
            self.assertEqual((0, 0, 0), before)
            self.assertEqual(before, after)
        finally:
            store.close()
            temp_dir.cleanup()

    def test_t11_15_real_windows_backend_smoke(self) -> None:
        results = Supervisor(clock=StepClock()).snapshot()

        self.assertEqual(set(SupervisorTarget), set(results))
        for target, result in results.items():
            self.assertEqual(target, result.target)
            self.assertIn(result.state, set(LivenessState))
            self.assertIsNotNone(result.observed_at.tzinfo)
            self.assertTrue(all(isinstance(item, ProcessRecord) for item in result.matched_processes))

    def test_t11_16_supervisor_backend_has_no_shell_or_process_control(self) -> None:
        source = Path(__file__).resolve().parents[2] / "core" / "runtime" / "supervisor" / "supervisor.py"
        content = source.read_text(encoding="utf-8")

        self.assertNotIn("shell=True", content)
        self.assertNotIn("Popen", content)
        self.assertNotIn("terminate", content)
        self.assertNotIn("kill", content)

    def test_t11_17_fixed_tasklist_fallback_is_bounded(self) -> None:
        completed = SimpleNamespace(
            returncode=0,
            stdout='"Photoshop.exe","123","Console","1","10 K"\n',
        )
        with patch.object(supervisor_module, "psutil", None), patch.object(
            supervisor_module.subprocess, "run", return_value=completed
        ) as run:
            records = tuple(WindowsProcessInspector().list_processes())

        self.assertEqual((ProcessRecord(123, "Photoshop.exe"),), records)
        run.assert_called_once_with(
            ["tasklist.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            encoding="utf-8",
            errors="replace",
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
