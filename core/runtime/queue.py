"""Persistent Queue MVP for FRAMEFLOW V5.

The queue decides which persisted Task is eligible next.  It never executes a
Task, invokes a provider, acquires a resource lock, or runs a worker loop.
"""

from __future__ import annotations

from typing import Any

from .state_store import TaskState, TaskStore


MAX_QUEUE_RETRIES = 3


class QueueError(RuntimeError):
    """Base error for bounded Queue operations."""


class TaskNotEnqueueable(QueueError):
    """The Task is not in a state that can be placed on the queue."""


class TaskNotCancellable(QueueError):
    """The Task is no longer pending and cannot be cancelled by T06."""


class RetryNotEligible(QueueError):
    """The Task is not eligible for another bounded queue placement."""


class TaskQueue:
    """Small persistent Queue facade built on the canonical TaskStore."""

    def __init__(self, task_store: TaskStore) -> None:
        self._tasks = task_store

    @staticmethod
    def _queue_order(task: dict[str, Any]) -> tuple[int, str, str]:
        return (
            -int(task["priority"]),
            str(task["created_at"] or ""),
            str(task["id"]),
        )

    def enqueue(self, task_id: str) -> dict[str, Any]:
        """Place a CREATED Task in QUEUED state without changing attempts."""

        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"task not found: {task_id}")
        current = TaskState(task["status"])
        if current is TaskState.QUEUED:
            return task
        if current is not TaskState.CREATED:
            raise TaskNotEnqueueable(
                f"Task {task_id} is {current.value}; only CREATED Tasks may be enqueued"
            )
        queued = self._tasks.set_status_if(
            task_id,
            expected_statuses=(TaskState.CREATED,),
            status=TaskState.QUEUED,
        )
        if queued is None:
            latest = self._tasks.get(task_id)
            if latest is not None and latest["status"] == TaskState.QUEUED.value:
                return latest
            raise TaskNotEnqueueable(f"Task {task_id} changed before enqueue")
        return queued

    def peek(self) -> dict[str, Any] | None:
        """Return the next eligible Task without modifying its row."""

        queued = self._tasks.list(status=TaskState.QUEUED)
        return min(queued, key=self._queue_order) if queued else None

    def count_queued(self) -> int:
        """Return the persisted number of queued Tasks."""

        return len(self._tasks.list(status=TaskState.QUEUED))

    def claim_next(self) -> dict[str, Any] | None:
        """Atomically claim the next queued Task as RUNNING."""

        return self._tasks.claim_next_queued()

    def cancel(self, task_id: str) -> dict[str, Any]:
        """Cancel a CREATED or QUEUED Task; RUNNING cancellation is T07+."""

        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"task not found: {task_id}")
        current = TaskState(task["status"])
        if current is TaskState.CANCELLED:
            return task
        if current not in {TaskState.CREATED, TaskState.QUEUED}:
            raise TaskNotCancellable(
                f"Task {task_id} is {current.value}; T06 cancels only pending Tasks"
            )
        cancelled = self._tasks.set_status_if(
            task_id,
            expected_statuses=(TaskState.CREATED, TaskState.QUEUED),
            status=TaskState.CANCELLED,
        )
        if cancelled is None:
            latest = self._tasks.get(task_id)
            if latest is not None and latest["status"] == TaskState.CANCELLED.value:
                return latest
            raise TaskNotCancellable(f"Task {task_id} changed before cancellation")
        return cancelled

    def retry(self, task_id: str) -> dict[str, Any]:
        """Requeue FAILED/INTERRUPTED work while ``attempt < 3``."""

        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"task not found: {task_id}")
        current = TaskState(task["status"])
        if current not in {TaskState.FAILED, TaskState.INTERRUPTED}:
            raise RetryNotEligible(
                f"Task {task_id} is {current.value}; only FAILED or INTERRUPTED Tasks may retry"
            )
        attempt = int(task["attempt"])
        max_attempts = int(task["max_attempts"])
        if attempt >= min(max_attempts, MAX_QUEUE_RETRIES):
            raise RetryNotEligible(
                f"Task {task_id} reached retry limit: attempt={attempt}, max_attempts={max_attempts}"
            )
        queued = self._tasks.requeue_retryable(task_id, max_retries=MAX_QUEUE_RETRIES)
        if queued is None:
            raise RetryNotEligible(f"Task {task_id} is no longer retry-eligible")
        return queued


__all__ = [
    "MAX_QUEUE_RETRIES",
    "QueueError",
    "RetryNotEligible",
    "TaskNotCancellable",
    "TaskNotEnqueueable",
    "TaskQueue",
]
