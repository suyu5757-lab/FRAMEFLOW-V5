"""Restart reconciliation for the in-process Worker Runtime.

T12 only reconciles stale ``RUNNING`` Tasks during a cold startup.  It does
not retry work, release ResourceLocks, touch Provider Submissions, or manage
Creative App processes.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Callable

from core.runtime.state_store import TaskState, TaskStore
from core.runtime.supervisor import LivenessResult, Supervisor


class RecoveryError(RuntimeError):
    """Raised when startup recovery cannot reconcile every stale Task."""

    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        failed = ", ".join(str(item.get("task_id")) for item in report.get("errors", []))
        super().__init__(f"startup recovery failed for Tasks: {failed or 'unknown'}")


class RestartRecovery:
    """Cold-start recovery over the canonical TaskStore transition primitive."""

    def __init__(
        self,
        task_store: TaskStore,
        *,
        supervisor: Supervisor | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._tasks = task_store
        self._supervisor = supervisor or Supervisor()
        self._clock = clock or (lambda: datetime.now(UTC))

    def recover_startup(self) -> dict[str, Any]:
        """Reconcile a cold restart with no surviving in-process Workers."""

        # A new Python process cannot retain Worker instances from the old
        # process.  The empty active set is therefore the only safe startup
        # assumption for this MVP.
        return self._reconcile(active_worker_ids=frozenset())

    def reconcile_running_tasks(
        self,
        active_worker_ids: Iterable[str],
    ) -> dict[str, Any]:
        """Reconcile RUNNING Tasks while preserving explicitly active owners.

        This is a controlled diagnostic/test seam; canonical cold startup uses
        ``recover_startup()`` and never supplies a stale Worker ID as active.
        """

        if isinstance(active_worker_ids, (str, bytes)):
            raise ValueError("active_worker_ids must be an iterable of worker IDs")
        active = frozenset(
            value.strip()
            for value in active_worker_ids
            if isinstance(value, str) and value.strip()
        )
        return self._reconcile(active_worker_ids=active)

    def _reconcile(self, *, active_worker_ids: frozenset[str]) -> dict[str, Any]:
        observed_at = self._observed_at()
        supervisor_snapshot = self._snapshot_payload()
        running = self._tasks.list(status=TaskState.RUNNING)
        report: dict[str, Any] = {
            "observed_at": observed_at.isoformat(),
            "running_scanned": len(running),
            "interrupted": [],
            "preserved": [],
            "errors": [],
            "supervisor_snapshot": supervisor_snapshot,
        }

        for task in running:
            task_id = str(task["id"])
            worker = task.get("worker")
            if isinstance(worker, str) and worker in active_worker_ids:
                report["preserved"].append(task_id)
                continue

            reason_code = "missing_worker_owner" if not worker else "runtime_restart_interrupted"
            error = {
                "code": reason_code,
                "reason_code": reason_code,
                "message": (
                    "cold startup found a RUNNING Task without an active in-process Worker"
                ),
                "retryable": True,
                "previous_worker": worker,
                "recovered_at": observed_at.isoformat(),
            }
            try:
                updated = self._tasks.interrupt_running_if(
                    task_id,
                    expected_worker=worker,
                    error=error,
                    recovered_at=observed_at,
                    reason_code=reason_code,
                )
                if updated is not None:
                    report["interrupted"].append(task_id)
                    continue
                current = self._tasks.get(task_id)
                if current is not None and current.get("status") != TaskState.RUNNING.value:
                    report["preserved"].append(task_id)
                else:
                    report["errors"].append(
                        {
                            "task_id": task_id,
                            "code": "recovery_conflict",
                            "message": "Task changed while startup recovery was rechecking it",
                        }
                    )
            except Exception:
                # Do not expose exception text, command lines, or credentials
                # in the report.  The failed transaction leaves the Task
                # visibly RUNNING and startup surfaces RecoveryError below.
                report["errors"].append(
                    {
                        "task_id": task_id,
                        "code": "recovery_transaction_failed",
                        "message": "Task interruption transaction could not be committed",
                    }
                )

        report["interrupted_count"] = len(report["interrupted"])
        report["preserved_count"] = len(report["preserved"])
        report["error_count"] = len(report["errors"])
        report["completed"] = not report["errors"]
        if report["errors"]:
            raise RecoveryError(report)
        return report

    def _observed_at(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Recovery clock must return an aware datetime")
        return value.astimezone(UTC)

    def _snapshot_payload(self) -> dict[str, Any]:
        try:
            snapshot = self._supervisor.snapshot()
        except Exception:
            return {"error_code": "supervisor_snapshot_failed"}
        return {
            str(target.value): self._liveness_payload(result)
            for target, result in snapshot.items()
        }

    @staticmethod
    def _liveness_payload(result: LivenessResult) -> dict[str, Any]:
        return {
            "target": result.target.value,
            "state": result.state.value,
            "observed_at": result.observed_at.isoformat(),
            "matched_processes": [
                {
                    "pid": item.pid,
                    "executable_name": item.executable_name,
                    "executable_path": item.executable_path,
                }
                for item in result.matched_processes
            ],
            "error_code": result.error_code,
        }


__all__ = ["RecoveryError", "RestartRecovery"]
