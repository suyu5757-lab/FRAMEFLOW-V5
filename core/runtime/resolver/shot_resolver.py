"""T20 — deterministic, read-only Shot/Asset/Artifact resolution.

The resolver reads one SQLite snapshot and returns a typed projection.  It
does not use exported manifests, does not inspect arbitrary user paths, and
does not call any builder, provider, queue, or persistence mutation API.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator
from sqlalchemy import select

from core.schemas.runtime_mvp import metadata
from frameflow.idempotency import canonical_json


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SHOT_SPEC_SCHEMA = PROJECT_ROOT / "core" / "schemas" / "shot_spec_v2.2.schema.json"


@dataclass(frozen=True, slots=True)
class ResolutionIssue:
    """A small typed issue vocabulary local to T20."""

    code: str
    message: str
    blocking: bool = True
    entity_type: str | None = None
    entity_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "blocking": self.blocking,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "details": _json_safe(self.details),
        }


@dataclass(frozen=True, slots=True)
class ResolvedArtifact:
    """The registered Artifact projection used by a resolved reference."""

    artifact_id: str
    type: str | None
    role: str | None
    path: str | None
    sha256: str | None
    version: str | None
    status: str | None
    project_id: str | None
    asset_id: str | None
    shot_id: str | None
    resolved: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "type": self.type,
            "role": self.role,
            "path": self.path,
            "sha256": self.sha256,
            "version": self.version,
            "status": self.status,
            "project_id": self.project_id,
            "asset_id": self.asset_id,
            "shot_id": self.shot_id,
            "resolved": self.resolved,
        }


@dataclass(frozen=True, slots=True)
class ResolvedAsset:
    """An Asset reference and its declared master Artifact."""

    asset_id: str
    type: str | None
    status: str | None
    version: str | None
    master_artifact: ResolvedArtifact | None
    resolved: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "type": self.type,
            "status": self.status,
            "version": self.version,
            "master_artifact": self.master_artifact.to_dict() if self.master_artifact else None,
            "resolved": self.resolved,
        }


@dataclass(frozen=True, slots=True)
class ResolvedShotContext:
    """Typed T20 output; no field is a persistence authority."""

    shot_id: str
    project_id: str | None
    sequence_id: str | None
    shot: Mapping[str, Any] | None
    shot_spec: Mapping[str, Any] | None
    characters: tuple[ResolvedAsset, ...]
    scene: ResolvedAsset | None
    props: tuple[ResolvedAsset, ...]
    first_frame: ResolvedArtifact | None
    last_frame: ResolvedArtifact | None
    camera: Any = None
    start_state: Any = None
    end_state: Any = None
    dialogue: str | None = None
    must_keep: tuple[str, ...] = ()
    must_avoid: tuple[str, ...] = ()
    issues: tuple[ResolutionIssue, ...] = ()
    ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "project_id": self.project_id,
            "sequence_id": self.sequence_id,
            "shot": _json_safe(self.shot),
            "shot_spec": _json_safe(self.shot_spec),
            "characters": [asset.to_dict() for asset in self.characters],
            "scene": self.scene.to_dict() if self.scene else None,
            "props": [asset.to_dict() for asset in self.props],
            "first_frame": self.first_frame.to_dict() if self.first_frame else None,
            "last_frame": self.last_frame.to_dict() if self.last_frame else None,
            "camera": _json_safe(self.camera),
            "start_state": _json_safe(self.start_state),
            "end_state": _json_safe(self.end_state),
            "dialogue": self.dialogue,
            "must_keep": list(self.must_keep),
            "must_avoid": list(self.must_avoid),
            "issues": [issue.to_dict() for issue in self.issues],
            "ready": self.ready,
        }


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bytes):
        return value.hex()
    return value


def _decode_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _row_dict(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _issue_sort_key(issue: ResolutionIssue) -> tuple[str, str, str, str]:
    return (
        issue.code,
        issue.entity_type or "",
        issue.entity_id or "",
        canonical_json(_json_safe(issue.details)),
    )


def _ref_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


@lru_cache(maxsize=4)
def _validator(schema_path: str) -> Draft202012Validator:
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


class ShotResolver:
    """Resolve a Shot from SQLite without creating or modifying state."""

    def __init__(self, store: Any, *, schema_path: Path | str = DEFAULT_SHOT_SPEC_SCHEMA) -> None:
        self.store = store
        self.schema_path = Path(schema_path).resolve(strict=False)

    def _invalid_context(
        self,
        shot_id: str,
        issues: Sequence[ResolutionIssue],
        *,
        project_id: str | None = None,
        sequence_id: str | None = None,
        shot: Mapping[str, Any] | None = None,
        shot_spec: Mapping[str, Any] | None = None,
    ) -> ResolvedShotContext:
        ordered = tuple(sorted(issues, key=_issue_sort_key))
        return ResolvedShotContext(
            shot_id=shot_id,
            project_id=project_id,
            sequence_id=sequence_id,
            shot=_json_safe(shot),
            shot_spec=_json_safe(shot_spec),
            characters=(),
            scene=None,
            props=(),
            first_frame=None,
            last_frame=None,
            issues=ordered,
            ready=False,
        )

    @staticmethod
    def _artifact_projection(row: Mapping[str, Any] | None, artifact_id: str) -> ResolvedArtifact:
        if row is None:
            return ResolvedArtifact(
                artifact_id=artifact_id,
                type=None,
                role=None,
                path=None,
                sha256=None,
                version=None,
                status=None,
                project_id=None,
                asset_id=None,
                shot_id=None,
                resolved=False,
            )
        return ResolvedArtifact(
            artifact_id=artifact_id,
            type=str(row.get("type")) if row.get("type") is not None else None,
            role=str(row.get("role")) if row.get("role") is not None else None,
            path=str(row.get("path")) if row.get("path") is not None else None,
            sha256=str(row.get("sha256")) if row.get("sha256") is not None else None,
            version=str(row.get("version")) if row.get("version") is not None else None,
            status=str(row.get("status")) if row.get("status") is not None else None,
            project_id=str(row.get("project_id")) if row.get("project_id") is not None else None,
            asset_id=str(row.get("asset_id")) if row.get("asset_id") is not None else None,
            shot_id=str(row.get("shot_id")) if row.get("shot_id") is not None else None,
            resolved=True,
        )

    @staticmethod
    def _asset_projection(row: Mapping[str, Any] | None, asset_id: str) -> ResolvedAsset:
        if row is None:
            return ResolvedAsset(asset_id, None, None, None, None, False)
        return ResolvedAsset(
            asset_id=asset_id,
            type=str(row.get("type")) if row.get("type") is not None else None,
            status=str(row.get("status")) if row.get("status") is not None else None,
            version=str(row.get("version")) if row.get("version") is not None else None,
            master_artifact=None,
            resolved=True,
        )

    def _validate_artifact(
        self,
        row: Mapping[str, Any] | None,
        artifact_id: str,
        *,
        project_id: str,
        expected_asset_id: str | None,
        shot_id: str,
        direct: bool,
        issues: list[ResolutionIssue],
    ) -> ResolvedArtifact:
        artifact = self._artifact_projection(row, artifact_id)
        if row is None:
            issues.append(
                ResolutionIssue(
                    "DIRECT_ARTIFACT_NOT_FOUND" if direct else "ARTIFACT_NOT_FOUND",
                    "Referenced Artifact row does not exist.",
                    entity_type="artifact",
                    entity_id=artifact_id,
                )
            )
            return artifact
        if artifact.project_id != project_id:
            issues.append(
                ResolutionIssue(
                    "PROJECT_MISMATCH",
                    "Referenced Artifact belongs to another project.",
                    entity_type="artifact",
                    entity_id=artifact_id,
                    details={"expected_project_id": project_id, "actual_project_id": artifact.project_id},
                )
            )
        if expected_asset_id is not None and artifact.asset_id != expected_asset_id:
            issues.append(
                ResolutionIssue(
                    "ARTIFACT_ASSET_MISMATCH",
                    "Artifact.asset_id does not match the Asset master reference.",
                    entity_type="artifact",
                    entity_id=artifact_id,
                    details={"expected_asset_id": expected_asset_id, "actual_asset_id": artifact.asset_id},
                )
            )
        if direct and artifact.shot_id is not None and artifact.shot_id != shot_id:
            issues.append(
                ResolutionIssue(
                    "SHOT_MISMATCH",
                    "Direct frame Artifact belongs to another Shot.",
                    entity_type="artifact",
                    entity_id=artifact_id,
                    details={"expected_shot_id": shot_id, "actual_shot_id": artifact.shot_id},
                )
            )
        missing_fields = [
            name for name, value in (
                ("path", artifact.path),
                ("sha256", artifact.sha256),
                ("version", artifact.version),
            ) if not value
        ]
        if missing_fields:
            issues.append(
                ResolutionIssue(
                    "ARTIFACT_METADATA_INCOMPLETE",
                    "Referenced Artifact is missing required resolution metadata.",
                    entity_type="artifact",
                    entity_id=artifact_id,
                    details={"missing_fields": missing_fields},
                )
            )
        if (artifact.status or "").upper() == "ARCHIVED":
            issues.append(
                ResolutionIssue(
                    "ARTIFACT_ARCHIVED",
                    "Referenced Artifact has observed ARCHIVED status; no replacement is selected.",
                    blocking=False,
                    entity_type="artifact",
                    entity_id=artifact_id,
                )
            )
        elif (artifact.status or "").upper() not in {"DRAFT", "CANDIDATE", "APPROVED", "LOCKED", "READY"}:
            issues.append(
                ResolutionIssue(
                    "ARTIFACT_STATUS_OBSERVED",
                    "Artifact status is returned as observed because downstream eligibility is not frozen in the Runtime contract.",
                    blocking=False,
                    entity_type="artifact",
                    entity_id=artifact_id,
                    details={"status": artifact.status},
                )
            )
        return ResolvedArtifact(
            artifact_id=artifact.artifact_id,
            type=artifact.type,
            role=artifact.role,
            path=artifact.path,
            sha256=artifact.sha256,
            version=artifact.version,
            status=artifact.status,
            project_id=artifact.project_id,
            asset_id=artifact.asset_id,
            shot_id=artifact.shot_id,
            resolved=not any(
            issue.blocking and issue.entity_type == "artifact" and issue.entity_id == artifact_id
            for issue in issues
            ),
        )

    def _resolve_asset(
        self,
        asset_id: str,
        *,
        project_id: str,
        shot_id: str,
        assets: Mapping[str, Mapping[str, Any]],
        artifacts: Mapping[str, Mapping[str, Any]],
        issues: list[ResolutionIssue],
    ) -> ResolvedAsset:
        row = assets.get(asset_id)
        asset = self._asset_projection(row, asset_id)
        if row is None:
            issues.append(
                ResolutionIssue("ASSET_NOT_FOUND", "Referenced Asset row does not exist.", entity_type="asset", entity_id=asset_id)
            )
            return asset
        if str(row.get("project_id")) != project_id:
            issues.append(
                ResolutionIssue(
                    "PROJECT_MISMATCH",
                    "Referenced Asset belongs to another project.",
                    entity_type="asset",
                    entity_id=asset_id,
                    details={"expected_project_id": project_id, "actual_project_id": row.get("project_id")},
                )
            )
        status = (asset.status or "").upper()
        if status not in {"DRAFT", "CANDIDATE", "APPROVED", "LOCKED"}:
            issues.append(
                ResolutionIssue(
                    "ASSET_STATUS_OBSERVED",
                    "Asset status is returned as observed; no downstream eligibility rule is frozen for T20.",
                    blocking=False,
                    entity_type="asset",
                    entity_id=asset_id,
                    details={"status": asset.status},
                )
            )
        master_id = str(row.get("master_artifact_id") or "")
        if not master_id:
            issues.append(
                ResolutionIssue(
                    "MASTER_ARTIFACT_MISSING",
                    "Asset.master_artifact_id is null or empty.",
                    entity_type="asset",
                    entity_id=asset_id,
                )
            )
            return asset
        master = self._validate_artifact(
            artifacts.get(master_id),
            master_id,
            project_id=project_id,
            expected_asset_id=asset_id,
            shot_id=shot_id,
            direct=False,
            issues=issues,
        )
        blocking_for_asset = any(
            issue.blocking and issue.entity_id in {asset_id, master_id}
            and issue.entity_type in {"asset", "artifact"}
            for issue in issues
        )
        return ResolvedAsset(
            asset_id=asset.asset_id,
            type=asset.type,
            status=asset.status,
            version=asset.version,
            master_artifact=master,
            resolved=not blocking_for_asset,
        )

    def resolve(self, shot_id: str) -> ResolvedShotContext:
        shot_id = str(shot_id)
        issues: list[ResolutionIssue] = []
        if not shot_id:
            return self._invalid_context(
                shot_id,
                [ResolutionIssue("SHOT_NOT_FOUND", "Shot ID is empty.", entity_type="shot", entity_id=shot_id)],
            )

        table = metadata.tables
        # Every SELECT below shares one ordinary connection snapshot.  There
        # is deliberately no INSERT, UPDATE, DELETE, event, or file call.
        with self.store.connection() as connection:
            shot_row = connection.execute(
                select(table["shots"]).where(table["shots"].c.id == shot_id)
            ).mappings().first()
            if shot_row is None:
                return self._invalid_context(
                    shot_id,
                    [ResolutionIssue("SHOT_NOT_FOUND", "Shot row does not exist.", entity_type="shot", entity_id=shot_id)],
                )
            shot = _row_dict(shot_row) or {}
            project_id = str(shot.get("project_id") or "")
            sequence_id = str(shot.get("sequence_id") or "")
            project_row = connection.execute(
                select(table["projects"]).where(table["projects"].c.id == project_id)
            ).mappings().first()
            sequence_row = connection.execute(
                select(table["sequences"]).where(table["sequences"].c.id == sequence_id)
            ).mappings().first()
            asset_rows = connection.execute(select(table["assets"])).mappings().all()
            artifact_rows = connection.execute(select(table["artifacts"])).mappings().all()

        if project_row is None:
            issues.append(ResolutionIssue("PROJECT_NOT_FOUND", "Shot.project_id does not resolve to a Project row.", entity_type="project", entity_id=project_id))
        if sequence_row is None:
            issues.append(ResolutionIssue("SEQUENCE_NOT_FOUND", "Shot.sequence_id does not resolve to a Sequence row.", entity_type="sequence", entity_id=sequence_id))
        elif str(sequence_row.get("project_id")) != project_id:
            issues.append(
                ResolutionIssue(
                    "PROJECT_MISMATCH",
                    "Sequence belongs to another project.",
                    entity_type="sequence",
                    entity_id=sequence_id,
                    details={"expected_project_id": project_id, "actual_project_id": sequence_row.get("project_id")},
                )
            )

        raw_spec = shot.get("shot_spec_json")
        spec = _decode_json(raw_spec)
        if spec is None or not isinstance(spec, dict):
            issues.append(ResolutionIssue("INVALID_SHOT_SPEC", "shot_spec_json is not a valid JSON object.", entity_type="shot", entity_id=shot_id))
            return self._invalid_context(shot_id, issues, project_id=project_id, sequence_id=sequence_id, shot=shot)

        try:
            validation_errors = sorted(
                _validator(str(self.schema_path)).iter_errors(spec),
                key=lambda error: (tuple(str(item) for item in error.path), error.message),
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(f"ShotSpec schema contract could not be loaded: {self.schema_path}") from exc
        for error in validation_errors:
            issues.append(
                ResolutionIssue(
                    "INVALID_SHOT_SPEC",
                    "ShotSpec does not satisfy ShotSpec v2.2.",
                    entity_type="shot",
                    entity_id=shot_id,
                    details={
                        "path": [str(item) for item in error.path],
                        "validator": error.validator,
                        "message": error.message,
                    },
                )
            )
        if spec.get("shot_id") != shot_id:
            issues.append(
                ResolutionIssue(
                    "SHOT_SPEC_ID_MISMATCH",
                    "ShotSpec.shot_id does not match the database Shot ID.",
                    entity_type="shot",
                    entity_id=shot_id,
                    details={"expected": shot_id, "actual": spec.get("shot_id")},
                )
            )
        if spec.get("sequence_id") != sequence_id:
            issues.append(
                ResolutionIssue(
                    "SEQUENCE_MISMATCH",
                    "ShotSpec.sequence_id does not match the database Shot sequence.",
                    entity_type="shot",
                    entity_id=shot_id,
                    details={"expected": sequence_id, "actual": spec.get("sequence_id")},
                )
            )

        assets = {str(row["id"]): dict(row) for row in asset_rows}
        artifacts = {str(row["id"]): dict(row) for row in artifact_rows}
        characters: list[ResolvedAsset] = []
        props: list[ResolvedAsset] = []
        seen_refs: set[tuple[str, str]] = set()
        for field_name, output in (("characters", characters), ("props", props)):
            for index, asset_id in enumerate(_ref_list(spec.get(field_name))):
                key = (field_name, asset_id)
                if key in seen_refs:
                    issues.append(
                        ResolutionIssue(
                            "DUPLICATE_ASSET_REFERENCE",
                            "Duplicate Asset reference is preserved and reported; it is not silently deduplicated.",
                            entity_type="asset",
                            entity_id=asset_id,
                            details={"field": field_name, "index": index},
                        )
                    )
                seen_refs.add(key)
                output.append(self._resolve_asset(asset_id, project_id=project_id, shot_id=shot_id, assets=assets, artifacts=artifacts, issues=issues))

        scene_id = spec.get("scene") if isinstance(spec.get("scene"), str) else ""
        scene = self._resolve_asset(scene_id, project_id=project_id, shot_id=shot_id, assets=assets, artifacts=artifacts, issues=issues) if scene_id else None
        if not scene_id:
            issues.append(ResolutionIssue("ASSET_NOT_FOUND", "ShotSpec.scene is empty or not a string.", entity_type="shot", entity_id=shot_id))

        frame_values: list[ResolvedArtifact | None] = []
        for field_name, direct_label in (("first_frame_artifact_id", "first"), ("last_frame_artifact_id", "last")):
            artifact_id = spec.get(field_name)
            if artifact_id is None:
                issues.append(
                    ResolutionIssue(
                        "DIRECT_ARTIFACT_ABSENT",
                        f"ShotSpec.{field_name} is null; no replacement is selected.",
                        blocking=False,
                        entity_type="shot",
                        entity_id=shot_id,
                        details={"frame": direct_label},
                    )
                )
                frame_values.append(None)
                continue
            if not isinstance(artifact_id, str) or not artifact_id:
                issues.append(ResolutionIssue("DIRECT_ARTIFACT_NOT_FOUND", f"ShotSpec.{field_name} is not a valid Artifact ID.", entity_type="shot", entity_id=shot_id))
                frame_values.append(None)
                continue
            frame_values.append(
                self._validate_artifact(
                    artifacts.get(artifact_id),
                    artifact_id,
                    project_id=project_id,
                    expected_asset_id=None,
                    shot_id=shot_id,
                    direct=True,
                    issues=issues,
                )
            )

        ordered_issues = tuple(sorted(issues, key=_issue_sort_key))
        ready = not any(issue.blocking for issue in ordered_issues)
        return ResolvedShotContext(
            shot_id=shot_id,
            project_id=project_id,
            sequence_id=sequence_id,
            shot=_json_safe(shot),
            shot_spec=_json_safe(spec),
            characters=tuple(characters),
            scene=scene,
            props=tuple(props),
            first_frame=frame_values[0],
            last_frame=frame_values[1],
            camera=spec.get("camera"),
            start_state=spec.get("start_state"),
            end_state=spec.get("end_state"),
            dialogue=spec.get("dialogue"),
            must_keep=tuple(_ref_list(spec.get("must_keep"))),
            must_avoid=tuple(_ref_list(spec.get("must_avoid"))),
            issues=ordered_issues,
            ready=ready,
        )


def resolve_shot(store: Any, shot_id: str, *, schema_path: Path | str = DEFAULT_SHOT_SPEC_SCHEMA) -> ResolvedShotContext:
    """Convenience entry point for one read-only resolution."""

    return ShotResolver(store, schema_path=schema_path).resolve(shot_id)


__all__ = [
    "ResolutionIssue",
    "ResolvedArtifact",
    "ResolvedAsset",
    "ResolvedShotContext",
    "ShotResolver",
    "resolve_shot",
]
