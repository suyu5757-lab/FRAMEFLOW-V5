"""Persistent TaskStore for the FRAMEFLOW V5 Runtime.

This module owns task-row persistence only.  It deliberately does not
schedule work, execute workers, acquire resource locks, submit providers, or
implement retry/event orchestration.  All database access goes through the
existing :class:`StateStore` connection and transaction boundaries.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Iterable

from sqlalchemy import insert, select, update

from core.schemas.runtime_mvp import TASK_STATUS_VALUES, metadata

from .store import StateStore


class TaskState(StrEnum):
    """The T05 Runtime TaskState contract."""

    CREATED = TASK_STATUS_VALUES[0]
    QUEUED = TASK_STATUS_VALUES[1]
    WAITING_FOR_RESOURCE = TASK_STATUS_VALUES[2]
    RUNNING = TASK_STATUS_VALUES[3]
    SUCCEEDED = TASK_STATUS_VALUES[4]
    FAILED = TASK_STATUS_VALUES[5]
    INTERRUPTED = TASK_STATUS_VALUES[6]
    CANCELLED = TASK_STATUS_VALUES[7]


_UNSET = object()
_MAX_LENGTHS = {
    "task_id": 120,
    "task_type": 64,
    "project_id": 120,
    "shot_id": 120,
    "worker": 120,
    "idempotency_key": 512,
}


def _text(value: Any, *, field: str, max_length: int, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{field} must be a non-empty string")
    if len(value) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return value


def _integer(value: Any, *, field: str, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _json_text(value: Any, *, field: str) -> str:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field} must contain valid JSON") from exc
    else:
        parsed = value
    try:
        return json.dumps(
            parsed,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be JSON serializable") from exc


def _state(value: TaskState | str) -> TaskState:
    try:
        return value if isinstance(value, TaskState) else TaskState(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(TASK_STATUS_VALUES)
        raise ValueError(f"status must be one of: {allowed}") from exc


class TaskStore:
    """Small typed persistence facade over the existing V5 ``tasks`` table."""

    def __init__(self, state_store: StateStore) -> None:
        self._state_store = state_store
        self._tasks = metadata.tables["tasks"]

    @staticmethod
    def _row(row: Any) -> dict[str, Any] | None:
        return dict(row._mapping) if row is not None else None

    def create(
        self,
        *,
        task_id: str,
        task_type: str,
        project_id: str | None,
        shot_id: str | None = None,
        status: TaskState | str = TaskState.CREATED,
        priority: int = 0,
        idempotency_key: str | None = None,
        attempt: int = 0,
        max_attempts: int = 3,
        timeout: int | None = None,
        worker: str | None = None,
        payload: Any = None,
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Create and commit one Task row, returning the persisted mapping."""

        values: dict[str, Any] = {
            "id": _text(task_id, field="task_id", max_length=_MAX_LENGTHS["task_id"]),
            "type": _text(task_type, field="task_type", max_length=_MAX_LENGTHS["task_type"]),
            # Keep the non-null project contract in the database.  Passing
            # None deliberately reaches the FK/non-null constraint for a
            # contract-level rejection test rather than being silently mapped.
            "project_id": (
                None
                if project_id is None
                else _text(project_id, field="project_id", max_length=_MAX_LENGTHS["project_id"])
            ),
            "shot_id": _text(shot_id, field="shot_id", max_length=_MAX_LENGTHS["shot_id"], required=False),
            "status": _state(status).value,
            "priority": _integer(priority, field="priority"),
            "idempotency_key": _text(
                idempotency_key,
                field="idempotency_key",
                max_length=_MAX_LENGTHS["idempotency_key"],
                required=False,
            ),
            "attempt": _integer(attempt, field="attempt"),
            "max_attempts": _integer(max_attempts, field="max_attempts"),
            "timeout": _integer(timeout, field="timeout", nullable=True),
            "worker": _text(worker, field="worker", max_length=_MAX_LENGTHS["worker"], required=False),
            "payload_json": _json_text({} if payload is None else payload, field="payload"),
        }
        if created_at is not None:
            values["created_at"] = created_at

        with self._state_store.transaction() as connection:
            connection.execute(insert(self._tasks).values(**values))
        task = self.get(task_id)
        if task is None:  # pragma: no cover - guards an impossible committed-read race
            raise RuntimeError(f"created task could not be read back: {task_id}")
        return task

    def get(self, task_id: str) -> dict[str, Any] | None:
        """Return one Task by ID, or ``None`` when it does not exist."""

        normalized_id = _text(task_id, field="task_id", max_length=_MAX_LENGTHS["task_id"])
        with self._state_store.connection() as connection:
            row = connection.execute(
                select(self._tasks).where(self._tasks.c.id == normalized_id)
            ).first()
        return self._row(row)

    def update(
        self,
        task_id: str,
        *,
        status: TaskState | str | object = _UNSET,
        worker: str | None | object = _UNSET,
        attempt: int | object = _UNSET,
        started_at: datetime | None | object = _UNSET,
        heartbeat_at: datetime | None | object = _UNSET,
        finished_at: datetime | None | object = _UNSET,
        payload: Any = _UNSET,
        result: Any = _UNSET,
        error: Any = _UNSET,
    ) -> dict[str, Any]:
        """Persist lifecycle fields and JSON execution evidence for one Task.

        This method intentionally does not validate state transitions.  T05
        persists valid states; queue, worker, retry, and orchestration policy
        belong to later runtime tasks.
        """

        normalized_id = _text(task_id, field="task_id", max_length=_MAX_LENGTHS["task_id"])
        changes: dict[str, Any] = {}
        if status is not _UNSET:
            changes["status"] = _state(status).value  # type: ignore[arg-type]
        if worker is not _UNSET:
            changes["worker"] = _text(
                worker,
                field="worker",
                max_length=_MAX_LENGTHS["worker"],
                required=False,
            )
        if attempt is not _UNSET:
            changes["attempt"] = _integer(attempt, field="attempt")
        for field, value in (
            ("started_at", started_at),
            ("heartbeat_at", heartbeat_at),
            ("finished_at", finished_at),
        ):
            if value is not _UNSET:
                if value is not None and not isinstance(value, datetime):
                    raise ValueError(f"{field} must be a datetime or None")
                changes[field] = value
        if payload is not _UNSET:
            changes["payload_json"] = _json_text({} if payload is None else payload, field="payload")
        if result is not _UNSET:
            changes["result_json"] = None if result is None else _json_text(result, field="result")
        if error is not _UNSET:
            changes["error_json"] = None if error is None else _json_text(error, field="error")

        if not changes:
            task = self.get(normalized_id)
            if task is None:
                raise KeyError(f"task not found: {normalized_id}")
            return task

        with self._state_store.transaction() as connection:
            result_proxy = connection.execute(
                update(self._tasks)
                .where(self._tasks.c.id == normalized_id)
                .values(**changes)
            )
            if result_proxy.rowcount != 1:
                raise KeyError(f"task not found: {normalized_id}")
        task = self.get(normalized_id)
        if task is None:  # pragma: no cover - guards an impossible committed-read race
            raise RuntimeError(f"updated task could not be read back: {normalized_id}")
        return task

    def list(
        self,
        *,
        status: TaskState | str | None = None,
        project_id: str | None = None,
        shot_id: str | None | object = _UNSET,
    ) -> list[dict[str, Any]]:
        """List Tasks with the minimal T05 status/project/shot filters."""

        statement = select(self._tasks)
        if status is not None:
            statement = statement.where(self._tasks.c.status == _state(status).value)
        if project_id is not None:
            statement = statement.where(
                self._tasks.c.project_id
                == _text(project_id, field="project_id", max_length=_MAX_LENGTHS["project_id"])
            )
        if shot_id is not _UNSET:
            if shot_id is None:
                statement = statement.where(self._tasks.c.shot_id.is_(None))
            else:
                statement = statement.where(
                    self._tasks.c.shot_id
                    == _text(shot_id, field="shot_id", max_length=_MAX_LENGTHS["shot_id"])
                )
        statement = statement.order_by(self._tasks.c.created_at, self._tasks.c.id)
        with self._state_store.connection() as connection:
            rows = connection.execute(statement).all()
        return [task for row in rows if (task := self._row(row)) is not None]

    def set_status_if(
        self,
        task_id: str,
        *,
        expected_statuses: Iterable[TaskState | str],
        status: TaskState | str,
    ) -> dict[str, Any] | None:
        """Conditionally persist one status transition and return its row.

        This is a small compare-and-set primitive for later runtime layers.
        It does not define a transition graph; callers provide the allowed
        current states for their own bounded operation.
        """

        normalized_id = _text(task_id, field="task_id", max_length=_MAX_LENGTHS["task_id"])
        expected = tuple(_state(value).value for value in expected_statuses)
        if not expected:
            raise ValueError("expected_statuses must not be empty")
        next_status = _state(status).value
        with self._state_store.transaction(immediate=True) as connection:
            result = connection.execute(
                update(self._tasks)
                .where(
                    self._tasks.c.id == normalized_id,
                    self._tasks.c.status.in_(expected),
                )
                .values(status=next_status)
            )
            if result.rowcount != 1:
                return None
        return self.get(normalized_id)

    def claim_next_queued(self) -> dict[str, Any] | None:
        """Atomically claim the next queued Task as ``RUNNING``.

        The write transaction is acquired before selecting the candidate, so
        competing consumers cannot both observe and claim the same row.  The
        execution attempt counter is intentionally unchanged; T07 owns the
        point at which an execution attempt begins.
        """

        with self._state_store.transaction(immediate=True) as connection:
            row = connection.execute(
                select(self._tasks)
                .where(self._tasks.c.status == TaskState.QUEUED.value)
                .order_by(
                    self._tasks.c.priority.desc(),
                    self._tasks.c.created_at.asc(),
                    self._tasks.c.id.asc(),
                )
                .limit(1)
            ).first()
            if row is None:
                return None
            task_id = str(row._mapping["id"])
            result = connection.execute(
                update(self._tasks)
                .where(
                    self._tasks.c.id == task_id,
                    self._tasks.c.status == TaskState.QUEUED.value,
                )
                .values(status=TaskState.RUNNING.value)
            )
            if result.rowcount != 1:
                return None
        return self.get(task_id)

    def requeue_retryable(
        self,
        task_id: str,
        *,
        max_retries: int = 3,
    ) -> dict[str, Any] | None:
        """Requeue a failed/interrupted Task without incrementing ``attempt``.

        ``attempt`` counts execution attempts, not queue placements.  The
        queue cap is applied in the conditional update so a retry race cannot
        pass the limit after a stale read.
        """

        normalized_id = _text(task_id, field="task_id", max_length=_MAX_LENGTHS["task_id"])
        retry_cap = _integer(max_retries, field="max_retries")
        if retry_cap is None or retry_cap < 0:
            raise ValueError("max_retries must be a non-negative integer")
        with self._state_store.transaction(immediate=True) as connection:
            result = connection.execute(
                update(self._tasks)
                .where(
                    self._tasks.c.id == normalized_id,
                    self._tasks.c.status.in_((TaskState.FAILED.value, TaskState.INTERRUPTED.value)),
                    self._tasks.c.attempt < self._tasks.c.max_attempts,
                    self._tasks.c.attempt < retry_cap,
                )
                .values(status=TaskState.QUEUED.value)
            )
            if result.rowcount != 1:
                return None
        return self.get(normalized_id)


__all__ = ["TASK_STATUS_VALUES", "TaskState", "TaskStore"]
