"""Minimal explicit-human approval boundary for T48 Runtime closure."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import insert, select, update

from core.runtime.event_log import EventLog
from core.runtime.minimal_smoke import smoke_video
from core.runtime.queue import TaskQueue
from core.runtime.state_store import StateStore, TaskStore
from core.runtime.worker import HandlerRegistry, TaskExecutionContext, Worker
from core.schemas.runtime_mvp import metadata
from frameflow.idempotency import canonical_json


TASK_EXPLICIT_APPROVE = "T48_EXPLICIT_APPROVE"


class ReviewError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class ApprovalResult:
    action: str
    task: Mapping[str, Any] | None = None
    post_ready: bool = False
    code: str | None = None


def _digest(prefix: str, value: Mapping[str, Any]) -> str:
    return f"{prefix}_{hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()[:48]}"


class ExplicitReviewService:
    """Queue a separately invoked approval; smoke alone cannot approve output."""

    def __init__(self, store: StateStore) -> None:
        self.store = store
        self.tasks = TaskStore(store)
        self.queue = TaskQueue(self.tasks)

    def post_ready(self, generation_id: str) -> bool:
        generation = self.store.get_generation(generation_id)
        if generation is None or str(generation.get("status")) != "QA_APPROVED":
            return False
        with self.store.connection() as connection:
            row = connection.execute(
                select(metadata.tables["reviews"])
                .where(metadata.tables["reviews"].c.generation_id == generation_id)
                .order_by(metadata.tables["reviews"].c.created_at.desc(), metadata.tables["reviews"].c.id.desc())
            ).mappings().first()
        if row is None or str(row.get("decision")) != "APPROVED":
            return False
        try:
            evidence = json.loads(str(row.get("qa_json") or "{}"))
        except json.JSONDecodeError:
            return False
        return bool(isinstance(evidence, Mapping) and evidence.get("smoke", {}).get("passed") is True)

    def approve(self, *, generation_id: str, result_artifact_id: str, actor: str) -> ApprovalResult:
        generation = self.store.get_generation(generation_id)
        artifact = self.store.get_artifact(result_artifact_id)
        if generation is None or artifact is None or str(artifact.get("generation_id")) != generation_id:
            return ApprovalResult("INVALID_REQUEST", code="GENERATION_RESULT_RELATION_INVALID")
        shot = self.store.get_shot(str(generation.get("shot_id")))
        if shot is None or not isinstance(actor, str) or not actor.strip():
            return ApprovalResult("INVALID_REQUEST", code="APPROVAL_INPUT_INVALID")
        smoke = smoke_video(artifact)
        if not smoke.passed:
            return ApprovalResult("INVALID_REQUEST", code="SMOKE_REQUIRED")
        payload = {"operation": "explicit_approve", "generation_id": generation_id, "result_artifact_id": result_artifact_id, "project_id": str(shot["project_id"]), "shot_id": str(shot["id"]), "actor": actor.strip(), "smoke": smoke.to_dict()}
        task_id = _digest("TASK_T48_APPROVE", payload)
        existing = self.tasks.get(task_id)
        if existing is not None:
            return ApprovalResult("TASK_QUEUED", task=existing, post_ready=self.post_ready(generation_id))
        task = self.tasks.create(task_id=task_id, task_type=TASK_EXPLICIT_APPROVE, project_id=str(shot["project_id"]), shot_id=str(shot["id"]), idempotency_key=f"review:{task_id}", payload=payload)
        return ApprovalResult("TASK_QUEUED", task=self.queue.enqueue(task_id))

    def trusted_handler_registry(self) -> HandlerRegistry:
        return HandlerRegistry({TASK_EXPLICIT_APPROVE: self._handle_approve})

    def worker(self, *, worker_id: str = "t48-review-worker") -> Worker:
        return Worker(self.tasks, queue=self.queue, handlers=self.trusted_handler_registry(), worker_id=worker_id)

    def _handle_approve(self, task: Mapping[str, Any], _context: TaskExecutionContext) -> dict[str, Any]:
        payload = json.loads(str(task.get("payload_json") or "{}"))
        expected = {"operation", "generation_id", "result_artifact_id", "project_id", "shot_id", "actor", "smoke"}
        if not isinstance(payload, Mapping) or set(payload) != expected or payload.get("operation") != "explicit_approve":
            raise ReviewError("INVALID_TASK_PAYLOAD", "explicit approval payload is invalid")
        generation = self.store.get_generation(str(payload["generation_id"]))
        artifact = self.store.get_artifact(str(payload["result_artifact_id"]))
        shot = self.store.get_shot(str(payload["shot_id"]))
        if generation is None or artifact is None or shot is None or str(generation.get("shot_id")) != str(payload["shot_id"]) or str(shot.get("project_id")) != str(payload["project_id"]) or str(artifact.get("generation_id")) != str(generation.get("id")):
            raise ReviewError("GENERATION_RESULT_RELATION_INVALID", "approval relation changed")
        smoke = smoke_video(artifact)
        if not smoke.passed:
            raise ReviewError("SMOKE_REQUIRED", "result cannot be approved before a passing smoke check")
        review_id = _digest("REV_T48", {"task_id": str(task["id"])})
        evidence = {"smoke": smoke.to_dict(), "approval": {"actor": str(payload["actor"]), "explicit": True, "task_id": str(task["id"])}, "post_ready": True}
        with self.store.transaction() as connection:
            current = connection.execute(select(metadata.tables["reviews"]).where(metadata.tables["reviews"].c.id == review_id)).mappings().first()
            if current is None:
                connection.execute(insert(metadata.tables["reviews"]).values(id=review_id, shot_id=str(shot["id"]), generation_id=str(generation["id"]), qa_json=canonical_json(evidence), decision="APPROVED"))
            elif str(current.get("generation_id")) != str(generation["id"]) or str(current.get("decision")) != "APPROVED":
                raise ReviewError("REVIEW_ID_CONFLICT", "existing review conflicts with approval task")
            connection.execute(update(metadata.tables["generations"]).where(metadata.tables["generations"].c.id == str(generation["id"])).values(status="QA_APPROVED"))
            EventLog(self.store).append_in_transaction(connection, trace_id=str(task["id"]), entity_type="GENERATION", entity_id=str(generation["id"]), event_type="T48_EXPLICIT_APPROVAL", payload={"review_id": review_id, "actor": str(payload["actor"]), "post_ready": True})
        return {"action": "APPROVED", "review_id": review_id, "generation_id": str(generation["id"]), "post_ready": True, "remote_call": False}


__all__ = ["ApprovalResult", "ExplicitReviewService", "ReviewError", "TASK_EXPLICIT_APPROVE"]
