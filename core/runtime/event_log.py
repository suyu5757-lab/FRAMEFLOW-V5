"""Persistent Runtime EventLog over the frozen ``events`` table."""

from __future__ import annotations

import re
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4

from sqlalchemy import insert, select
from sqlalchemy.engine import Connection

from frameflow.idempotency import canonical_json

from .state_store import StateStore
from core.schemas.runtime_mvp import metadata


class EventLogError(RuntimeError):
    """Base error for EventLog contract failures."""


class InvalidEventError(EventLogError):
    """Raised when an event field or payload cannot be persisted safely."""


_EVENT_TABLE = metadata.tables["events"]
_SENSITIVE_KEY = re.compile(r"(?i)^(api[_ -]?key|token|password|secret|credential|authorization)$")


def _text(value: Any, *, field: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidEventError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > max_length:
        raise InvalidEventError(f"{field} exceeds {max_length} characters")
    return normalized


def _utc_naive(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise InvalidEventError("created_at must be a datetime")
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: "[REDACTED]" if isinstance(key, str) and _SENSITIVE_KEY.fullmatch(key) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    return value


def _payload_text(value: Any) -> str:
    try:
        return canonical_json(_redact({} if value is None else value))
    except (TypeError, ValueError) as exc:
        raise InvalidEventError("payload must be JSON serializable") from exc


def _row(row: Any) -> dict[str, Any] | None:
    return dict(row._mapping) if row is not None else None


class EventLog:
    """Small append/query EventLog using the canonical StateStore boundary."""

    def __init__(
        self,
        state_store: StateStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._state_store = state_store
        self._clock = clock or (lambda: datetime.now(UTC))

    def append(
        self,
        *,
        trace_id: str | None = None,
        entity_type: str,
        entity_id: str,
        event_type: str,
        payload: Any = None,
        event_id: str | None = None,
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Append one event in its own short committed transaction."""

        with self._state_store.transaction() as connection:
            return self.append_in_transaction(
                connection,
                trace_id=trace_id,
                entity_type=entity_type,
                entity_id=entity_id,
                event_type=event_type,
                payload=payload,
                event_id=event_id,
                created_at=created_at,
            )

    def append_in_transaction(
        self,
        connection: Connection,
        *,
        trace_id: str | None = None,
        entity_type: str,
        entity_id: str,
        event_type: str,
        payload: Any = None,
        event_id: str | None = None,
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Insert an event into a caller-owned transaction.

        Callers can place a domain mutation and this event insert in the same
        StateStore transaction; EventLog itself never commits this method.
        """

        values = {
            "id": _text(event_id or f"EVT_{uuid4().hex}", field="event_id", max_length=120),
            "trace_id": _text(trace_id or f"TRACE_{uuid4().hex}", field="trace_id", max_length=120),
            "entity_type": _text(entity_type, field="entity_type", max_length=64),
            "entity_id": _text(entity_id, field="entity_id", max_length=120),
            "event_type": _text(event_type, field="event_type", max_length=120),
            "payload": _payload_text(payload),
            "created_at": _utc_naive(created_at or self._clock()),
        }
        connection.execute(insert(_EVENT_TABLE).values(**values))
        created = _row(
            connection.execute(
                select(_EVENT_TABLE).where(_EVENT_TABLE.c.id == values["id"])
            ).first()
        )
        if created is None:  # pragma: no cover - transaction-local read guard
            raise EventLogError(f"event could not be read back: {values['id']}")
        return created

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        """Expose the canonical short transaction for companion event writes."""

        with self._state_store.transaction() as connection:
            yield connection

    def get(self, event_id: str) -> dict[str, Any] | None:
        event_id = _text(event_id, field="event_id", max_length=120)
        with self._state_store.connection() as connection:
            return _row(
                connection.execute(
                    select(_EVENT_TABLE).where(_EVENT_TABLE.c.id == event_id)
                ).first()
            )

    def list(
        self,
        *,
        trace_id: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Read events in deterministic chronological order with filters."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise InvalidEventError("limit must be an integer from 1 to 1000")
        statement = select(_EVENT_TABLE)
        for column, value, field, max_length in (
            (_EVENT_TABLE.c.trace_id, trace_id, "trace_id", 120),
            (_EVENT_TABLE.c.entity_type, entity_type, "entity_type", 64),
            (_EVENT_TABLE.c.entity_id, entity_id, "entity_id", 120),
            (_EVENT_TABLE.c.event_type, event_type, "event_type", 120),
        ):
            if value is not None:
                statement = statement.where(column == _text(value, field=field, max_length=max_length))
        statement = statement.order_by(_EVENT_TABLE.c.created_at.asc(), _EVENT_TABLE.c.id.asc()).limit(limit)
        with self._state_store.connection() as connection:
            rows = connection.execute(statement).all()
        return [event for raw_row in rows if (event := _row(raw_row)) is not None]

    def by_trace(self, trace_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.list(trace_id=trace_id, limit=limit)

    def for_entity(
        self,
        entity_type: str,
        entity_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.list(entity_type=entity_type, entity_id=entity_id, limit=limit)


__all__ = ["EventLog", "EventLogError", "InvalidEventError"]
