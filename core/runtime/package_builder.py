"""T16 deterministic, Artifact-backed Shot Package builder.

Package manifests are durable Artifact outputs, not a new Runtime entity.  The
public preparation API is read-only; durable work is intentionally restricted
to the existing Task -> Queue -> Worker -> trusted-handler path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError

from core.runtime.prompt import CanonicalPrompt
from core.runtime.queue import TaskQueue
from core.runtime.resolver import ResolvedArtifact, ResolvedAsset, ResolvedShotContext
from core.runtime.state_store import StateStore, TaskStore
from core.runtime.worker import HandlerRegistry, TaskExecutionContext, Worker
from frameflow.idempotency import canonical_json


PACKAGE_MANIFEST_VERSION = 1
PACKAGE_ARTIFACT_ROLE = "package_manifest"
PACKAGE_ARTIFACT_STATUS = "READY"
TASK_BUILD_PACKAGE = "BUILD_SHOT_PACKAGE"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,120}$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_FORBIDDEN_KEY = re.compile(r"(?i)(?:api[_-]?key|token|password|secret|credential|authorization|command|shell|exec|eval|callable|module)")


class PackageBuilderError(RuntimeError):
    """Typed failure raised only inside the trusted Package handler."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class PackageIssue:
    code: str
    message: str
    blocking: bool = True
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "blocking": self.blocking, "details": dict(self.details)}


@dataclass(frozen=True, slots=True)
class PackagePreparation:
    ready: bool
    project_id: str | None
    shot_id: str
    artifact_id: str | None = None
    package_version: str | None = None
    logical_sha256: str | None = None
    destination: str | None = None
    manifest: Mapping[str, Any] | None = None
    source_artifact_ids: tuple[str, ...] = ()
    issues: tuple[PackageIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class PackageBuildResult:
    action: str
    preparation: PackagePreparation
    task: Mapping[str, Any] | None = None
    issues: tuple[PackageIssue, ...] = ()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_id(value: Any, field: str) -> str:
    text = str(value or "")
    if not _SAFE_ID.fullmatch(text):
        raise PackageBuilderError("INVALID_IDENTIFIER", f"{field} is not a safe identifier")
    return text


def _digest(prefix: str, value: Mapping[str, Any]) -> str:
    return f"{prefix}_{hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()[:48]}"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PackageAtomicJsonWriter:
    """Create a new JSON output without replacing an existing destination."""

    def write_new(self, destination: Path, payload: Mapping[str, Any]) -> str:
        if destination.exists() or destination.is_symlink():
            raise PackageBuilderError("PACKAGE_DESTINATION_COLLISION", "package destination already exists")
        temporary = destination.with_name(f".{destination.name}.tmp")
        if temporary.exists() or temporary.is_symlink():
            raise PackageBuilderError("PACKAGE_TEMPORARY_COLLISION", "package temporary path already exists")
        expected = (canonical_json(payload) + "\n").encode("utf-8")
        try:
            with temporary.open("xb") as handle:
                handle.write(expected)
                handle.flush()
                os.fsync(handle.fileno())
            if temporary.read_bytes() != expected:
                raise PackageBuilderError("PACKAGE_WRITE_FAILED", "serialized package verification failed")
            # Task identity serializes same-logical-input execution.  This
            # second collision check ensures an unrelated file is never
            # silently replaced by atomic finalization.
            if destination.exists() or destination.is_symlink():
                raise PackageBuilderError("PACKAGE_DESTINATION_COLLISION", "package destination appeared during write")
            os.replace(temporary, destination)
            return _file_sha256(destination)
        except PackageBuilderError:
            raise
        except OSError as exc:
            raise PackageBuilderError("PACKAGE_WRITE_FAILED", "package file could not be written atomically") from exc
        finally:
            if temporary.exists() or temporary.is_symlink():
                try:
                    temporary.unlink()
                except OSError:
                    pass


class PackageBuilder:
    """Build one deterministic Shot package from completed T20/T23 inputs."""

    def __init__(
        self,
        state_store: StateStore,
        *,
        projects_root: Path | str | None = None,
        allowed_reference_roots: Sequence[Path | str] | None = None,
        writer: PackageAtomicJsonWriter | None = None,
    ) -> None:
        self.store = state_store
        self.tasks = TaskStore(state_store)
        self.queue = TaskQueue(self.tasks)
        self.projects_root = (Path(projects_root) if projects_root is not None else Path(state_store.path).parent / "projects").resolve(strict=False)
        roots = allowed_reference_roots or (self.projects_root, Path(r"D:\AIGC\SUYU"), Path(r"D:\ComfyUI"))
        self.allowed_reference_roots = tuple(Path(root).resolve(strict=False) for root in roots)
        self.writer = writer or PackageAtomicJsonWriter()

    def _destination(self, project_id: str, shot_id: str, version: str) -> Path:
        destination = (self.projects_root / project_id / "shots" / shot_id / "packages" / f"{version}.json").resolve(strict=False)
        shot_root = (self.projects_root / project_id / "shots" / shot_id).resolve(strict=False)
        if not _inside(destination, shot_root):
            raise PackageBuilderError("PACKAGE_PATH_NOT_ALLOWED", "package destination escaped canonical Shot packages root")
        return destination

    @staticmethod
    def _candidates(context: ResolvedShotContext) -> list[tuple[str, ResolvedArtifact | None, str | None]]:
        entries: list[tuple[str, ResolvedArtifact | None, str | None]] = []
        entries.extend(("character_master", item.master_artifact, item.asset_id) for item in context.characters)
        if context.scene is not None:
            entries.append(("scene_master", context.scene.master_artifact, context.scene.asset_id))
        entries.extend(("prop_master", item.master_artifact, item.asset_id) for item in context.props)
        entries.extend((("first_frame", context.first_frame, None), ("last_frame", context.last_frame, None)))
        return entries

    def _reference(self, reference_type: str, projection: ResolvedArtifact | None, asset_id: str | None, project_id: str, shot_id: str, issues: list[PackageIssue]) -> dict[str, Any] | None:
        if projection is None or not projection.resolved:
            issues.append(PackageIssue("REFERENCE_NOT_RESOLVED", f"{reference_type} is not resolved"))
            return None
        row = self.store.get_artifact(projection.artifact_id)
        if row is None:
            issues.append(PackageIssue("MISSING_ARTIFACT", "referenced Artifact does not exist", details={"artifact_id": projection.artifact_id}))
            return None
        if str(row.get("project_id")) != project_id:
            issues.append(PackageIssue("CROSS_PROJECT_ARTIFACT", "Artifact belongs to another project", details={"artifact_id": projection.artifact_id}))
        if asset_id is not None and str(row.get("asset_id") or "") != asset_id:
            issues.append(PackageIssue("ARTIFACT_ASSET_MISMATCH", "Asset master Artifact does not match T20 reference", details={"artifact_id": projection.artifact_id}))
        if asset_id is None and str(row.get("shot_id") or "") != shot_id:
            issues.append(PackageIssue("CROSS_SHOT_ARTIFACT", "frame Artifact belongs to another Shot", details={"artifact_id": projection.artifact_id}))
        for key in ("path", "sha256", "version"):
            if not row.get(key):
                issues.append(PackageIssue("ARTIFACT_METADATA_INCOMPLETE", f"Artifact is missing {key}", details={"artifact_id": projection.artifact_id}))
        raw_path = str(row.get("path") or "")
        resolved = Path(raw_path).expanduser().resolve(strict=False)
        if not raw_path or Path(raw_path).is_symlink() or not any(_inside(resolved, root) for root in self.allowed_reference_roots):
            issues.append(PackageIssue("INVALID_ARTIFACT_PATH", "Artifact path is outside allowed roots or is a symlink", details={"artifact_id": projection.artifact_id}))
        elif not resolved.is_file():
            issues.append(PackageIssue("MISSING_ARTIFACT_FILE", "registered Artifact file is missing", details={"artifact_id": projection.artifact_id}))
        elif not _SHA256.fullmatch(str(row.get("sha256") or "")) or _file_sha256(resolved).lower() != str(row.get("sha256")).lower():
            issues.append(PackageIssue("ARTIFACT_INTEGRITY_MISMATCH", "registered Artifact hash does not match file", details={"artifact_id": projection.artifact_id}))
        for key in ("type", "role", "path", "sha256", "version", "project_id", "asset_id", "shot_id"):
            value = getattr(projection, key if key != "artifact_id" else "artifact_id", None)
            if key != "path" and value is not None and str(row.get(key) or "") != str(value):
                issues.append(PackageIssue("CONTEXT_ARTIFACT_MISMATCH", "T20 projection does not match registered Artifact", details={"artifact_id": projection.artifact_id, "field": key}))
        return {"reference_type": reference_type, "artifact_id": projection.artifact_id, "role": row.get("role"), "type": row.get("type"), "path": str(resolved), "sha256": row.get("sha256"), "version": row.get("version"), "asset_id": row.get("asset_id"), "shot_id": row.get("shot_id")}

    def prepare(self, context: ResolvedShotContext, canonical_prompt: CanonicalPrompt) -> PackagePreparation:
        if not isinstance(context, ResolvedShotContext):
            raise TypeError("prepare requires a T20 ResolvedShotContext")
        if not isinstance(canonical_prompt, CanonicalPrompt):
            raise TypeError("prepare requires a T23 CanonicalPrompt")
        issues: list[PackageIssue] = []
        project_id = str(context.project_id or "")
        shot_id = str(context.shot_id)
        if not context.ready:
            issues.append(PackageIssue("RESOLVER_NOT_READY", "T20 ResolvedShotContext is not ready"))
        if not project_id:
            issues.append(PackageIssue("PROJECT_ID_MISSING", "T20 context has no project ID"))
        if canonical_prompt.shot_id != shot_id:
            issues.append(PackageIssue("SHOT_ID_MISMATCH", "T23 prompt and T20 context identify different shots"))
        if not canonical_prompt.canonical_text or not _SHA256.fullmatch(canonical_prompt.prompt_sha256) or hashlib.sha256(canonical_prompt.canonical_text.encode("utf-8")).hexdigest() != canonical_prompt.prompt_sha256:
            issues.append(PackageIssue("CANONICAL_PROMPT_INVALID", "T23 canonical prompt content/hash is invalid"))
        shot = self.store.get_shot(shot_id)
        if shot is None:
            issues.append(PackageIssue("SHOT_NOT_FOUND", "Shot does not exist"))
        elif str(shot.get("project_id")) != project_id:
            issues.append(PackageIssue("PROJECT_MISMATCH", "Shot does not belong to T20 project"))
        if project_id and self.store.get_project(project_id) is None:
            issues.append(PackageIssue("PROJECT_NOT_FOUND", "Project does not exist"))
        references = [self._reference(kind, artifact, asset_id, project_id, shot_id, issues) for kind, artifact, asset_id in self._candidates(context)]
        refs = [item for item in references if item is not None]
        source_ids = tuple(item["artifact_id"] for item in refs)
        if tuple(canonical_prompt.source_artifact_ids) != source_ids:
            issues.append(PackageIssue("PROMPT_SOURCE_ARTIFACT_MISMATCH", "T23 source Artifact IDs differ from canonical T20 reference order"))
        if issues:
            return PackagePreparation(False, project_id or None, shot_id, source_artifact_ids=source_ids, issues=tuple(issues))
        identity = {"package_manifest_version": PACKAGE_MANIFEST_VERSION, "project_id": project_id, "shot_id": shot_id, "sequence_id": context.sequence_id, "shot_spec": context.shot_spec, "canonical_prompt": {"shot_id": canonical_prompt.shot_id, "shot_spec_version": canonical_prompt.shot_spec_version, "text": canonical_prompt.canonical_text, "sha256": canonical_prompt.prompt_sha256}, "references": refs, "source_artifact_ids": list(source_ids)}
        logical_sha256 = hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest()
        package_version = f"pkg-{logical_sha256[:24]}"
        artifact_id = f"PKG_{logical_sha256[:48]}"
        manifest = {"manifest_type": "FRAMEFLOW_V5_SHOT_PACKAGE", **identity, "package_version": package_version, "logical_sha256": logical_sha256}
        try:
            destination = self._destination(project_id, shot_id, package_version)
        except PackageBuilderError as exc:
            return PackagePreparation(False, project_id, shot_id, source_artifact_ids=source_ids, issues=(PackageIssue(exc.code, str(exc)),))
        return PackagePreparation(True, project_id, shot_id, artifact_id, package_version, logical_sha256, str(destination), manifest, source_ids)

    def build(self, context: ResolvedShotContext, canonical_prompt: CanonicalPrompt) -> PackageBuildResult:
        prepared = self.prepare(context, canonical_prompt)
        if not prepared.ready:
            return PackageBuildResult("INVALID_REQUEST", prepared, issues=prepared.issues)
        assert prepared.artifact_id and prepared.manifest and prepared.project_id
        payload = {"operation": "build_package", "project_id": prepared.project_id, "shot_id": prepared.shot_id, "artifact_id": prepared.artifact_id, "package_version": prepared.package_version, "logical_sha256": prepared.logical_sha256, "manifest": prepared.manifest, "source_artifact_ids": list(prepared.source_artifact_ids)}
        task_id = _digest("TASK_PACKAGE", payload)
        existing = self.tasks.get(task_id)
        if existing is not None:
            if str(existing.get("type")) != TASK_BUILD_PACKAGE or canonical_json(json.loads(str(existing.get("payload_json") or "{}"))) != canonical_json(payload):
                return PackageBuildResult("INVALID_REQUEST", prepared, issues=(PackageIssue("TASK_ID_CONFLICT", "deterministic Task ID conflicts with another payload"),))
            return PackageBuildResult("TASK_QUEUED", prepared, task=existing)
        try:
            task = self.tasks.create(task_id=task_id, task_type=TASK_BUILD_PACKAGE, project_id=prepared.project_id, shot_id=prepared.shot_id, idempotency_key=f"package:{prepared.logical_sha256}", payload=payload)
        except IntegrityError:
            # Concurrent duplicate requests race only at the unique Task row.
            # The winner is the single durable execution authority; the loser
            # must reuse it rather than create another package side effect.
            existing = self.tasks.get(task_id)
            if existing is None:
                raise
            if str(existing.get("type")) != TASK_BUILD_PACKAGE or canonical_json(json.loads(str(existing.get("payload_json") or "{}"))) != canonical_json(payload):
                return PackageBuildResult("INVALID_REQUEST", prepared, issues=(PackageIssue("TASK_ID_CONFLICT", "deterministic Task ID conflicts with another payload"),))
            return PackageBuildResult("TASK_QUEUED", prepared, task=existing)
        return PackageBuildResult("TASK_QUEUED", prepared, task=self.queue.enqueue(task_id))

    def trusted_handler_registry(self) -> HandlerRegistry:
        return HandlerRegistry({TASK_BUILD_PACKAGE: self._handle_build})

    def worker(self, *, worker_id: str = "package-builder-worker") -> Worker:
        return Worker(self.tasks, queue=self.queue, handlers=self.trusted_handler_registry(), worker_id=worker_id)

    def _handle_build(self, task: Mapping[str, Any], _context: TaskExecutionContext) -> dict[str, Any]:
        try:
            payload = json.loads(str(task.get("payload_json") or "{}"))
        except json.JSONDecodeError as exc:
            raise PackageBuilderError("INVALID_TASK_PAYLOAD", "Task payload is not JSON") from exc
        allowed = {"operation", "project_id", "shot_id", "artifact_id", "package_version", "logical_sha256", "manifest", "source_artifact_ids"}
        if not isinstance(payload, Mapping) or set(payload) != allowed or payload.get("operation") != "build_package":
            raise PackageBuilderError("INVALID_TASK_PAYLOAD", "Task payload is not a Package build request")
        project_id, shot_id, artifact_id = (_safe_id(payload.get(key), key) for key in ("project_id", "shot_id", "artifact_id"))
        manifest = payload.get("manifest")
        if not isinstance(manifest, Mapping) or any(_FORBIDDEN_KEY.search(str(key)) for key in manifest):
            raise PackageBuilderError("INVALID_TASK_PAYLOAD", "Package manifest is invalid or contains private/executable fields")
        expected_identity = {key: value for key, value in manifest.items() if key not in {"manifest_type", "package_version", "logical_sha256"}}
        logical_sha256 = hashlib.sha256(canonical_json(expected_identity).encode("utf-8")).hexdigest()
        if logical_sha256 != payload.get("logical_sha256") or logical_sha256 != manifest.get("logical_sha256") or payload.get("package_version") != manifest.get("package_version") or artifact_id != f"PKG_{logical_sha256[:48]}":
            raise PackageBuilderError("PACKAGE_INPUT_CONFLICT", "Package logical identity does not match manifest")
        if self.store.get_project(project_id) is None or (shot := self.store.get_shot(shot_id)) is None or str(shot.get("project_id")) != project_id:
            raise PackageBuilderError("PACKAGE_RELATION_INVALID", "Project/Shot relation is invalid")
        source_ids = payload.get("source_artifact_ids")
        if not isinstance(source_ids, list) or source_ids != manifest.get("source_artifact_ids"):
            raise PackageBuilderError("PACKAGE_INPUT_CONFLICT", "source Artifact identity differs from manifest")
        for reference in manifest.get("references", []):
            if not isinstance(reference, Mapping):
                raise PackageBuilderError("INVALID_TASK_PAYLOAD", "reference entry is invalid")
            row = self.store.get_artifact(str(reference.get("artifact_id") or ""))
            if row is None or str(row.get("project_id")) != project_id or str(row.get("sha256")) != str(reference.get("sha256")):
                raise PackageBuilderError("MISSING_ARTIFACT", "source Artifact changed or is missing")
            path = Path(str(row.get("path") or "")).expanduser().resolve(strict=False)
            if not path.is_file() or not any(_inside(path, root) for root in self.allowed_reference_roots) or _file_sha256(path).lower() != str(row.get("sha256")).lower():
                raise PackageBuilderError("ARTIFACT_INTEGRITY_MISMATCH", "source Artifact file is no longer valid")
        destination = self._destination(project_id, shot_id, str(payload["package_version"]))
        existing = self.store.get_artifact(artifact_id)
        if existing is not None:
            if str(existing.get("project_id")) == project_id and str(existing.get("shot_id")) == shot_id and existing.get("role") == PACKAGE_ARTIFACT_ROLE and existing.get("version") == payload["package_version"] and str(existing.get("path")) == str(destination) and destination.is_file() and str(existing.get("sha256")) == _file_sha256(destination):
                return {"action": "REUSED", "package_manifest_artifact_id": artifact_id, "package_version": payload["package_version"], "package_manifest_path": str(destination), "remote_call": False}
            raise PackageBuilderError("PACKAGE_INPUT_CONFLICT", "existing Artifact conflicts with package identity")
        if destination.exists() or destination.is_symlink():
            raise PackageBuilderError("PACKAGE_DESTINATION_COLLISION", "package destination already exists")
        created_dirs: list[Path] = []
        finalized = False
        try:
            current = destination.parent
            missing: list[Path] = []
            while not current.exists():
                missing.append(current)
                current = current.parent
            destination.parent.mkdir(parents=True, exist_ok=True)
            created_dirs.extend(reversed(missing))
            file_sha256 = self.writer.write_new(destination, manifest)
            finalized = True
            artifact = self.store.create_artifact(artifact_id, project_id, "json", PACKAGE_ARTIFACT_ROLE, str(destination), str(payload["package_version"]), shot_id=shot_id, sha256=file_sha256, source_task_id=str(task["id"]), source_artifacts=source_ids, status=PACKAGE_ARTIFACT_STATUS)
        except Exception:
            temporary = destination.with_name(f".{destination.name}.tmp")
            if temporary.exists() or temporary.is_symlink():
                try:
                    temporary.unlink()
                except OSError:
                    pass
            if finalized and (destination.exists() or destination.is_symlink()):
                try:
                    destination.unlink()
                except OSError:
                    pass
            for directory in reversed(created_dirs):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            raise
        return {"action": "READY", "package_manifest_artifact_id": str(artifact["id"]), "package_version": payload["package_version"], "package_manifest_path": str(destination), "package_sha256": file_sha256, "remote_call": False}


__all__ = ["PACKAGE_ARTIFACT_ROLE", "PACKAGE_ARTIFACT_STATUS", "PACKAGE_MANIFEST_VERSION", "TASK_BUILD_PACKAGE", "PackageAtomicJsonWriter", "PackageBuildResult", "PackageBuilder", "PackageBuilderError", "PackageIssue", "PackagePreparation"]
