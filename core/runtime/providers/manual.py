"""Provider-agnostic V5 Manual Provider Adapter.

The adapter is the Runtime bridge for a provider without a stable API. Pure
methods return handoff data; the three explicit mutations (mark submitted,
bind external task ID, and import result) are persisted only through the
existing Task -> Queue -> Worker -> trusted handler path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from core.runtime.idempotency import (
    ProviderIdempotencyService,
    ProviderSubmissionStore,
    idempotency_key,
    provider_config_hash,
    request_hash,
)
from core.runtime.prompt import CanonicalPrompt
from core.runtime.queue import TaskQueue
from core.runtime.resolver import ResolvedArtifact, ResolvedAsset, ResolvedShotContext
from core.runtime.state_store import StateStore, TaskStore
from core.runtime.worker import HandlerRegistry, TaskExecutionContext, Worker
from frameflow.idempotency import canonical_json


PROVIDER_IDENTITY = "manual"
TASK_MARK_SUBMITTED = "MANUAL_PROVIDER_MARK_SUBMITTED"
TASK_BIND_EXTERNAL_TASK_ID = "MANUAL_PROVIDER_BIND_EXTERNAL_TASK_ID"
TASK_IMPORT_RESULT = "MANUAL_PROVIDER_IMPORT_RESULT"
RESULT_ARTIFACT_ROLE = "provider_result"
RESULT_ARTIFACT_STATUS = "READY"
MANUAL_COST_STATUS = "UNKNOWN"

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_FORBIDDEN_KEY = re.compile(
    r"(?i)(?:^|[_-])(command|shell|exec|eval|callable|module|python|powershell)(?:$|[_-])"
)
_SECRET_KEY = re.compile(
    r"(?i)(?:api[_-]?key|token|password|secret|credential|authorization)"
)
_VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".webm", ".mkv", ".avi"})
_AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"})
_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".tif", ".tiff"})


class ManualAdapterError(RuntimeError):
    """A trusted Manual handler rejected a typed operation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class ManualAction(StrEnum):
    READY = "READY"
    INVALID_REQUEST = "INVALID_REQUEST"
    TASK_QUEUED = "TASK_QUEUED"
    MANUAL_ACTION_REQUIRED = "MANUAL_ACTION_REQUIRED"
    RECONCILED = "RECONCILED"
    MANUAL_CONFIRMATION_REQUIRED = "MANUAL_CONFIRMATION_REQUIRED"
    MANUAL_IMPORT_REQUIRED = "MANUAL_IMPORT_REQUIRED"
    MANUAL_CANCELLATION_REQUIRED = "MANUAL_CANCELLATION_REQUIRED"
    NORMALIZED = "NORMALIZED"
    REUSED = "REUSED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ManualIssue:
    code: str
    message: str
    blocking: bool = True
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "blocking": self.blocking,
            "details": _json_safe(self.details),
        }


@dataclass(frozen=True, slots=True)
class ReferenceArtifact:
    artifact_id: str
    reference_type: str
    role: str | None
    path: str
    sha256: str | None
    version: str | None
    status: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "reference_type": self.reference_type,
            "role": self.role,
            "path": self.path,
            "sha256": self.sha256,
            "version": self.version,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class UploadChecklist:
    canonical_prompt_present: bool
    package_ready: bool
    character_reference_artifact_ids: tuple[str, ...] = ()
    scene_reference_artifact_ids: tuple[str, ...] = ()
    prop_reference_artifact_ids: tuple[str, ...] = ()
    first_frame_artifact_id: str | None = None
    last_frame_artifact_id: str | None = None
    other_reference_artifact_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_prompt_present": self.canonical_prompt_present,
            "package_ready": self.package_ready,
            "character_reference_artifact_ids": list(self.character_reference_artifact_ids),
            "scene_reference_artifact_ids": list(self.scene_reference_artifact_ids),
            "prop_reference_artifact_ids": list(self.prop_reference_artifact_ids),
            "first_frame_artifact_id": self.first_frame_artifact_id,
            "last_frame_artifact_id": self.last_frame_artifact_id,
            "other_reference_artifact_ids": list(self.other_reference_artifact_ids),
        }


@dataclass(frozen=True, slots=True)
class ManualHandoff:
    provider: str
    generation_id: str
    shot_id: str
    project_id: str
    canonical_prompt_text: str
    prompt_sha256: str
    reference_artifacts: tuple[ReferenceArtifact, ...]
    upload_checklist: UploadChecklist
    package_manifest_artifact_id: str | None
    package_version: str | None
    package_manifest_path: str | None
    submission_ready: bool
    package_ready: bool
    required_manual_actions: tuple[str, ...]
    manual_instructions: tuple[str, ...]
    cost_status: str = MANUAL_COST_STATUS
    warnings: tuple[ManualIssue, ...] = ()
    issues: tuple[ManualIssue, ...] = ()
    idempotency_key: str | None = None
    request_hash: str | None = None
    provider_config_hash: str | None = None
    submission_request: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "generation_id": self.generation_id,
            "shot_id": self.shot_id,
            "project_id": self.project_id,
            "canonical_prompt_text": self.canonical_prompt_text,
            "prompt_sha256": self.prompt_sha256,
            "reference_artifacts": [item.to_dict() for item in self.reference_artifacts],
            "upload_checklist": self.upload_checklist.to_dict(),
            "package_manifest_artifact_id": self.package_manifest_artifact_id,
            "package_version": self.package_version,
            "package_manifest_path": self.package_manifest_path,
            "submission_ready": self.submission_ready,
            "package_ready": self.package_ready,
            "required_manual_actions": list(self.required_manual_actions),
            "manual_instructions": list(self.manual_instructions),
            "cost_status": self.cost_status,
            "warnings": [item.to_dict() for item in self.warnings],
            "issues": [item.to_dict() for item in self.issues],
            "submission_identity": {
                "idempotency_key": self.idempotency_key,
                "request_hash": self.request_hash,
                "provider_config_hash": self.provider_config_hash,
            },
        }


@dataclass(frozen=True, slots=True)
class ManualOperationResult:
    action: ManualAction | str
    handoff: ManualHandoff | None = None
    task: Mapping[str, Any] | None = None
    submission: Mapping[str, Any] | None = None
    data: Mapping[str, Any] = field(default_factory=dict)
    issues: tuple[ManualIssue, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": str(self.action),
            "handoff": self.handoff.to_dict() if self.handoff else None,
            "task": _json_safe(self.task),
            "submission": _json_safe(self.submission),
            "data": _json_safe(self.data),
            "issues": [item.to_dict() for item in self.issues],
        }


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _safe_text(value: Any, *, field_name: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManualAdapterError("INVALID_REQUEST", f"{field_name} must be non-empty text")
    normalized = value.strip()
    if len(normalized) > max_length:
        raise ManualAdapterError("INVALID_REQUEST", f"{field_name} exceeds {max_length} characters")
    if any(ord(char) < 32 for char in normalized):
        raise ManualAdapterError("INVALID_REQUEST", f"{field_name} contains control characters")
    return normalized


def _safe_identifier(value: Any, *, field_name: str) -> str:
    normalized = _safe_text(value, field_name=field_name, max_length=120)
    if not _SAFE_ID.fullmatch(normalized):
        raise ManualAdapterError("INVALID_REQUEST", f"{field_name} is not a safe identifier")
    return normalized


def _safe_external_task_id(value: Any) -> str:
    normalized = _safe_text(value, field_name="external_task_id", max_length=255)
    if "/" in normalized or "\\" in normalized:
        raise ManualAdapterError("INVALID_EXTERNAL_TASK_ID", "external_task_id is plain data, not a path")
    return normalized


def _safe_version(value: Any, *, field_name: str) -> str:
    return _safe_text(value, field_name=field_name, max_length=64)


def _safe_config(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ManualAdapterError("INVALID_PROVIDER_CONFIG", "provider_config must be a JSON object")

    def walk(item: Any, key_path: str = "") -> Any:
        if isinstance(item, Mapping):
            result: dict[str, Any] = {}
            for key, nested in item.items():
                normalized_key = str(key)
                if _FORBIDDEN_KEY.search(normalized_key):
                    raise ManualAdapterError("INVALID_PROVIDER_CONFIG", f"forbidden execution key: {key_path}{normalized_key}")
                if _SECRET_KEY.search(normalized_key):
                    raise ManualAdapterError("INVALID_PROVIDER_CONFIG", f"secret-like key is not accepted: {key_path}{normalized_key}")
                result[normalized_key] = walk(nested, key_path + normalized_key + ".")
            return result
        if isinstance(item, (list, tuple)):
            return [walk(nested, key_path) for nested in item]
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        raise ManualAdapterError("INVALID_PROVIDER_CONFIG", "provider_config must be JSON serializable")

    result = walk(value)
    try:
        canonical_json(result)
    except (TypeError, ValueError) as exc:
        raise ManualAdapterError("INVALID_PROVIDER_CONFIG", "provider_config must be canonical JSON") from exc
    return result


def _issue(code: str, message: str, *, blocking: bool = True, **details: Any) -> ManualIssue:
    return ManualIssue(code=code, message=message, blocking=blocking, details=details)


def _task_digest(prefix: str, value: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()[:48]
    return f"{prefix}_{digest}"


def _artifact_ids(value: Sequence[Any]) -> tuple[str, ...]:
    result: list[str] = []
    for item in value:
        result.append(_safe_identifier(item, field_name="artifact_id"))
    return tuple(result)


def _path_inside(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _media_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in _VIDEO_EXTENSIONS:
        return "video"
    if suffix in _AUDIO_EXTENSIONS:
        return "audio"
    if suffix in _IMAGE_EXTENSIONS:
        return "image"
    raise ManualAdapterError("UNSUPPORTED_RESULT_TYPE", f"unsupported media extension: {suffix or '<none>'}")


def _validate_source_artifacts(
    store: StateStore,
    project_id: str,
    artifact_ids: Sequence[Any],
) -> tuple[str, ...]:
    normalized = _artifact_ids(artifact_ids)
    for artifact_id in normalized:
        artifact = store.get_artifact(artifact_id)
        if artifact is None or str(artifact.get("project_id")) != project_id:
            raise ManualAdapterError(
                "SOURCE_ARTIFACT_INVALID",
                f"source Artifact is missing or cross-project: {artifact_id}",
            )
    return normalized


class _ManualConfirmationSubmitter:
    """Local confirmation callback used by T09; it never contacts a provider."""

    def __init__(self, external_task_id: str) -> None:
        self.external_task_id = external_task_id

    def submit(self, _request_payload: Mapping[str, Any]) -> str:
        return self.external_task_id


class ManualProviderAdapter:
    """Minimal V5 provider lifecycle for a human-operated external provider."""

    provider = PROVIDER_IDENTITY

    def __init__(self, state_store: StateStore, *, provider_config: Mapping[str, Any] | None = None) -> None:
        self.store = state_store
        self.tasks = TaskStore(state_store)
        self.queue = TaskQueue(self.tasks)
        self.provider_config = _safe_config(provider_config)
        self.projects_root = (Path(state_store.path).parent / "projects").resolve(strict=False)

    def _empty_handoff(
        self,
        *,
        canonical_prompt: CanonicalPrompt,
        context: ResolvedShotContext,
        generation_id: str,
        issues: Sequence[ManualIssue],
        warnings: Sequence[ManualIssue] = (),
        package_manifest_artifact_id: str | None = None,
        package_version: str | None = None,
        package_manifest_path: str | None = None,
        reference_artifacts: Sequence[ReferenceArtifact] = (),
    ) -> ManualHandoff:
        checklist = UploadChecklist(
            canonical_prompt_present=bool(canonical_prompt.canonical_text),
            package_ready=False,
            character_reference_artifact_ids=tuple(
                item.artifact_id
                for item in reference_artifacts
                if item.reference_type == "character_master"
            ),
            scene_reference_artifact_ids=tuple(
                item.artifact_id
                for item in reference_artifacts
                if item.reference_type == "scene_master"
            ),
            prop_reference_artifact_ids=tuple(
                item.artifact_id
                for item in reference_artifacts
                if item.reference_type == "prop_master"
            ),
            first_frame_artifact_id=next(
                (item.artifact_id for item in reference_artifacts if item.reference_type == "first_frame"),
                None,
            ),
            last_frame_artifact_id=next(
                (item.artifact_id for item in reference_artifacts if item.reference_type == "last_frame"),
                None,
            ),
        )
        return ManualHandoff(
            provider=self.provider,
            generation_id=generation_id,
            shot_id=str(context.shot_id),
            project_id=str(context.project_id or ""),
            canonical_prompt_text=canonical_prompt.canonical_text,
            prompt_sha256=canonical_prompt.prompt_sha256,
            reference_artifacts=tuple(reference_artifacts),
            upload_checklist=checklist,
            package_manifest_artifact_id=package_manifest_artifact_id,
            package_version=package_version,
            package_manifest_path=package_manifest_path,
            submission_ready=False,
            package_ready=False,
            required_manual_actions=("RESOLVE_BLOCKING_ISSUES",),
            manual_instructions=("Do not submit externally until the blocking handoff issues are resolved.",),
            warnings=tuple(warnings),
            issues=tuple(issues),
        )

    @staticmethod
    def _registered_file(path: Any) -> tuple[str | None, bool]:
        if not isinstance(path, str) or not path.strip():
            return None, False
        raw = Path(path).expanduser()
        try:
            resolved = raw.resolve(strict=False)
        except OSError:
            return str(raw), False
        if raw.is_symlink() or not resolved.is_file():
            return str(resolved), False
        return str(resolved), True

    def _reference_projection(
        self,
        context: ResolvedShotContext,
    ) -> tuple[tuple[ReferenceArtifact, ...], list[ManualIssue]]:
        candidates: list[tuple[str, ResolvedArtifact | None]] = []
        candidates.extend(
            ("character_master", asset.master_artifact)
            for asset in context.characters
        )
        if context.scene is not None:
            candidates.append(("scene_master", context.scene.master_artifact))
        candidates.extend(("prop_master", asset.master_artifact) for asset in context.props)
        candidates.extend((("first_frame", context.first_frame), ("last_frame", context.last_frame)))
        references: list[ReferenceArtifact] = []
        issues: list[ManualIssue] = []
        for reference_type, artifact in candidates:
            if artifact is None or not artifact.resolved:
                issues.append(_issue("REFERENCE_NOT_RESOLVED", f"{reference_type} is not resolved"))
                continue
            path, exists = self._registered_file(artifact.path)
            if path is None:
                issues.append(_issue("REFERENCE_PATH_MISSING", f"{artifact.artifact_id} has no registered path"))
                continue
            if not exists:
                issues.append(_issue("REFERENCE_FILE_MISSING", f"registered reference file is missing: {artifact.artifact_id}"))
                continue
            references.append(
                ReferenceArtifact(
                    artifact_id=_safe_identifier(artifact.artifact_id, field_name="artifact_id"),
                    reference_type=reference_type,
                    role=artifact.role,
                    path=path,
                    sha256=artifact.sha256,
                    version=artifact.version,
                    status=artifact.status,
                )
            )
        return tuple(references), issues

    def prepare(
        self,
        canonical_prompt: CanonicalPrompt,
        resolved_context: ResolvedShotContext,
        *,
        generation_id: str,
    ) -> ManualHandoff:
        """Read-only compile of a T23 prompt and T20 references into handoff data."""

        if not isinstance(canonical_prompt, CanonicalPrompt):
            raise TypeError("prepare requires a T23 CanonicalPrompt")
        if not isinstance(resolved_context, ResolvedShotContext):
            raise TypeError("prepare requires a T20 ResolvedShotContext")
        normalized_generation_id = _safe_identifier(generation_id, field_name="generation_id")
        issues: list[ManualIssue] = []
        warnings = list(canonical_prompt.warnings)
        references, reference_issues = self._reference_projection(resolved_context)
        issues.extend(reference_issues)
        if not resolved_context.ready:
            issues.append(_issue("RESOLVER_NOT_READY", "T20 ResolvedShotContext is not ready"))
        if canonical_prompt.shot_id != resolved_context.shot_id:
            issues.append(_issue("SHOT_ID_MISMATCH", "T23 prompt and T20 context identify different shots"))
        if not canonical_prompt.canonical_text:
            issues.append(_issue("PROMPT_MISSING", "T23 CanonicalPrompt text is empty"))
        if resolved_context.project_id is None:
            issues.append(_issue("PROJECT_ID_MISSING", "T20 context has no project_id"))

        project_id = str(resolved_context.project_id or "")
        shot_id = str(resolved_context.shot_id)
        generation = self.store.get_generation(normalized_generation_id)
        shot = self.store.get_shot(shot_id)
        package_id: str | None = None
        package_version: str | None = None
        package_path: str | None = None
        if generation is None:
            issues.append(_issue("GENERATION_NOT_FOUND", f"Generation does not exist: {normalized_generation_id}"))
        else:
            if str(generation.get("provider")) != self.provider:
                issues.append(_issue("GENERATION_PROVIDER_MISMATCH", "Generation provider is not manual"))
            if str(generation.get("shot_id")) != shot_id:
                issues.append(_issue("GENERATION_SHOT_MISMATCH", "Generation does not belong to the requested shot"))
            package_id = str(generation.get("package_manifest_artifact_id") or "") or None
            if package_id is None:
                issues.append(_issue("PACKAGE_REQUIRED", "Generation has no package manifest Artifact"))
            else:
                package = self.store.get_artifact(package_id)
                if package is None:
                    issues.append(_issue("PACKAGE_REQUIRED", "package manifest Artifact is missing"))
                else:
                    package_path, package_exists = self._registered_file(package.get("path"))
                    package_version = str(package.get("version") or "") or None
                    if not package_version or not package_path or not package_exists:
                        issues.append(_issue("PACKAGE_NOT_READY", "registered package identity/version/file is incomplete"))
                    if str(package.get("project_id")) != project_id or str(package.get("shot_id")) != shot_id:
                        issues.append(_issue("PACKAGE_RELATION_MISMATCH", "package manifest is not owned by the Generation shot/project"))
        if shot is None:
            issues.append(_issue("SHOT_NOT_FOUND", f"Shot does not exist: {shot_id}"))
        elif str(shot.get("project_id")) != project_id:
            issues.append(_issue("PROJECT_MISMATCH", "Shot project does not match T20 context"))

        blocking = tuple(issue for issue in issues if issue.blocking)
        config_hash = provider_config_hash(self.provider_config)
        submission_request: dict[str, Any] = {
            "generation_id": normalized_generation_id,
            "project_id": project_id,
            "shot_id": shot_id,
            "provider": self.provider,
            "package_manifest_artifact_id": package_id,
            "package_version": package_version,
            "shot_spec_version": canonical_prompt.shot_spec_version,
            "prompt_text": canonical_prompt.canonical_text,
            "prompt_sha256": canonical_prompt.prompt_sha256,
            "reference_artifact_ids": [item.artifact_id for item in references],
        }
        logical_key: str | None = None
        actual_request_hash: str | None = None
        if package_version and project_id:
            logical_key = idempotency_key(
                project_id=project_id,
                shot_id=shot_id,
                package_version=package_version,
                shot_spec_version=canonical_prompt.shot_spec_version,
                provider=self.provider,
                provider_config_hash=config_hash,
            )
            actual_request_hash = request_hash(submission_request)
        package_ready = any(issue.code in {"PACKAGE_REQUIRED", "PACKAGE_NOT_READY", "PACKAGE_RELATION_MISMATCH"} for issue in issues) is False
        checklist = UploadChecklist(
            canonical_prompt_present=bool(canonical_prompt.canonical_text),
            package_ready=package_ready,
            character_reference_artifact_ids=tuple(item.artifact_id for item in references if item.reference_type == "character_master"),
            scene_reference_artifact_ids=tuple(item.artifact_id for item in references if item.reference_type == "scene_master"),
            prop_reference_artifact_ids=tuple(item.artifact_id for item in references if item.reference_type == "prop_master"),
            first_frame_artifact_id=next((item.artifact_id for item in references if item.reference_type == "first_frame"), None),
            last_frame_artifact_id=next((item.artifact_id for item in references if item.reference_type == "last_frame"), None),
        )
        ready = not blocking
        actions = (
            ("COPY_PROMPT", "UPLOAD_REFERENCES", "SUBMIT_EXTERNALLY", "MARK_SUBMITTED_WITH_EXTERNAL_TASK_ID")
            if ready
            else ("RESOLVE_BLOCKING_ISSUES",)
        )
        instructions = (
            ("Copy canonical_prompt_text without editing it.", "Upload only the registered reference paths in checklist order.", "Submit manually outside FRAMEFLOW, then record the external task ID.")
            if ready
            else ("Do not submit externally until the blocking handoff issues are resolved.",)
        )
        return ManualHandoff(
            provider=self.provider,
            generation_id=normalized_generation_id,
            shot_id=shot_id,
            project_id=project_id,
            canonical_prompt_text=canonical_prompt.canonical_text,
            prompt_sha256=canonical_prompt.prompt_sha256,
            reference_artifacts=references,
            upload_checklist=checklist,
            package_manifest_artifact_id=package_id,
            package_version=package_version,
            package_manifest_path=package_path,
            submission_ready=ready,
            package_ready=package_ready,
            required_manual_actions=actions,
            manual_instructions=instructions,
            warnings=tuple(warnings),
            issues=tuple(issues),
            idempotency_key=logical_key,
            request_hash=actual_request_hash,
            provider_config_hash=config_hash,
            submission_request=submission_request,
        )

    def submit(self, handoff: ManualHandoff) -> ManualOperationResult:
        """Return a manual-action handoff; never call an external Provider."""

        if not isinstance(handoff, ManualHandoff):
            raise TypeError("submit requires a ManualHandoff")
        if not handoff.submission_ready:
            return ManualOperationResult(
                action=ManualAction.INVALID_REQUEST,
                handoff=handoff,
                issues=handoff.issues or (_issue("PACKAGE_REQUIRED", "handoff is not submission-ready"),),
            )
        return ManualOperationResult(
            action=ManualAction.MANUAL_ACTION_REQUIRED,
            handoff=handoff,
            data={
                "instructions": list(handoff.manual_instructions),
                "submission_identity": {
                    "idempotency_key": handoff.idempotency_key,
                    "request_hash": handoff.request_hash,
                },
            },
        )

    def _ensure_task(
        self,
        *,
        task_id: str,
        task_type: str,
        project_id: str,
        shot_id: str,
        payload: Mapping[str, Any],
    ) -> ManualOperationResult:
        existing = self.tasks.get(task_id)
        if existing is not None:
            try:
                existing_payload = json.loads(str(existing.get("payload_json") or "{}"))
            except json.JSONDecodeError as exc:
                raise ManualAdapterError("TASK_PAYLOAD_CORRUPT", f"existing Task payload is invalid: {task_id}") from exc
            if existing.get("type") != task_type or canonical_json(existing_payload) != canonical_json(payload):
                return ManualOperationResult(
                    action=ManualAction.INVALID_REQUEST,
                    issues=(_issue("TASK_ID_CONFLICT", "deterministic Task identity conflicts with an existing payload"),),
                )
            return ManualOperationResult(action=ManualAction.TASK_QUEUED, task=existing)
        task = self.tasks.create(
            task_id=task_id,
            task_type=task_type,
            project_id=project_id,
            shot_id=shot_id,
            idempotency_key=f"manual-task:{task_id}",
            payload=dict(payload),
        )
        queued = self.queue.enqueue(task_id)
        return ManualOperationResult(action=ManualAction.TASK_QUEUED, task=queued)

    def mark_submitted(self, handoff: ManualHandoff, *, external_task_id: str) -> ManualOperationResult:
        if not isinstance(handoff, ManualHandoff):
            raise TypeError("mark_submitted requires a ManualHandoff")
        if not handoff.submission_ready:
            return ManualOperationResult(action=ManualAction.INVALID_REQUEST, handoff=handoff, issues=handoff.issues)
        try:
            normalized_external_id = _safe_external_task_id(external_task_id)
        except ManualAdapterError as exc:
            return ManualOperationResult(action=ManualAction.INVALID_REQUEST, handoff=handoff, issues=(_issue(exc.code, str(exc)),))
        payload = {
            "operation": "mark_submitted",
            "provider": self.provider,
            "generation_id": handoff.generation_id,
            "project_id": handoff.project_id,
            "shot_id": handoff.shot_id,
            "package_version": handoff.package_version,
            "shot_spec_version": str(handoff.submission_request.get("shot_spec_version") or ""),
            "provider_config": self.provider_config,
            "request_payload": dict(handoff.submission_request),
            "external_task_id": normalized_external_id,
        }
        task_id = _task_digest("TASK_MANUAL_MARK", {"idempotency_key": handoff.idempotency_key, "external_task_id": normalized_external_id})
        return self._ensure_task(task_id=task_id, task_type=TASK_MARK_SUBMITTED, project_id=handoff.project_id, shot_id=handoff.shot_id, payload=payload)

    def bind_external_task_id(self, submission_id: str, *, external_task_id: str) -> ManualOperationResult:
        try:
            normalized_submission_id = _safe_identifier(submission_id, field_name="submission_id")
            normalized_external_id = _safe_external_task_id(external_task_id)
        except ManualAdapterError as exc:
            return ManualOperationResult(action=ManualAction.INVALID_REQUEST, issues=(_issue(exc.code, str(exc)),))
        submission_store = ProviderSubmissionStore(self.store)
        existing = submission_store.get(normalized_submission_id)
        if existing is None:
            return ManualOperationResult(
                action=ManualAction.INVALID_REQUEST,
                issues=(_issue("SUBMISSION_NOT_FOUND", "ProviderSubmission does not exist"),),
            )
        generation = self.store.get_generation(str(existing["generation_id"]))
        if generation is None or str(generation.get("provider")) != self.provider:
            return ManualOperationResult(
                action=ManualAction.INVALID_REQUEST,
                issues=(_issue("GENERATION_RELATION_INVALID", "ProviderSubmission is not a manual Generation"),),
            )
        shot = self.store.get_shot(str(generation["shot_id"]))
        if shot is None:
            return ManualOperationResult(
                action=ManualAction.INVALID_REQUEST,
                issues=(_issue("GENERATION_RELATION_INVALID", "ProviderSubmission shot does not exist"),),
            )
        payload = {
            "operation": "bind_external_task_id",
            "provider": self.provider,
            "submission_id": normalized_submission_id,
            "external_task_id": normalized_external_id,
            "generation_id": str(generation["id"]),
            "project_id": str(shot["project_id"]),
            "shot_id": str(shot["id"]),
        }
        task_id = _task_digest("TASK_MANUAL_BIND", payload)
        return self._ensure_task(
            task_id=task_id,
            task_type=TASK_BIND_EXTERNAL_TASK_ID,
            project_id=str(shot["project_id"]),
            shot_id=str(shot["id"]),
            payload=payload,
        )

    def _allowed_source_roots(self, project_id: str) -> tuple[Path, ...]:
        return (
            (Path(tempfile.gettempdir()) / "FRAMEFLOW").resolve(strict=False),
            (self.projects_root / project_id / "imports").resolve(strict=False),
        )

    def _safe_source_path(self, project_id: str, source_path: Any, *, require_file: bool) -> Path:
        if not isinstance(source_path, str) or not source_path.strip():
            raise ManualAdapterError("SOURCE_PATH_REQUIRED", "source path is required")
        raw = Path(source_path).expanduser()
        try:
            resolved = raw.resolve(strict=False)
        except OSError as exc:
            raise ManualAdapterError("SOURCE_PATH_INVALID", "source path cannot be canonicalized") from exc
        if raw.is_symlink() or not any(_path_inside(resolved, root) for root in self._allowed_source_roots(project_id)):
            raise ManualAdapterError("SOURCE_PATH_NOT_ALLOWED", "source path is outside approved import staging")
        if require_file and not resolved.is_file():
            raise ManualAdapterError("SOURCE_NOT_FOUND", "source file does not exist")
        return resolved

    def import_result(
        self,
        handoff: ManualHandoff,
        *,
        source_path: str,
        destination_name: str,
        version: str,
        expected_sha256: str | None = None,
    ) -> ManualOperationResult:
        if not isinstance(handoff, ManualHandoff):
            raise TypeError("import_result requires a ManualHandoff")
        if not handoff.submission_ready:
            return ManualOperationResult(action=ManualAction.INVALID_REQUEST, handoff=handoff, issues=handoff.issues)
        try:
            source = self._safe_source_path(handoff.project_id, source_path, require_file=True)
            safe_name = _safe_text(destination_name, field_name="destination_name", max_length=120)
            if not _SAFE_NAME.fullmatch(safe_name) or Path(safe_name).name != safe_name:
                raise ManualAdapterError("INVALID_DESTINATION_NAME", "destination_name must be a safe basename")
            safe_version = _safe_version(version, field_name="version")
            if expected_sha256 is not None and not _SHA256.fullmatch(expected_sha256):
                raise ManualAdapterError("INVALID_EXPECTED_SHA256", "expected_sha256 must be 64 hex characters")
            _media_type(safe_name)
        except ManualAdapterError as exc:
            return ManualOperationResult(action=ManualAction.INVALID_REQUEST, handoff=handoff, issues=(_issue(exc.code, str(exc)),))
        payload = {
            "operation": "import_result",
            "provider": self.provider,
            "generation_id": handoff.generation_id,
            "project_id": handoff.project_id,
            "shot_id": handoff.shot_id,
            "source_path": str(source),
            "destination_name": safe_name,
            "version": safe_version,
            "expected_sha256": expected_sha256.lower() if expected_sha256 else None,
            "source_artifact_ids": [
                *(([handoff.package_manifest_artifact_id] if handoff.package_manifest_artifact_id else [])),
                *(item.artifact_id for item in handoff.reference_artifacts),
            ],
        }
        task_id = _task_digest("TASK_MANUAL_IMPORT", payload)
        return self._ensure_task(task_id=task_id, task_type=TASK_IMPORT_RESULT, project_id=handoff.project_id, shot_id=handoff.shot_id, payload=payload)

    def reconcile(self, submission_id: str) -> ManualOperationResult:
        try:
            normalized = _safe_identifier(submission_id, field_name="submission_id")
        except ManualAdapterError as exc:
            return ManualOperationResult(action=ManualAction.INVALID_REQUEST, issues=(_issue(exc.code, str(exc)),))
        submission = ProviderSubmissionStore(self.store).get(normalized)
        if submission is None:
            return ManualOperationResult(action=ManualAction.MANUAL_CONFIRMATION_REQUIRED, issues=(_issue("SUBMISSION_NOT_FOUND", "local ProviderSubmission does not exist"),))
        if submission.get("status") == "SUBMITTED" and submission.get("external_task_id"):
            return ManualOperationResult(action=ManualAction.RECONCILED, submission=submission)
        return ManualOperationResult(action=ManualAction.MANUAL_CONFIRMATION_REQUIRED, submission=submission)

    def poll(self, submission_id: str) -> ManualOperationResult:
        return self.reconcile(submission_id)

    def fetch(self, generation_id: str) -> ManualOperationResult:
        try:
            normalized = _safe_identifier(generation_id, field_name="generation_id")
        except ManualAdapterError as exc:
            return ManualOperationResult(action=ManualAction.INVALID_REQUEST, issues=(_issue(exc.code, str(exc)),))
        return ManualOperationResult(
            action=ManualAction.MANUAL_IMPORT_REQUIRED,
            data={
                "generation_id": normalized,
                "allowed_source_roots": [str(root) for root in self._allowed_source_roots("<project>")],
                "instructions": ["Place the externally downloaded result in approved import staging, then call import_result."],
            },
        )

    def cancel(self, submission_id: str) -> ManualOperationResult:
        try:
            normalized = _safe_identifier(submission_id, field_name="submission_id")
        except ManualAdapterError as exc:
            return ManualOperationResult(action=ManualAction.INVALID_REQUEST, issues=(_issue(exc.code, str(exc)),))
        return ManualOperationResult(
            action=ManualAction.MANUAL_CANCELLATION_REQUIRED,
            data={"submission_id": normalized, "status_mutated": False},
        )

    def normalize_result(self, result: Mapping[str, Any]) -> ManualOperationResult:
        if not isinstance(result, Mapping):
            return ManualOperationResult(action=ManualAction.INVALID_REQUEST, issues=(_issue("INVALID_RESULT", "result must be a mapping"),))
        try:
            generation_id = _safe_identifier(result.get("generation_id"), field_name="generation_id")
            project_id = _safe_identifier(result.get("project_id"), field_name="project_id")
            shot_id = _safe_identifier(result.get("shot_id"), field_name="shot_id")
            artifact_id = _safe_identifier(result.get("artifact_id"), field_name="artifact_id")
            source_task_id = _safe_identifier(result.get("source_task_id"), field_name="source_task_id")
            path = _safe_text(result.get("path"), field_name="path", max_length=4096)
            version = _safe_version(result.get("version"), field_name="version")
            sha = _safe_text(result.get("sha256"), field_name="sha256", max_length=128).lower()
            if not _SHA256.fullmatch(sha):
                raise ManualAdapterError("INVALID_SHA256", "sha256 must be 64 hex characters")
            if result.get("asset_id") is not None:
                raise ManualAdapterError("RESULT_ASSET_ID_MUST_BE_NULL", "provider result Artifacts use asset_id=NULL")
            if result.get("role") != RESULT_ARTIFACT_ROLE:
                raise ManualAdapterError("INVALID_RESULT_ROLE", "result role must be provider_result")
            generation = self.store.get_generation(generation_id)
            shot = self.store.get_shot(shot_id)
            if generation is None or shot is None:
                raise ManualAdapterError("GENERATION_RELATION_INVALID", "Generation or Shot does not exist")
            if str(generation.get("shot_id")) != shot_id or str(shot.get("project_id")) != project_id:
                raise ManualAdapterError("GENERATION_RELATION_INVALID", "result project/shot does not match Generation")
            if str(generation.get("provider")) != self.provider:
                raise ManualAdapterError("GENERATION_PROVIDER_MISMATCH", "Generation provider is not manual")
            resolved_path = Path(path).expanduser().resolve(strict=False)
            destination_root = self._destination_root(project_id, shot_id, generation_id).resolve(strict=False)
            if not _path_inside(resolved_path, destination_root) or resolved_path == destination_root:
                raise ManualAdapterError("INVALID_RESULT_PATH", "result path is outside the canonical Generation destination")
            source_ids = _validate_source_artifacts(
                self.store,
                project_id,
                result.get("source_artifacts") or [],
            )
            normalized = {
                "artifact_id": artifact_id,
                "project_id": project_id,
                "shot_id": shot_id,
                "generation_id": generation_id,
                "asset_id": None,
                "type": _safe_text(result.get("type"), field_name="type", max_length=64),
                "role": RESULT_ARTIFACT_ROLE,
                "path": str(resolved_path),
                "sha256": sha,
                "version": version,
                "source_task_id": source_task_id,
                "source_artifacts": list(source_ids),
                "status": RESULT_ARTIFACT_STATUS,
            }
        except ManualAdapterError as exc:
            return ManualOperationResult(action=ManualAction.INVALID_REQUEST, issues=(_issue(exc.code, str(exc)),))
        return ManualOperationResult(
            action=ManualAction.NORMALIZED,
            data={"result": normalized, "review_required": True, "review_target_generation_id": generation_id, "result_artifact_ids": [artifact_id]},
        )

    def trusted_handler_registry(self) -> HandlerRegistry:
        """Return the explicit allowlist used by the Runtime Worker."""

        return HandlerRegistry(
            {
                TASK_MARK_SUBMITTED: self._handle_mark_submitted,
                TASK_BIND_EXTERNAL_TASK_ID: self._handle_bind_external_task_id,
                TASK_IMPORT_RESULT: self._handle_import_result,
            }
        )

    def worker(self, *, worker_id: str = "manual-provider-worker") -> Worker:
        return Worker(self.tasks, queue=self.queue, handlers=self.trusted_handler_registry(), worker_id=worker_id)

    def _generation_for_payload(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        generation_id = _safe_identifier(payload.get("generation_id"), field_name="generation_id")
        project_id = _safe_identifier(payload.get("project_id"), field_name="project_id")
        shot_id = _safe_identifier(payload.get("shot_id"), field_name="shot_id")
        generation = self.store.get_generation(generation_id)
        shot = self.store.get_shot(shot_id)
        if generation is None or shot is None:
            raise ManualAdapterError("GENERATION_RELATION_INVALID", "Generation or Shot does not exist")
        if str(generation.get("provider")) != self.provider or str(generation.get("shot_id")) != shot_id or str(shot.get("project_id")) != project_id:
            raise ManualAdapterError("GENERATION_RELATION_INVALID", "typed payload does not match Generation/Shot/Project")
        return generation, shot

    @staticmethod
    def _strict_payload(payload: Mapping[str, Any], allowed: set[str]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ManualAdapterError("INVALID_TASK_PAYLOAD", "Task payload must be an object")
        for key in payload:
            key_text = str(key)
            if key_text not in allowed or _FORBIDDEN_KEY.search(key_text):
                raise ManualAdapterError("INVALID_TASK_PAYLOAD", f"unsupported Task payload key: {key_text}")
        return dict(payload)

    def _handle_mark_submitted(self, task: Mapping[str, Any], _context: TaskExecutionContext) -> dict[str, Any]:
        payload = self._strict_payload(
            json.loads(str(task.get("payload_json") or "{}")),
            {"operation", "provider", "generation_id", "project_id", "shot_id", "package_version", "shot_spec_version", "provider_config", "request_payload", "external_task_id"},
        )
        if payload.get("provider") != self.provider or payload.get("operation") != "mark_submitted":
            raise ManualAdapterError("INVALID_TASK_PAYLOAD", "invalid manual mark-submitted operation")
        generation, _shot = self._generation_for_payload(payload)
        package_version = _safe_version(payload.get("package_version"), field_name="package_version")
        shot_spec_version = _safe_version(payload.get("shot_spec_version"), field_name="shot_spec_version")
        external_task_id = _safe_external_task_id(payload.get("external_task_id"))
        config = _safe_config(payload.get("provider_config"))
        request_payload = payload.get("request_payload")
        if not isinstance(request_payload, Mapping):
            raise ManualAdapterError("INVALID_TASK_PAYLOAD", "request_payload must be an object")
        submission_store = ProviderSubmissionStore(self.store)
        logical_key = idempotency_key(
            project_id=str(payload["project_id"]),
            shot_id=str(payload["shot_id"]),
            package_version=package_version,
            shot_spec_version=shot_spec_version,
            provider=self.provider,
            provider_config_hash=provider_config_hash(config),
        )
        existing = submission_store.get_by_idempotency_key(logical_key)
        if (
            existing is not None
            and existing.get("status") == "SUBMITTED"
            and existing.get("external_task_id") != external_task_id
        ):
            raise ManualAdapterError(
                "EXTERNAL_TASK_ID_CONFLICT",
                "the logical ProviderSubmission is already bound to another external task ID",
            )
        service = ProviderIdempotencyService(submission_store)
        result = service.submit(
            generation_id=str(generation["id"]),
            project_id=str(payload["project_id"]),
            shot_id=str(payload["shot_id"]),
            package_version=package_version,
            shot_spec_version=shot_spec_version,
            provider=self.provider,
            provider_config=config,
            request_payload=request_payload,
            submitter=_ManualConfirmationSubmitter(external_task_id),
        )
        return {
            "action": result.action.value,
            "provider": self.provider,
            "submission": _json_safe(result.submission),
            "idempotency_key": result.idempotency_key,
            "request_hash": result.request_hash,
            "remote_call": False,
            "review_required": False,
        }

    def _handle_bind_external_task_id(self, task: Mapping[str, Any], _context: TaskExecutionContext) -> dict[str, Any]:
        payload = self._strict_payload(
            json.loads(str(task.get("payload_json") or "{}")),
            {"operation", "provider", "submission_id", "external_task_id", "generation_id", "project_id", "shot_id"},
        )
        if payload.get("provider") != self.provider or payload.get("operation") != "bind_external_task_id":
            raise ManualAdapterError("INVALID_TASK_PAYLOAD", "invalid manual external-task binding operation")
        submission_id = _safe_identifier(payload.get("submission_id"), field_name="submission_id")
        external_task_id = _safe_external_task_id(payload.get("external_task_id"))
        self._generation_for_payload(payload)
        submission_store = ProviderSubmissionStore(self.store)
        existing = submission_store.get(submission_id)
        if existing is None or str(existing.get("generation_id")) != str(payload.get("generation_id")):
            raise ManualAdapterError("SUBMISSION_RELATION_INVALID", "ProviderSubmission does not match the typed Generation")
        submission = submission_store.bind_external_task(submission_id, external_task_id=external_task_id)
        return {
            "action": ManualAction.REUSED.value if submission.get("external_task_id") == external_task_id and submission.get("status") == "SUBMITTED" else ManualAction.READY.value,
            "provider": self.provider,
            "submission": _json_safe(submission),
            "remote_call": False,
        }

    def _destination_root(self, project_id: str, shot_id: str, generation_id: str) -> Path:
        candidate = (
            self.projects_root
            / project_id
            / "shots"
            / shot_id
            / "generations"
            / generation_id
        ).resolve(strict=False)
        if not _path_inside(candidate, self.projects_root):
            raise ManualAdapterError(
                "DESTINATION_PATH_NOT_ALLOWED",
                "Generation destination escaped the canonical projects root",
            )
        return candidate

    def _handle_import_result(self, task: Mapping[str, Any], _context: TaskExecutionContext) -> dict[str, Any]:
        payload = self._strict_payload(
            json.loads(str(task.get("payload_json") or "{}")),
            {"operation", "provider", "generation_id", "project_id", "shot_id", "source_path", "destination_name", "version", "expected_sha256", "source_artifact_ids"},
        )
        if payload.get("provider") != self.provider or payload.get("operation") != "import_result":
            raise ManualAdapterError("INVALID_TASK_PAYLOAD", "invalid manual result-import operation")
        generation, _shot = self._generation_for_payload(payload)
        project_id = _safe_identifier(payload.get("project_id"), field_name="project_id")
        shot_id = _safe_identifier(payload.get("shot_id"), field_name="shot_id")
        generation_id = _safe_identifier(payload.get("generation_id"), field_name="generation_id")
        source = self._safe_source_path(project_id, payload.get("source_path"), require_file=True)
        destination_name = _safe_text(payload.get("destination_name"), field_name="destination_name", max_length=120)
        if not _SAFE_NAME.fullmatch(destination_name) or Path(destination_name).name != destination_name:
            raise ManualAdapterError("INVALID_DESTINATION_NAME", "destination_name must be a safe basename")
        version = _safe_version(payload.get("version"), field_name="version")
        expected_sha = payload.get("expected_sha256")
        if expected_sha is not None and not _SHA256.fullmatch(str(expected_sha)):
            raise ManualAdapterError("INVALID_EXPECTED_SHA256", "expected_sha256 must be 64 hex characters")
        source_ids = _validate_source_artifacts(
            self.store,
            project_id,
            payload.get("source_artifact_ids") or [],
        )
        media_type = _media_type(destination_name)
        artifact_id = _task_digest("ART_MANUAL_RESULT", {"task_id": str(task["id"])})
        destination_root = self._destination_root(project_id, shot_id, generation_id)
        destination = destination_root / destination_name
        existing = self.store.get_artifact(artifact_id)
        if existing is not None:
            if (
                str(existing.get("generation_id")) == generation_id
                and str(existing.get("project_id")) == project_id
                and str(existing.get("shot_id")) == shot_id
                and existing.get("role") == RESULT_ARTIFACT_ROLE
                and existing.get("source_task_id") == str(task["id"])
                and str(existing.get("path")) == str(destination)
                and Path(str(existing.get("path"))).is_file()
                and str(existing.get("sha256")) == _sha256(Path(str(existing.get("path"))))
            ):
                return {"action": ManualAction.REUSED.value, "provider": self.provider, "result_artifact_ids": [artifact_id], "review_required": True, "generation_id": generation_id, "remote_call": False}
            raise ManualAdapterError("IMPORT_IDEMPOTENCY_CONFLICT", "existing Artifact does not match this import Task")
        if destination.exists() or destination.is_symlink():
            raise ManualAdapterError("DESTINATION_COLLISION", "destination already exists and will not be overwritten")
        digest, size = _hash_file(source)
        if expected_sha is not None and digest.lower() != str(expected_sha).lower():
            raise ManualAdapterError("HASH_MISMATCH", "source SHA-256 does not match expected_sha256")
        created_dirs: list[Path] = []
        temporary: Path | None = None
        finalized = False
        try:
            current = destination_root
            missing: list[Path] = []
            while not current.exists():
                missing.append(current)
                current = current.parent
            destination_root.mkdir(parents=True, exist_ok=True)
            created_dirs.extend(reversed(missing))
            temporary = destination.with_name(f".{destination.name}.{str(task['id'])[-16:]}.tmp")
            if temporary.exists() or temporary.is_symlink():
                raise ManualAdapterError("TEMPORARY_COLLISION", "temporary import path already exists")
            with source.open("rb") as source_handle, temporary.open("xb") as destination_handle:
                while True:
                    chunk = source_handle.read(1024 * 1024)
                    if not chunk:
                        break
                    destination_handle.write(chunk)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())
            copied_digest, copied_size = _hash_file(temporary)
            if copied_digest != digest or copied_size != size:
                raise ManualAdapterError("COPY_VERIFICATION_FAILED", "copied result failed size/hash verification")
            os.replace(temporary, destination)
            temporary = None
            finalized = True
            artifact = self.store.create_artifact(
                artifact_id,
                project_id,
                media_type,
                RESULT_ARTIFACT_ROLE,
                str(destination),
                version,
                shot_id=shot_id,
                asset_id=None,
                sha256=digest,
                source_task_id=str(task["id"]),
                source_artifacts=list(source_ids),
                generation_id=generation_id,
                status=RESULT_ARTIFACT_STATUS,
            )
        except Exception:
            if temporary is not None and (temporary.exists() or temporary.is_symlink()):
                temporary.unlink()
            if finalized and (destination.exists() or destination.is_symlink()):
                destination.unlink()
            for directory in reversed(created_dirs):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            raise
        return {
            "action": ManualAction.READY.value,
            "provider": self.provider,
            "result_artifact_ids": [str(artifact["id"])],
            "generation_id": generation_id,
            "review_required": True,
            "review_target_generation_id": generation_id,
            "source_task_id": str(task["id"]),
            "source_sha256": digest,
            "remote_call": False,
        }


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


__all__ = [
    "MANUAL_COST_STATUS",
    "PROVIDER_IDENTITY",
    "RESULT_ARTIFACT_ROLE",
    "RESULT_ARTIFACT_STATUS",
    "TASK_BIND_EXTERNAL_TASK_ID",
    "TASK_IMPORT_RESULT",
    "TASK_MARK_SUBMITTED",
    "ManualAction",
    "ManualAdapterError",
    "ManualHandoff",
    "ManualIssue",
    "ManualOperationResult",
    "ManualProviderAdapter",
    "ReferenceArtifact",
    "UploadChecklist",
]
