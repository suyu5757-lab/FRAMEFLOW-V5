"""In-process Worker MVP for the FRAMEFLOW V5 Runtime.

The Worker owns execution lifecycle only.  It consumes the persistent T06
Queue, starts one trusted handler, and persists the result or structured
failure through the T05 TaskStore.  It never evaluates payloads, imports
arbitrary handler paths, invokes a provider, or executes a shell command.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from .queue import TaskQueue
from .state_store import TaskState, TaskStore


TaskHandler = Callable[[Mapping[str, Any], "TaskExecutionContext"], Any]


class WorkerError(RuntimeError):
    """Base error for Worker contract failures."""


class WorkerOwnershipLost(WorkerError):
    """Raised when a live handler can no longer heartbeat its Task."""


class TaskTimeoutError(WorkerError):
    """Raised by a cooperative handler after its deadline is reached."""


class HandlerRegistry:
    """Explicit allowlist of code-defined Task handlers."""

    def __init__(self, handlers: Mapping[str, TaskHandler] | None = None) -> None:
        self._handlers: dict[str, TaskHandler] = {}
        for task_type, handler in (handlers or {}).items():
            self.register(task_type, handler)

    def register(self, task_type: str, handler: TaskHandler) -> None:
        if not isinstance(task_type, str) or not task_type.strip():
            raise ValueError("task_type must be a non-empty string")
        if not callable(handler):
            raise TypeError("handler must be callable")
        if task_type in self._handlers:
            raise ValueError(f"handler already registered: {task_type}")
        self._handlers[task_type] = handler

    def resolve(self, task_type: str) -> TaskHandler | None:
        return self._handlers.get(task_type)


@dataclass
class TaskExecutionContext:
    """Narrow cooperative execution context exposed to trusted handlers."""

    task_id: str
    worker_id: str
    attempt: int
    deadline: float | None
    _heartbeat_callback: Callable[[], dict[str, Any]]
    _monotonic: Callable[[], float]
    cancel_event: threading.Event = field(default_factory=threading.Event)

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def heartbeat(self) -> dict[str, Any]:
        """Publish an immediate heartbeat for a cooperative handler."""

        return self._heartbeat_callback()

    def check_cancelled(self) -> None:
        """Raise a safe cooperative timeout signal at the execution boundary."""

        if self.cancel_event.is_set():
            raise TaskTimeoutError("task execution was cancelled or timed out")
        if self.deadline is not None and self._monotonic() >= self.deadline:
            self.cancel_event.set()
            raise TaskTimeoutError("task execution exceeded its timeout")


class WorkerOutcome(StrEnum):
    IDLE = "idle"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    FINALIZATION_FAILED = "finalization_failed"
    OWNERSHIP_LOST = "ownership_lost"


@dataclass(frozen=True)
class WorkerRunResult:
    """Result of one independently testable ``Worker.run_once`` call."""

    outcome: WorkerOutcome
    task_id: str | None
    task_status: TaskState | None
    task: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    @property
    def status(self) -> str:
        """Return the string outcome for callers that do not need the enum."""

        return self.outcome.value


_SENSITIVE_PATTERN = re.compile(
    r"(?i)(api[_ -]?key|token|password|secret|credential|authorization)"
    r"(\s*[:=]\s*)[^\s,;]+"
)


def _safe_message(value: str) -> str:
    message = value.strip() or "handler raised an exception"
    message = _SENSITIVE_PATTERN.sub(r"\1\2[REDACTED]", message)
    return message[:1000]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Worker:
    """One in-process Runtime Worker with a synchronous ``run_once`` API."""

    def __init__(
        self,
        task_store: TaskStore,
        *,
        queue: TaskQueue | None = None,
        handlers: HandlerRegistry | Mapping[str, TaskHandler] | None = None,
        worker_id: str | None = None,
        heartbeat_interval: float = 5.0,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
        heartbeat_observer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if not isinstance(heartbeat_interval, (int, float)) or heartbeat_interval <= 0:
            raise ValueError("heartbeat_interval must be greater than zero")
        self._tasks = task_store
        self._queue = queue or TaskQueue(task_store)
        self._handlers = (
            handlers
            if isinstance(handlers, HandlerRegistry)
            else HandlerRegistry(handlers)
        )
        self.worker_id = worker_id or f"worker-{uuid4().hex}"
        if not isinstance(self.worker_id, str) or not self.worker_id.strip():
            raise ValueError("worker_id must be a non-empty string")
        if len(self.worker_id) > 120:
            raise ValueError("worker_id exceeds 120 characters")
        self.heartbeat_interval = float(heartbeat_interval)
        self._clock = clock or _utc_now
        self._monotonic = monotonic or time.monotonic
        self._heartbeat_observer = heartbeat_observer

    def run_once(self) -> WorkerRunResult:
        """Claim and execute at most one Task, returning an explicit outcome."""

        claimed = self._queue.claim_next()
        if claimed is None:
            return WorkerRunResult(WorkerOutcome.IDLE, None, None)

        started = self._tasks.begin_execution(
            claimed["id"],
            worker=self.worker_id,
            started_at=self._clock(),
        )
        if started is None:
            return WorkerRunResult(
                WorkerOutcome.OWNERSHIP_LOST,
                str(claimed["id"]),
                TaskState.RUNNING,
                task=self._tasks.get(str(claimed["id"])),
            )

        task_id = str(started["id"])
        attempt = int(started["attempt"])
        task_type = str(started["type"])
        timeout = started.get("timeout")
        deadline = None
        if timeout is not None:
            deadline = self._monotonic() + max(0, int(timeout))

        context = TaskExecutionContext(
            task_id=task_id,
            worker_id=self.worker_id,
            attempt=attempt,
            deadline=deadline,
            _heartbeat_callback=lambda: self._heartbeat(task_id),
            _monotonic=self._monotonic,
        )
        stop_heartbeat = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(task_id, stop_heartbeat),
            name=f"frameflow-heartbeat-{task_id}",
            daemon=True,
        )
        heartbeat_thread.start()

        handler_error: dict[str, Any] | None = None
        handler_result: Any = None
        try:
            handler = self._handlers.resolve(task_type)
            if handler is None:
                handler_error = self._error(
                    code="handler_not_registered",
                    exception_type="HandlerNotRegistered",
                    message=f"no trusted handler registered for task type: {task_type}",
                    retryable=False,
                    task=started,
                )
            else:
                try:
                    handler_result = handler(started, context)
                    context.check_cancelled()
                except TaskTimeoutError as exc:
                    handler_error = self._error(
                        code="timeout",
                        exception_type=type(exc).__name__,
                        message=_safe_message(str(exc)),
                        retryable=True,
                        task=started,
                    )
                except Exception as exc:
                    handler_error = self._error(
                        code="handler_failed",
                        exception_type=type(exc).__name__,
                        message=_safe_message(str(exc)),
                        retryable=False,
                        task=started,
                    )
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join()

        if handler_error is not None:
            return self._persist_failure(started, handler_error)

        try:
            serialized_result = json.dumps(
                handler_result,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            result_error = self._error(
                code="result_not_json_serializable",
                exception_type=type(exc).__name__,
                message="trusted handler returned a non-JSON-compatible result",
                retryable=False,
                task=started,
            )
            return self._persist_failure(started, result_error)

        finished_at = self._clock()
        try:
            finished = self._tasks.finish_success(
                task_id,
                worker=self.worker_id,
                result=serialized_result,
                finished_at=finished_at,
            )
        except Exception as exc:
            return self._persist_finalization_failure(started, exc)
        if finished is None:
            return self._persist_finalization_failure(started, WorkerOwnershipLost("Task ownership was lost"))
        return WorkerRunResult(
            WorkerOutcome.SUCCEEDED,
            task_id,
            TaskState.SUCCEEDED,
            task=finished,
        )

    def _heartbeat(self, task_id: str) -> dict[str, Any]:
        updated = self._tasks.touch_heartbeat(
            task_id,
            worker=self.worker_id,
            heartbeat_at=self._clock(),
        )
        if updated is None:
            raise WorkerOwnershipLost(f"Task ownership was lost: {task_id}")
        self._observe_heartbeat(updated)
        return updated

    def _heartbeat_loop(self, task_id: str, stop_event: threading.Event) -> None:
        while not stop_event.wait(self.heartbeat_interval):
            try:
                self._heartbeat(task_id)
            except Exception:
                # A failed heartbeat must not crash the Worker thread.  The
                # next cooperative context check or finalization will report
                # the Task's actual lifecycle outcome safely.
                return

    def _observe_heartbeat(self, task: dict[str, Any]) -> None:
        if self._heartbeat_observer is None:
            return
        try:
            self._heartbeat_observer(task)
        except Exception:
            # The observer is diagnostic/test instrumentation, never lifecycle
            # authority and never allowed to break Task execution.
            return

    def _error(
        self,
        *,
        code: str,
        exception_type: str,
        message: str,
        retryable: bool,
        task: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "code": code,
            "type": exception_type,
            "message": _safe_message(message),
            "retryable": retryable,
            "worker_id": self.worker_id,
            "attempt": int(task["attempt"]),
            "task_type": str(task["type"]),
        }

    def _persist_failure(
        self,
        task: Mapping[str, Any],
        error: dict[str, Any],
    ) -> WorkerRunResult:
        task_id = str(task["id"])
        try:
            failed = self._tasks.finish_failure(
                task_id,
                worker=self.worker_id,
                error=error,
                finished_at=self._clock(),
            )
        except Exception as exc:
            return self._persist_finalization_failure(task, exc)
        if failed is None:
            return self._persist_finalization_failure(
                task,
                WorkerOwnershipLost("Task ownership was lost during failure finalization"),
            )
        return WorkerRunResult(
            WorkerOutcome.FAILED,
            task_id,
            TaskState.FAILED,
            task=failed,
            error=error,
        )

    def _persist_finalization_failure(
        self,
        task: Mapping[str, Any],
        cause: Exception,
    ) -> WorkerRunResult:
        report = self._error(
            code="finalization_failed",
            exception_type=type(cause).__name__,
            message="Task result/error finalization could not be persisted",
            retryable=True,
            task=task,
        )
        task_id = str(task["id"])
        try:
            failed = self._tasks.finish_failure(
                task_id,
                worker=self.worker_id,
                error=report,
                finished_at=self._clock(),
            )
        except Exception:
            failed = None
        if failed is not None:
            return WorkerRunResult(
                WorkerOutcome.FAILED,
                task_id,
                TaskState.FAILED,
                task=failed,
                error=report,
            )
        return WorkerRunResult(
            WorkerOutcome.FINALIZATION_FAILED,
            task_id,
            TaskState.RUNNING,
            task=self._tasks.get(task_id),
            error=report,
        )


__all__ = [
    "HandlerRegistry",
    "TaskExecutionContext",
    "TaskHandler",
    "TaskTimeoutError",
    "Worker",
    "WorkerError",
    "WorkerOutcome",
    "WorkerOwnershipLost",
    "WorkerRunResult",
]
