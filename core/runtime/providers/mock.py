"""Local deterministic T48 Mock Provider.

It intentionally reuses the V5 Manual adapter's trusted T09 submission and
T26 import handlers.  Its only difference is a deterministic local external
task identity and a pre-created, isolated staging result supplied by the test
harness; it performs no network work.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .manual import ManualAction, ManualHandoff, ManualOperationResult, ManualProviderAdapter, _issue, _safe_identifier
PROVIDER_IDENTITY = "mock"


class MockProviderAdapter(ManualProviderAdapter):
    """Provider-compatible local test double with no remote side effects."""

    provider = PROVIDER_IDENTITY

    def __init__(self, *args: Any, result_source_path: Path | str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.result_source_path = Path(result_source_path).resolve(strict=False)

    def submit(self, handoff: ManualHandoff) -> ManualOperationResult:
        if not isinstance(handoff, ManualHandoff):
            raise TypeError("submit requires a ManualHandoff")
        if not handoff.submission_ready or not handoff.idempotency_key:
            return ManualOperationResult(action=ManualAction.INVALID_REQUEST, handoff=handoff, issues=handoff.issues or (_issue("PACKAGE_REQUIRED", "handoff is not submission-ready"),))
        external_task_id = f"mock-{handoff.idempotency_key[:48]}"
        return self.mark_submitted(handoff, external_task_id=external_task_id)

    def fetch(self, generation_id: str) -> ManualOperationResult:
        try:
            normalized = _safe_identifier(generation_id, field_name="generation_id")
        except Exception as exc:
            return ManualOperationResult(action=ManualAction.INVALID_REQUEST, issues=(_issue("INVALID_REQUEST", str(exc)),))
        generation = self.store.get_generation(normalized)
        if generation is None or str(generation.get("provider")) != self.provider:
            return ManualOperationResult(action=ManualAction.INVALID_REQUEST, issues=(_issue("GENERATION_RELATION_INVALID", "generation is not a mock Generation"),))
        submission = next((row for row in self.store.list("provider_submissions") if str(row.get("generation_id")) == normalized), None)
        if submission is None or submission.get("status") != "SUBMITTED":
            return ManualOperationResult(action="MOCK_RESULT_PENDING", issues=(_issue("SUBMISSION_NOT_READY", "mock submission is not ready"),))
        shot = self.store.get_shot(str(generation["shot_id"]))
        if shot is None:
            return ManualOperationResult(action=ManualAction.INVALID_REQUEST, issues=(_issue("GENERATION_RELATION_INVALID", "mock Generation Shot is missing"),))
        try:
            source = self._safe_source_path(str(shot["project_id"]), str(self.result_source_path), require_file=True)
        except Exception as exc:
            return ManualOperationResult(action="MOCK_RESULT_PENDING", issues=(_issue("MOCK_RESULT_MISSING", str(exc)),))
        return ManualOperationResult(action="MOCK_RESULT_AVAILABLE", data={"generation_id": normalized, "source_path": str(source), "external_task_id": submission.get("external_task_id"), "remote_call": False})

    def cancel(self, submission_id: str) -> ManualOperationResult:
        try:
            normalized = _safe_identifier(submission_id, field_name="submission_id")
        except Exception as exc:
            return ManualOperationResult(action=ManualAction.INVALID_REQUEST, issues=(_issue("INVALID_REQUEST", str(exc)),))
        return ManualOperationResult(action="MOCK_CANCELLATION_NOT_REQUIRED", data={"submission_id": normalized, "status_mutated": False, "remote_call": False})


__all__ = ["MockProviderAdapter", "PROVIDER_IDENTITY"]
