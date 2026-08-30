"""Persistent ResourceLockManager for the FRAMEFLOW V5 Runtime.

This module implements the T08 lock lease boundary over the existing
``resource_locks`` table. SQLite is the source of truth; Python collections
only hold values read inside a short transaction. Undefined future matrix
pairs fail closed until Architecture decides them.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Callable

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection

from core.schemas.runtime_mvp import metadata

from ..state_store import StateStore


LEASE_TIMEOUT_SECONDS = 300
HEARTBEAT_INTERVAL_SECONDS = 30
RESOURCE_IDS = (
    "PHOTOSHOP",
    "AFTER_EFFECTS",
    "RESOLVE",
    "COMFY_GPU",
)
MATRIX_SOURCE = (
    "ADR-008 — Resource Locks; FRAMEFLOW_V5_3_2_SCOPE.md; "
    "T08 approved architecture clarification"
)


class ResourceId(StrEnum):
    PHOTOSHOP = "PHOTOSHOP"
    AFTER_EFFECTS = "AFTER_EFFECTS"
    RESOLVE = "RESOLVE"
    COMFY_GPU = "COMFY_GPU"


class LockStatus(StrEnum):
    HELD = "HELD"
    RELEASED = "RELEASED"


class Compatibility(StrEnum):
    ALLOW = "ALLOW"
    CONFLICT = "CONFLICT"
    UNDEFINED = "UNDEFINED"


class ResourceLockError(RuntimeError):
    """Base error for bounded ResourceLockManager operations."""


class InvalidResourceError(ResourceLockError):
    """Raised when a caller supplies a resource outside the frozen set."""


class OwnerTaskNotFoundError(ResourceLockError):
    """Raised when a lock owner is not a persisted Runtime Task."""


class ResourceBusyError(ResourceLockError):
    """Raised when an active owner or frozen conflict blocks acquisition."""


class ResourceCompatibilityUndefined(ResourceLockError):
    """Raised when Architecture has not frozen a required resource pair."""


class LockNotFoundError(ResourceLockError):
    """Raised when a heartbeat or release has no persisted lock row."""


class NotLockOwnerError(ResourceLockError):
    """Raised when a non-owner attempts to mutate a lock."""


class LeaseExpiredError(ResourceLockError):
    """Raised when the owner attempts to mutate an expired lease."""


_CONFLICT_PAIRS = frozenset(
    {
        frozenset((ResourceId.PHOTOSHOP, ResourceId.AFTER_EFFECTS)),
        frozenset((ResourceId.PHOTOSHOP, ResourceId.RESOLVE)),
        frozenset((ResourceId.AFTER_EFFECTS, ResourceId.RESOLVE)),
        frozenset((ResourceId.COMFY_GPU, ResourceId.AFTER_EFFECTS)),
        frozenset((ResourceId.COMFY_GPU, ResourceId.RESOLVE)),
    }
)
_ALLOW_PAIRS = frozenset(
    {
        frozenset((ResourceId.COMFY_GPU, ResourceId.PHOTOSHOP)),
    }
)
_LOCK_TABLE = metadata.tables["resource_locks"]
_TASK_TABLE = metadata.tables["tasks"]


def _normalize_resource(resource_id: ResourceId | str) -> ResourceId:
    try:
        return resource_id if isinstance(resource_id, ResourceId) else ResourceId(resource_id)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(RESOURCE_IDS)
        raise InvalidResourceError(
            f"resource_id must be one of: {allowed}; received {resource_id!r}"
        ) from exc


def _normalize_task_id(owner_task_id: str) -> str:
    if not isinstance(owner_task_id, str) or not owner_task_id.strip():
        raise OwnerTaskNotFoundError("owner_task_id must be a non-empty string")
    if len(owner_task_id) > 120:
        raise OwnerTaskNotFoundError("owner_task_id exceeds 120 characters")
    return owner_task_id


def _utc_naive(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("clock must return a datetime")
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _row(row: Any) -> dict[str, Any] | None:
    return dict(row._mapping) if row is not None else None


def _pair_compatibility(
    requested: ResourceId,
    active_resources: Iterable[ResourceId | str],
) -> Compatibility:
    undefined = False
    for active_value in active_resources:
        try:
            active = _normalize_resource(active_value)
        except InvalidResourceError:
            return Compatibility.UNDEFINED
        if active == requested:
            return Compatibility.CONFLICT
        pair = frozenset((requested, active))
        if pair in _CONFLICT_PAIRS:
            return Compatibility.CONFLICT
        if pair in _ALLOW_PAIRS:
            continue
        undefined = True
    return Compatibility.UNDEFINED if undefined else Compatibility.ALLOW


class ResourceLockManager:
    """Persistent four-resource lease manager with fail-closed matrix rules."""

    def __init__(
        self,
        state_store: StateStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._state_store = state_store
        self._clock = clock or (lambda: datetime.now(UTC))

    def acquire(
        self,
        resource_id: ResourceId | str,
        owner_task_id: str,
    ) -> dict[str, Any]:
        """Acquire one resource atomically for an existing Runtime Task."""

        resource = _normalize_resource(resource_id)
        owner = _normalize_task_id(owner_task_id)
        now = _utc_naive(self._clock())
        with self._state_store.transaction(immediate=True) as connection:
            if connection.execute(
                select(_TASK_TABLE.c.id).where(_TASK_TABLE.c.id == owner)
            ).first() is None:
                raise OwnerTaskNotFoundError(f"owner task not found: {owner}")

            rows = connection.execute(select(_LOCK_TABLE)).all()
            current_row: dict[str, Any] | None = None
            active_rows: list[dict[str, Any]] = []
            for raw_row in rows:
                lock = _row(raw_row)
                if lock is None:
                    continue
                if str(lock["resource_id"]) == resource.value:
                    current_row = lock
                if lock["status"] == LockStatus.HELD.value and not self._is_expired(lock, now):
                    active_rows.append(lock)

            if current_row is not None and current_row in active_rows:
                if current_row["owner_task_id"] == owner:
                    return current_row
                raise ResourceBusyError(
                    f"resource {resource.value} is held by {current_row['owner_task_id']}"
                )

            compatibility = _pair_compatibility(
                resource,
                (str(lock["resource_id"]) for lock in active_rows),
            )
            if compatibility is Compatibility.CONFLICT:
                blockers = ", ".join(sorted(str(lock["resource_id"]) for lock in active_rows))
                raise ResourceBusyError(
                    f"resource {resource.value} conflicts with active resources: {blockers}"
                )
            if compatibility is Compatibility.UNDEFINED:
                blockers = ", ".join(sorted(str(lock["resource_id"]) for lock in active_rows))
                raise ResourceCompatibilityUndefined(
                    f"compatibility is not frozen for {resource.value} with: {blockers}; "
                    f"source={MATRIX_SOURCE}; ARCHITECTURE_DECISION_REQUIRED"
                )

            values = {
                "resource_id": resource.value,
                "owner_task_id": owner,
                "acquired_at": now,
                "heartbeat_at": now,
                "lease_timeout": LEASE_TIMEOUT_SECONDS,
                "status": LockStatus.HELD.value,
            }
            if current_row is None:
                connection.execute(insert(_LOCK_TABLE).values(**values))
            else:
                connection.execute(
                    update(_LOCK_TABLE)
                    .where(_LOCK_TABLE.c.resource_id == resource.value)
                    .values(**values)
                )
            return self._get_in_connection(connection, resource.value)

    def heartbeat(
        self,
        resource_id: ResourceId | str,
        owner_task_id: str,
    ) -> dict[str, Any]:
        """Renew a lease only when the caller is its current live owner."""

        resource = _normalize_resource(resource_id)
        owner = _normalize_task_id(owner_task_id)
        now = _utc_naive(self._clock())
        with self._state_store.transaction(immediate=True) as connection:
            lock = self._get_in_connection(connection, resource.value)
            self._assert_owner_can_mutate(lock, resource, owner, now)
            updated = connection.execute(
                update(_LOCK_TABLE)
                .where(
                    _LOCK_TABLE.c.resource_id == resource.value,
                    _LOCK_TABLE.c.owner_task_id == owner,
                    _LOCK_TABLE.c.status == LockStatus.HELD.value,
                )
                .values(heartbeat_at=now)
            )
            if updated.rowcount != 1:
                raise NotLockOwnerError(f"lock ownership changed: {resource.value}")
            return self._get_in_connection(connection, resource.value)

    def release(
        self,
        resource_id: ResourceId | str,
        owner_task_id: str,
    ) -> dict[str, Any]:
        """Mark a live lease released only when called by its owner."""

        resource = _normalize_resource(resource_id)
        owner = _normalize_task_id(owner_task_id)
        now = _utc_naive(self._clock())
        with self._state_store.transaction(immediate=True) as connection:
            lock = self._get_in_connection(connection, resource.value)
            self._assert_owner_can_mutate(lock, resource, owner, now)
            updated = connection.execute(
                update(_LOCK_TABLE)
                .where(
                    _LOCK_TABLE.c.resource_id == resource.value,
                    _LOCK_TABLE.c.owner_task_id == owner,
                    _LOCK_TABLE.c.status == LockStatus.HELD.value,
                )
                .values(status=LockStatus.RELEASED.value)
            )
            if updated.rowcount != 1:
                raise NotLockOwnerError(f"lock ownership changed: {resource.value}")
            return self._get_in_connection(connection, resource.value)

    def get(self, resource_id: ResourceId | str) -> dict[str, Any] | None:
        """Return the persisted row for one frozen resource."""

        resource = _normalize_resource(resource_id)
        with self._state_store.connection() as connection:
            return self._get_in_connection(connection, resource.value)

    def list_active(self) -> list[dict[str, Any]]:
        """Return non-expired ``HELD`` rows without mutating stale rows."""

        now = _utc_naive(self._clock())
        with self._state_store.connection() as connection:
            rows = connection.execute(
                select(_LOCK_TABLE)
                .where(_LOCK_TABLE.c.status == LockStatus.HELD.value)
                .order_by(_LOCK_TABLE.c.resource_id)
            ).all()
        return [
            lock
            for raw_row in rows
            if (lock := _row(raw_row)) is not None and not self._is_expired(lock, now)
        ]

    def inspect_expired(self) -> list[dict[str, Any]]:
        """Return expired held rows without task recovery or automatic mutation."""

        now = _utc_naive(self._clock())
        with self._state_store.connection() as connection:
            rows = connection.execute(
                select(_LOCK_TABLE)
                .where(_LOCK_TABLE.c.status == LockStatus.HELD.value)
                .order_by(_LOCK_TABLE.c.resource_id)
            ).all()
        return [
            lock
            for raw_row in rows
            if (lock := _row(raw_row)) is not None and self._is_expired(lock, now)
        ]

    def check_compatibility(self, resource_id: ResourceId | str) -> Compatibility:
        """Check one requested resource against current active leases."""

        resource = _normalize_resource(resource_id)
        active = self.list_active()
        return _pair_compatibility(
            resource,
            (str(lock["resource_id"]) for lock in active),
        )

    def is_available(self, resource_id: ResourceId | str) -> bool:
        """Return true only when acquisition is currently explicitly allowed."""

        return self.check_compatibility(resource_id) is Compatibility.ALLOW

    @staticmethod
    def _get_in_connection(connection: Connection, resource_id: str) -> dict[str, Any] | None:
        return _row(
            connection.execute(
                select(_LOCK_TABLE).where(_LOCK_TABLE.c.resource_id == resource_id)
            ).first()
        )

    @staticmethod
    def _is_expired(lock: dict[str, Any], now: datetime) -> bool:
        heartbeat = lock["heartbeat_at"]
        if isinstance(heartbeat, str):
            heartbeat = datetime.fromisoformat(heartbeat)
        if not isinstance(heartbeat, datetime):
            raise ResourceLockError("resource lock heartbeat_at is not a datetime")
        timeout = int(lock.get("lease_timeout") or LEASE_TIMEOUT_SECONDS)
        return now >= heartbeat + timedelta(seconds=timeout)

    @classmethod
    def _assert_owner_can_mutate(
        cls,
        lock: dict[str, Any] | None,
        resource: ResourceId,
        owner: str,
        now: datetime,
    ) -> None:
        if lock is None:
            raise LockNotFoundError(f"resource lock not found: {resource.value}")
        if lock["status"] != LockStatus.HELD.value:
            raise LockNotFoundError(f"resource lock is not held: {resource.value}")
        if lock["owner_task_id"] != owner:
            raise NotLockOwnerError(
                f"{owner} does not own {resource.value}; current owner={lock['owner_task_id']}"
            )
        if cls._is_expired(lock, now):
            raise LeaseExpiredError(f"resource lock lease expired: {resource.value}")


__all__ = [
    "Compatibility",
    "HEARTBEAT_INTERVAL_SECONDS",
    "LEASE_TIMEOUT_SECONDS",
    "LockNotFoundError",
    "LockStatus",
    "LeaseExpiredError",
    "InvalidResourceError",
    "MATRIX_SOURCE",
    "NotLockOwnerError",
    "OwnerTaskNotFoundError",
    "RESOURCE_IDS",
    "ResourceCompatibilityUndefined",
    "ResourceId",
    "ResourceBusyError",
    "ResourceLockError",
    "ResourceLockManager",
]
