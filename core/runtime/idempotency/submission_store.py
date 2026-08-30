"""Persistent Provider Submission intent and election store for T09."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection

from core.schemas.runtime_mvp import metadata

from ..state_store import StateStore


class SubmissionStatus(StrEnum):
    PREPARED = "PREPARED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    UNKNOWN = "UNKNOWN"
    FAILED = "FAILED"


class SubmissionStoreError(RuntimeError):
    """Base error for persisted Provider Submission contract failures."""


class GenerationNotFoundError(SubmissionStoreError):
    """Raised when a submission does not reference a valid Generation."""


class SubmissionContractError(SubmissionStoreError):
    """Raised when Generation/Shot/Project/Provider inputs do not match."""


class SubmissionConflictError(SubmissionStoreError):
    """Raised when one logical identity is paired with a different request."""


class SubmissionTransitionError(SubmissionStoreError):
    """Raised when a persisted submission cannot perform the requested action."""


@dataclass(frozen=True)
class SubmissionReservation:
    """The result of the atomic intent insert/election."""

    is_owner: bool
    submission: dict[str, Any]


_SUBMISSION_TABLE = metadata.tables["provider_submissions"]
_GENERATION_TABLE = metadata.tables["generations"]
_SHOT_TABLE = metadata.tables["shots"]


def _text(value: Any, *, field: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _row(row: Any) -> dict[str, Any] | None:
    return dict(row._mapping) if row is not None else None


def _utc_naive(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("clock must return a datetime")
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


class ProviderSubmissionStore:
    """Small typed persistence facade over the frozen submission table."""

    def __init__(
        self,
        state_store: StateStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._state_store = state_store
        self._clock = clock or (lambda: datetime.now(UTC))

    def prepare_intent(
        self,
        *,
        generation_id: str,
        project_id: str,
        shot_id: str,
        provider: str,
        idempotency_key: str,
        request_hash: str,
    ) -> SubmissionReservation:
        """Atomically validate the Generation and elect one submit owner."""

        generation_id = _text(generation_id, field="generation_id", max_length=120)
        project_id = _text(project_id, field="project_id", max_length=120)
        shot_id = _text(shot_id, field="shot_id", max_length=120)
        provider = _text(provider, field="provider", max_length=64)
        idempotency_key = _text(idempotency_key, field="idempotency_key", max_length=1024)
        request_hash = _text(request_hash, field="request_hash", max_length=128)

        with self._state_store.transaction(immediate=True) as connection:
            generation = connection.execute(
                select(
                    _GENERATION_TABLE.c.id,
                    _GENERATION_TABLE.c.shot_id,
                    _GENERATION_TABLE.c.provider,
                    _SHOT_TABLE.c.project_id,
                )
                .select_from(
                    _GENERATION_TABLE.join(
                        _SHOT_TABLE,
                        _SHOT_TABLE.c.id == _GENERATION_TABLE.c.shot_id,
                    )
                )
                .where(_GENERATION_TABLE.c.id == generation_id)
            ).first()
            if generation is None:
                raise GenerationNotFoundError(f"generation not found: {generation_id}")
            generation_values = generation._mapping
            if (
                generation_values["shot_id"] != shot_id
                or generation_values["project_id"] != project_id
                or generation_values["provider"] != provider
            ):
                raise SubmissionContractError(
                    "generation does not match project, shot, and provider inputs"
                )

            existing = _row(
                connection.execute(
                    select(_SUBMISSION_TABLE).where(
                        _SUBMISSION_TABLE.c.idempotency_key == idempotency_key
                    )
                ).first()
            )
            if existing is not None:
                if (
                    existing["request_hash"] != request_hash
                    or existing["provider"] != provider
                ):
                    raise SubmissionConflictError(
                        "same idempotency_key has a different request_hash or provider"
                    )
                return SubmissionReservation(is_owner=False, submission=existing)

            values = {
                "id": f"PSUB_{uuid4().hex}",
                "generation_id": generation_id,
                "provider": provider,
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
                "external_task_id": None,
                "attempt": 0,
                "status": SubmissionStatus.PREPARED.value,
                "submitted_at": None,
            }
            connection.execute(insert(_SUBMISSION_TABLE).values(**values))
            created = _row(
                connection.execute(
                    select(_SUBMISSION_TABLE).where(
                        _SUBMISSION_TABLE.c.id == values["id"]
                    )
                ).first()
            )
            if created is None:  # pragma: no cover - committed-read guard
                raise RuntimeError("provider submission intent could not be read back")
            return SubmissionReservation(is_owner=True, submission=created)

    def get(self, submission_id: str) -> dict[str, Any] | None:
        submission_id = _text(submission_id, field="submission_id", max_length=120)
        with self._state_store.connection() as connection:
            return self._get_in_connection(connection, submission_id)

    def get_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        idempotency_key = _text(idempotency_key, field="idempotency_key", max_length=1024)
        with self._state_store.connection() as connection:
            return _row(
                connection.execute(
                    select(_SUBMISSION_TABLE).where(
                        _SUBMISSION_TABLE.c.idempotency_key == idempotency_key
                    )
                ).first()
            )

    def mark_submitting(self, submission_id: str) -> dict[str, Any] | None:
        """Move one elected intent to SUBMITTING and increment provider attempt once."""

        submission_id = _text(submission_id, field="submission_id", max_length=120)
        with self._state_store.transaction(immediate=True) as connection:
            result = connection.execute(
                update(_SUBMISSION_TABLE)
                .where(
                    _SUBMISSION_TABLE.c.id == submission_id,
                    _SUBMISSION_TABLE.c.status == SubmissionStatus.PREPARED.value,
                )
                .values(
                    status=SubmissionStatus.SUBMITTING.value,
                    attempt=_SUBMISSION_TABLE.c.attempt + 1,
                )
            )
            if result.rowcount != 1:
                return None
        return self.get(submission_id)

    def mark_unknown(self, submission_id: str) -> dict[str, Any]:
        """Record an ambiguous external outcome without assuming failure."""

        submission_id = _text(submission_id, field="submission_id", max_length=120)
        with self._state_store.transaction(immediate=True) as connection:
            current = self._get_in_connection(connection, submission_id)
            if current is None:
                raise SubmissionTransitionError(f"submission not found: {submission_id}")
            status = SubmissionStatus(current["status"])
            if status in {SubmissionStatus.UNKNOWN, SubmissionStatus.SUBMITTED}:
                return current
            if status is not SubmissionStatus.SUBMITTING:
                raise SubmissionTransitionError(
                    f"cannot mark {status.value} submission unknown: {submission_id}"
                )
            connection.execute(
                update(_SUBMISSION_TABLE)
                .where(_SUBMISSION_TABLE.c.id == submission_id)
                .values(status=SubmissionStatus.UNKNOWN.value)
            )
            return self._get_in_connection(connection, submission_id)

    def mark_failed(self, submission_id: str) -> dict[str, Any]:
        """Record a known pre-completion failure without inventing an external ID."""

        submission_id = _text(submission_id, field="submission_id", max_length=120)
        with self._state_store.transaction(immediate=True) as connection:
            current = self._get_in_connection(connection, submission_id)
            if current is None:
                raise SubmissionTransitionError(f"submission not found: {submission_id}")
            status = SubmissionStatus(current["status"])
            if status is SubmissionStatus.FAILED:
                return current
            if status is SubmissionStatus.SUBMITTED:
                return current
            connection.execute(
                update(_SUBMISSION_TABLE)
                .where(_SUBMISSION_TABLE.c.id == submission_id)
                .values(status=SubmissionStatus.FAILED.value)
            )
            return self._get_in_connection(connection, submission_id)

    def bind_external_task(
        self,
        submission_id: str,
        *,
        external_task_id: str,
    ) -> dict[str, Any]:
        """Bind a real provider ID and finalize the persisted submission."""

        submission_id = _text(submission_id, field="submission_id", max_length=120)
        external_task_id = _text(
            external_task_id,
            field="external_task_id",
            max_length=255,
        )
        submitted_at = _utc_naive(self._clock())
        with self._state_store.transaction(immediate=True) as connection:
            current = self._get_in_connection(connection, submission_id)
            if current is None:
                raise SubmissionTransitionError(f"submission not found: {submission_id}")
            status = SubmissionStatus(current["status"])
            if status is SubmissionStatus.SUBMITTED:
                if current["external_task_id"] == external_task_id:
                    return current
                raise SubmissionConflictError(
                    "submitted idempotency record is already bound to another external_task_id"
                )
            if status not in {
                SubmissionStatus.PREPARED,
                SubmissionStatus.SUBMITTING,
                SubmissionStatus.UNKNOWN,
            }:
                raise SubmissionTransitionError(
                    f"cannot bind external task for {status.value} submission: {submission_id}"
                )
            connection.execute(
                update(_SUBMISSION_TABLE)
                .where(_SUBMISSION_TABLE.c.id == submission_id)
                .values(
                    external_task_id=external_task_id,
                    status=SubmissionStatus.SUBMITTED.value,
                    submitted_at=submitted_at,
                )
            )
            return self._get_in_connection(connection, submission_id)

    @staticmethod
    def _get_in_connection(connection: Connection, submission_id: str) -> dict[str, Any] | None:
        return _row(
            connection.execute(
                select(_SUBMISSION_TABLE).where(_SUBMISSION_TABLE.c.id == submission_id)
            ).first()
        )


__all__ = [
    "GenerationNotFoundError",
    "ProviderSubmissionStore",
    "SubmissionConflictError",
    "SubmissionContractError",
    "SubmissionReservation",
    "SubmissionStatus",
    "SubmissionStoreError",
    "SubmissionTransitionError",
]
