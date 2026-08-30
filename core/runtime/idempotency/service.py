"""Persist-before-side-effect Provider Submit idempotency service for T09."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from .key import idempotency_key, provider_config_hash, request_hash
from .submission_store import (
    ProviderSubmissionStore,
    SubmissionStatus,
)


class ProviderSubmitter(Protocol):
    """Minimal test/provider boundary; no adapter lifecycle is defined here."""

    def submit(self, request_payload: Mapping[str, Any]) -> str:
        ...


class ProviderSubmitTimeout(TimeoutError):
    """The provider response timed out after an outcome became ambiguous."""

    def __init__(self, message: str = "provider submit response timed out") -> None:
        super().__init__(message)


class SubmitAction(StrEnum):
    SUBMITTED = "SUBMITTED"
    REUSED = "REUSED"
    RECONCILED = "RECONCILED"
    IN_PROGRESS = "IN_PROGRESS"
    NEEDS_RECONCILE = "NEEDS_RECONCILE"
    FAILED = "FAILED"


@dataclass(frozen=True)
class SubmitResult:
    """Outcome of one logical Provider Submit request."""

    action: SubmitAction
    submission: dict[str, Any]
    idempotency_key: str
    request_hash: str


def _submit_callable(submitter: ProviderSubmitter | Callable[[Mapping[str, Any]], str]):
    method = getattr(submitter, "submit", None)
    if callable(method):
        return method
    if callable(submitter):
        return submitter
    raise TypeError("submitter must expose submit() or be callable")


def _reconcile_callable(
    submitter: ProviderSubmitter | Callable[[Mapping[str, Any]], str],
    reconcile: Callable[[Mapping[str, Any], Mapping[str, Any]], str | None] | None,
):
    if reconcile is not None:
        return reconcile
    method = getattr(submitter, "reconcile", None)
    return method if callable(method) else None


class ProviderIdempotencyService:
    """Small orchestration layer for intent, election, submit, and reconcile."""

    def __init__(self, submissions: ProviderSubmissionStore) -> None:
        self._submissions = submissions

    def submit(
        self,
        *,
        generation_id: str,
        project_id: str,
        shot_id: str,
        package_version: str,
        shot_spec_version: str,
        provider: str,
        provider_config: Any,
        request_payload: Mapping[str, Any],
        submitter: ProviderSubmitter | Callable[[Mapping[str, Any]], str],
        reconcile: Callable[[Mapping[str, Any], Mapping[str, Any]], str | None] | None = None,
    ) -> SubmitResult:
        """Submit at most once for one logical key, reconciling ambiguity first."""

        config_hash = provider_config_hash(provider_config)
        logical_key = idempotency_key(
            project_id=project_id,
            shot_id=shot_id,
            package_version=package_version,
            shot_spec_version=shot_spec_version,
            provider=provider,
            provider_config_hash=config_hash,
        )
        actual_request_hash = request_hash(request_payload)
        reservation = self._submissions.prepare_intent(
            generation_id=generation_id,
            project_id=project_id,
            shot_id=shot_id,
            provider=provider,
            idempotency_key=logical_key,
            request_hash=actual_request_hash,
        )
        if not reservation.is_owner:
            return self._existing_result(
                reservation.submission,
                logical_key,
                actual_request_hash,
                request_payload,
                submitter,
                reconcile,
            )

        submitting = self._submissions.mark_submitting(reservation.submission["id"])
        if submitting is None:
            existing = self._submissions.get(reservation.submission["id"])
            if existing is None:  # pragma: no cover - committed row guard
                raise RuntimeError("provider submission election row disappeared")
            return self._existing_result(
                existing,
                logical_key,
                actual_request_hash,
                request_payload,
                submitter,
                reconcile,
            )

        try:
            external_task_id = _submit_callable(submitter)(request_payload)
        except ProviderSubmitTimeout:
            unknown = self._submissions.mark_unknown(submitting["id"])
            return self._reconcile_or_wait(
                unknown,
                logical_key,
                actual_request_hash,
                request_payload,
                submitter,
                reconcile,
            )
        except Exception:
            failed = self._submissions.mark_failed(submitting["id"])
            return SubmitResult(
                SubmitAction.FAILED,
                failed,
                logical_key,
                actual_request_hash,
            )

        if not isinstance(external_task_id, str) or not external_task_id.strip():
            unknown = self._submissions.mark_unknown(submitting["id"])
            return self._reconcile_or_wait(
                unknown,
                logical_key,
                actual_request_hash,
                request_payload,
                submitter,
                reconcile,
            )

        bound = self._submissions.bind_external_task(
            submitting["id"],
            external_task_id=external_task_id,
        )
        return SubmitResult(
            SubmitAction.SUBMITTED,
            bound,
            logical_key,
            actual_request_hash,
        )

    def _existing_result(
        self,
        submission: dict[str, Any],
        logical_key: str,
        actual_request_hash: str,
        request_payload: Mapping[str, Any],
        submitter: ProviderSubmitter | Callable[[Mapping[str, Any]], str],
        reconcile: Callable[[Mapping[str, Any], Mapping[str, Any]], str | None] | None,
    ) -> SubmitResult:
        status = SubmissionStatus(submission["status"])
        if status is SubmissionStatus.SUBMITTED:
            return SubmitResult(SubmitAction.REUSED, submission, logical_key, actual_request_hash)
        if status is SubmissionStatus.UNKNOWN:
            return self._reconcile_or_wait(
                submission,
                logical_key,
                actual_request_hash,
                request_payload,
                submitter,
                reconcile,
            )
        if status is SubmissionStatus.PREPARED:
            action = SubmitAction.NEEDS_RECONCILE
        elif status is SubmissionStatus.SUBMITTING:
            action = SubmitAction.IN_PROGRESS
        else:
            action = SubmitAction.FAILED
        return SubmitResult(action, submission, logical_key, actual_request_hash)

    def _reconcile_or_wait(
        self,
        submission: dict[str, Any],
        logical_key: str,
        actual_request_hash: str,
        request_payload: Mapping[str, Any],
        submitter: ProviderSubmitter | Callable[[Mapping[str, Any]], str],
        reconcile: Callable[[Mapping[str, Any], Mapping[str, Any]], str | None] | None,
    ) -> SubmitResult:
        reconcile_method = _reconcile_callable(submitter, reconcile)
        if reconcile_method is None:
            return SubmitResult(
                SubmitAction.NEEDS_RECONCILE,
                submission,
                logical_key,
                actual_request_hash,
            )
        try:
            external_task_id = reconcile_method(request_payload, submission)
        except Exception:
            external_task_id = None
        if not isinstance(external_task_id, str) or not external_task_id.strip():
            latest = self._submissions.get(submission["id"]) or submission
            return SubmitResult(
                SubmitAction.NEEDS_RECONCILE,
                latest,
                logical_key,
                actual_request_hash,
            )
        bound = self._submissions.bind_external_task(
            submission["id"],
            external_task_id=external_task_id,
        )
        return SubmitResult(
            SubmitAction.RECONCILED,
            bound,
            logical_key,
            actual_request_hash,
        )


__all__ = [
    "ProviderIdempotencyService",
    "ProviderSubmitTimeout",
    "ProviderSubmitter",
    "SubmitAction",
    "SubmitResult",
]
