"""T13 read-only Shot State projection.

T13 deliberately adds no persistence surface.  The Runtime tables remain the
authority and this module only projects their current evidence into the
seven-dimensional Shot view used by operators.  In particular, the summary
state is a read model; it is never written back to ``shots``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select

from core.runtime.package_builder import PackageBuilder, PackagePreparation
from core.runtime.prompt import CanonicalPromptCompiler
from core.runtime.resolver import ResolvedShotContext, ShotResolver
from core.runtime.state_store import StateStore
from core.schemas.runtime_mvp import metadata
from frameflow.idempotency import canonical_json


SUMMARY_STATES = (
    "DRAFT",
    "SPEC_READY",
    "ASSET_READY",
    "PACKAGE_READY",
    "SUBMITTED",
    "GENERATING",
    "RESULT_READY",
    "QA_APPROVED",
    "RETRY_REQUIRED",
    "DELIVERED",
)

SPEC_STATES = ("DRAFT", "SPEC_READY", "UNKNOWN")
ASSET_STATES = ("NOT_READY", "ASSET_READY", "UNKNOWN")
PACKAGE_STATES = ("NOT_READY", "PACKAGE_READY", "UNKNOWN")
GENERATION_STATES = (
    "NOT_STARTED",
    "CREATED",
    "SUBMITTED",
    "GENERATING",
    "RESULT_READY",
    "QA_APPROVED",
    "RETRY_REQUIRED",
    "UNKNOWN",
)
REVIEW_STATES = ("NOT_STARTED", "AWAITING_REVIEW", "APPROVED", "RETRY_REQUIRED", "UNKNOWN")
POST_STATES = ("NOT_READY", "POST_READY", "UNKNOWN")
DELIVERY_STATES = ("NOT_DELIVERED", "DELIVERED", "UNKNOWN")

_SPEC_READY_STATUSES = frozenset(SUMMARY_STATES) - {"DRAFT"}
_SPEC_ISSUE_CODES = frozenset(
    {
        "INVALID_SHOT_SPEC",
        "SHOT_SPEC_ID_MISMATCH",
        "SEQUENCE_MISMATCH",
    }
)
_RETRY_REVIEW_DECISIONS = frozenset(
    {
        "REJECTED",
        "REJECT",
        "NEEDS_RETRY",
        "RETRY_REQUIRED",
        "RETRY-REQUIRED",
        "NEEDS_REVISION",
        "NEEDS REVISION",
    }
)


@dataclass(frozen=True, slots=True)
class StateEvidence:
    """A minimal pointer explaining why one projected state was selected."""

    entity_type: str
    entity_id: str
    detail: str | None = None

    def to_dict(self) -> dict[str, str]:
        result = {"entity_type": self.entity_type, "entity_id": self.entity_id}
        if self.detail:
            result["detail"] = self.detail
        return result


@dataclass(frozen=True, slots=True)
class ProjectionIssue:
    """Typed, fail-closed issue observed while projecting a Shot."""

    code: str
    message: str
    blocking: bool = True
    evidence: tuple[StateEvidence, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "blocking": self.blocking,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class ShotState7D:
    """The T13 typed read model for one Shot.

    The seven public state fields are derived strings, not persisted domain
    status fields.  ``evidence`` and ``reasons`` are intentionally small so a
    Workbench can explain a state without loading the complete EventLog.
    """

    shot_id: str
    spec_state: str
    asset_state: str
    package_state: str
    generation_state: str
    review_state: str
    post_state: str
    delivery_state: str
    summary_state: str
    summary_reason: str
    reasons: Mapping[str, str] = field(default_factory=dict)
    evidence: Mapping[str, tuple[StateEvidence, ...]] = field(default_factory=dict)
    issues: tuple[ProjectionIssue, ...] = ()
    current_package_artifact_id: str | None = None
    current_generation_id: str | None = None

    @property
    def dimensions(self) -> dict[str, str]:
        return {
            "spec_state": self.spec_state,
            "asset_state": self.asset_state,
            "package_state": self.package_state,
            "generation_state": self.generation_state,
            "review_state": self.review_state,
            "post_state": self.post_state,
            "delivery_state": self.delivery_state,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "dimensions": self.dimensions,
            "summary_state": self.summary_state,
            "summary_reason": self.summary_reason,
            "reasons": dict(self.reasons),
            "evidence": {
                key: [item.to_dict() for item in values]
                for key, values in self.evidence.items()
            },
            "issues": [issue.to_dict() for issue in self.issues],
            "current_package_artifact_id": self.current_package_artifact_id,
            "current_generation_id": self.current_generation_id,
        }


@dataclass(frozen=True, slots=True)
class _RuntimeSnapshot:
    shot: Mapping[str, Any] | None
    projects: tuple[Mapping[str, Any], ...]
    sequences: tuple[Mapping[str, Any], ...]
    assets: tuple[Mapping[str, Any], ...]
    artifacts: tuple[Mapping[str, Any], ...]
    tasks: tuple[Mapping[str, Any], ...]
    events: tuple[Mapping[str, Any], ...]
    generations: tuple[Mapping[str, Any], ...]
    submissions: tuple[Mapping[str, Any], ...]
    reviews: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class _PackageSelection:
    current: Mapping[str, Any] | None
    all_for_shot: tuple[Mapping[str, Any], ...]
    stale_ids: tuple[str, ...]
    preparation: PackagePreparation | None


@dataclass(frozen=True, slots=True)
class _GenerationSelection:
    current: Mapping[str, Any] | None
    submission: Mapping[str, Any] | None
    result_artifacts: tuple[Mapping[str, Any], ...]
    review: Mapping[str, Any] | None
    review_smoke_passed: bool


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _row_dict(row: Any) -> dict[str, Any] | None:
    return dict(row._mapping) if row is not None else None


def _decode(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _upper(value: Any) -> str:
    return _text(value).upper()


def _sort_key(row: Mapping[str, Any]) -> tuple[str, str]:
    """Stable newest-first key using persisted timestamps, then IDs."""

    return (_text(row.get("created_at")), _text(row.get("id")))


def _submission_sort_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _text(row.get("submitted_at")),
        _text(row.get("attempt")),
        _text(row.get("id")),
    )


def _evidence(entity_type: str, entity_id: Any, detail: str | None = None) -> StateEvidence:
    return StateEvidence(entity_type, _text(entity_id), detail)


def _issue(
    code: str,
    message: str,
    *,
    blocking: bool = True,
    evidence: Sequence[StateEvidence] = (),
) -> ProjectionIssue:
    return ProjectionIssue(code, message, blocking, tuple(evidence))


def _artifact_ids(context: ResolvedShotContext | None) -> tuple[str, ...]:
    if context is None:
        return ()
    values: list[str] = []
    for asset in (*context.characters, *(tuple([context.scene]) if context.scene else ()), *context.props):
        if asset.master_artifact is not None and asset.master_artifact.artifact_id:
            values.append(asset.master_artifact.artifact_id)
    for artifact in (context.first_frame, context.last_frame):
        if artifact is not None and artifact.artifact_id:
            values.append(artifact.artifact_id)
    return tuple(values)


def _review_retry(decision: Any) -> bool:
    return _upper(decision) in _RETRY_REVIEW_DECISIONS


def _smoke_passed(review: Mapping[str, Any] | None) -> bool:
    if review is None:
        return False
    evidence = _decode(review.get("qa_json"))
    return bool(isinstance(evidence, Mapping) and isinstance(evidence.get("smoke"), Mapping) and evidence["smoke"].get("passed") is True)


def derive_summary_state(state: ShotState7D | Mapping[str, Any]) -> str:
    """Derive the operator summary without storing or mutating it.

    The order is explicit and semantic, not lexical.  ``UNKNOWN`` is fail
    closed to ``DRAFT`` so malformed evidence cannot appear production-ready.
    """

    if isinstance(state, ShotState7D):
        values: Mapping[str, Any] = state.dimensions
    elif isinstance(state, Mapping):
        nested = state.get("dimensions")
        values = nested if isinstance(nested, Mapping) else state
    else:
        raise TypeError("derive_summary_state requires ShotState7D or a mapping")

    def value(name: str) -> str:
        raw = values.get(name)
        if isinstance(raw, Mapping):
            raw = raw.get("state")
        return _upper(raw)

    delivery = value("delivery_state")
    generation = value("generation_state")
    review = value("review_state")
    post = value("post_state")
    package = value("package_state")
    assets = value("asset_state")
    spec = value("spec_state")

    if delivery == "DELIVERED":
        return "DELIVERED"
    if "UNKNOWN" in {generation, review, post, package, assets, spec}:
        return "DRAFT"
    if spec != "SPEC_READY":
        return "DRAFT"
    if generation == "RETRY_REQUIRED" or review == "RETRY_REQUIRED":
        return "RETRY_REQUIRED"
    if generation == "QA_APPROVED" and review == "APPROVED" and post == "POST_READY":
        return "QA_APPROVED"
    if generation == "RESULT_READY":
        return "RESULT_READY"
    if generation == "GENERATING":
        return "GENERATING"
    if generation == "SUBMITTED":
        return "SUBMITTED"
    if package == "PACKAGE_READY":
        return "PACKAGE_READY"
    if assets == "ASSET_READY":
        return "ASSET_READY"
    if spec == "SPEC_READY":
        return "SPEC_READY"
    return "DRAFT"


class ShotStateProjector:
    """Project one Shot from the existing Runtime authority, read-only."""

    def __init__(
        self,
        store: StateStore,
        *,
        projects_root: Path | str | None = None,
        schema_path: Path | str | None = None,
    ) -> None:
        if not isinstance(store, StateStore):
            raise TypeError("ShotStateProjector requires a StateStore")
        self.store = store
        default_root = Path(store.path).parent / "projects" if str(store.path) != ":memory:" else Path("projects")
        self.projects_root = Path(projects_root or default_root).resolve(strict=False)
        self.schema_path = Path(schema_path).resolve(strict=False) if schema_path is not None else None

    def _snapshot(self, shot_id: str) -> _RuntimeSnapshot:
        tables = metadata.tables
        with self.store.connection() as connection:
            shot = _row_dict(connection.execute(select(tables["shots"]).where(tables["shots"].c.id == shot_id)).first())

            def rows(name: str) -> tuple[Mapping[str, Any], ...]:
                result = connection.execute(select(tables[name])).mappings().all()
                return tuple(dict(row) for row in result)

            return _RuntimeSnapshot(
                shot=shot,
                projects=rows("projects"),
                sequences=rows("sequences"),
                assets=rows("assets"),
                artifacts=rows("artifacts"),
                tasks=rows("tasks"),
                events=rows("events"),
                generations=rows("generations"),
                submissions=rows("provider_submissions"),
                reviews=rows("reviews"),
            )

    def _resolve(self, shot_id: str) -> ResolvedShotContext:
        resolver = ShotResolver(self.store, schema_path=self.schema_path) if self.schema_path is not None else ShotResolver(self.store)
        return resolver.resolve(shot_id)

    def _spec_projection(
        self,
        shot_id: str,
        context: ResolvedShotContext | None,
        issues: list[ProjectionIssue],
    ) -> tuple[str, str, tuple[StateEvidence, ...]]:
        if context is None or not isinstance(context.shot_spec, Mapping):
            return "UNKNOWN", "ShotSpec is missing or is not a JSON object.", (_evidence("shot", shot_id),)
        spec = context.shot_spec
        status = _upper(spec.get("status"))
        spec_issues = [item for item in context.issues if item.code in _SPEC_ISSUE_CODES and item.blocking]
        evidence = (_evidence("shot", shot_id),)
        if status == "DRAFT":
            if spec_issues:
                issues.append(_issue("SHOT_SPEC_INCOMPLETE", "ShotSpec is still a Draft and has validation issues.", blocking=False, evidence=evidence))
            return "DRAFT", "ShotSpec is explicitly DRAFT; it is not yet ready for production.", evidence
        if status in _SPEC_READY_STATUSES and not spec_issues:
            return "SPEC_READY", f"ShotSpec status is {status} and T20 identity validation passed.", evidence
        if spec_issues:
            issues.append(_issue("SHOT_SPEC_INVALID", "ShotSpec identity or schema validation failed; state is not promoted.", evidence=evidence))
        else:
            issues.append(_issue("SHOT_SPEC_STATUS_UNKNOWN", "ShotSpec uses an unknown status; state is not guessed.", evidence=evidence))
        return "UNKNOWN", "ShotSpec is not safely promotable from the existing contract.", evidence

    def _asset_projection(
        self,
        shot_id: str,
        context: ResolvedShotContext | None,
        spec_state: str,
        issues: list[ProjectionIssue],
    ) -> tuple[str, str, tuple[StateEvidence, ...]]:
        evidence: list[StateEvidence] = [_evidence("shot", shot_id)]
        if context is not None:
            for artifact_id in _artifact_ids(context):
                evidence.append(_evidence("artifact", artifact_id))
        if context is None or spec_state == "UNKNOWN":
            return "UNKNOWN", "Asset readiness cannot be projected without a valid ShotSpec context.", tuple(evidence)
        blocking = [item for item in context.issues if item.blocking and item.entity_type in {"asset", "artifact"}]
        if blocking or not context.ready:
            return "NOT_READY", "T20 has unresolved required Asset or reference evidence.", tuple(evidence)
        return "ASSET_READY", "T20 resolved all requested Asset and direct reference relationships.", tuple(evidence)

    def _expected_package(
        self,
        context: ResolvedShotContext | None,
    ) -> tuple[PackagePreparation | None, str]:
        if context is None or not context.ready:
            return None, "T20 is not ready, so no current package identity can be computed."
        compiled = CanonicalPromptCompiler().compile(context)
        if not compiled.success or compiled.prompt is None:
            return None, "T23 Canonical Prompt compilation is not ready, so no current package identity can be computed."
        preparation = PackageBuilder(self.store, projects_root=self.projects_root).prepare(context, compiled.prompt)
        if not preparation.ready:
            return preparation, "T16 rejected the current inputs; no valid current package identity exists."
        return preparation, "T16 computed a deterministic current package identity from the Shot, prompt, and references."

    def _valid_package(
        self,
        row: Mapping[str, Any],
        preparation: PackagePreparation | None,
        project_id: str,
        shot_id: str,
    ) -> bool:
        if preparation is None or not preparation.ready or not preparation.manifest:
            return False
        if _upper(row.get("status")) != "READY" or _text(row.get("role")).casefold() != "package_manifest":
            return False
        if _text(row.get("project_id")) != project_id or _text(row.get("shot_id")) != shot_id:
            return False
        path_text = _text(row.get("path"))
        if not path_text:
            return False
        path = Path(path_text).expanduser()
        resolved = path.resolve(strict=False)
        package_root = (self.projects_root / project_id / "shots" / shot_id / "packages").resolve(strict=False)
        if path.is_symlink() or not _inside(resolved, package_root) or not resolved.is_file():
            return False
        expected_sha = _text(row.get("sha256")).lower()
        if len(expected_sha) != 64:
            return False
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if digest != expected_sha:
            return False
        try:
            manifest = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        if not isinstance(manifest, Mapping):
            return False
        expected_manifest = preparation.manifest
        if canonical_json(manifest) != canonical_json(expected_manifest):
            return False
        return (
            _text(row.get("version")) == _text(preparation.package_version)
            and _text(manifest.get("logical_sha256")) == _text(preparation.logical_sha256)
            and _text(manifest.get("package_version")) == _text(preparation.package_version)
        )

    def _package_selection(
        self,
        snapshot: _RuntimeSnapshot,
        context: ResolvedShotContext | None,
        shot_id: str,
        project_id: str,
    ) -> _PackageSelection:
        preparation, _ = self._expected_package(context)
        all_for_shot = tuple(
            row
            for row in snapshot.artifacts
            if _text(row.get("shot_id")) == shot_id
            and _text(row.get("project_id")) == project_id
            and _text(row.get("role")).casefold() == "package_manifest"
        )
        matches = tuple(row for row in all_for_shot if self._valid_package(row, preparation, project_id, shot_id))
        current = sorted(matches, key=_sort_key, reverse=True)[0] if matches else None
        stale_ids = tuple(sorted(_text(row.get("id")) for row in all_for_shot if current is None or _text(row.get("id")) != _text(current.get("id"))))
        return _PackageSelection(current, all_for_shot, stale_ids, preparation)

    @staticmethod
    def _valid_result_artifact(row: Mapping[str, Any], project_id: str, shot_id: str, generation_id: str) -> bool:
        return (
            _text(row.get("project_id")) == project_id
            and _text(row.get("shot_id")) == shot_id
            and _text(row.get("generation_id")) == generation_id
            and _text(row.get("role")).casefold() == "provider_result"
            and bool(_text(row.get("path")) and _text(row.get("sha256")) and _text(row.get("version")))
        )

    def _generation_selection(
        self,
        snapshot: _RuntimeSnapshot,
        package: _PackageSelection,
        shot_id: str,
        project_id: str,
        issues: list[ProjectionIssue],
    ) -> _GenerationSelection:
        package_ids = {_text(package.current.get("id"))} if package.current is not None else set()
        package_rows_by_id = {
            _text(row.get("id")): row
            for row in snapshot.artifacts
            if _text(row.get("role")).casefold() == "package_manifest"
        }
        for row in snapshot.generations:
            if _text(row.get("shot_id")) != shot_id:
                continue
            package_id = _text(row.get("package_manifest_artifact_id"))
            if package_id and package_id not in package_rows_by_id:
                issues.append(
                    _issue(
                        "DANGLING_GENERATION_PACKAGE",
                        "Generation references a package Artifact row that does not exist; it is excluded from current state.",
                        evidence=(_evidence("generation", row.get("id")),),
                    )
                )
        candidates = [
            row
            for row in snapshot.generations
            if _text(row.get("shot_id")) == shot_id
            and _text(row.get("package_manifest_artifact_id")) in package_ids
        ]
        current = sorted(candidates, key=_sort_key, reverse=True)[0] if candidates else None
        if current is None:
            return _GenerationSelection(None, None, (), None, False)
        generation_id = _text(current.get("id"))
        submissions = [row for row in snapshot.submissions if _text(row.get("generation_id")) == generation_id]
        submission = sorted(submissions, key=_submission_sort_key, reverse=True)[0] if submissions else None
        result_artifacts = tuple(
            row
            for row in sorted(snapshot.artifacts, key=_sort_key, reverse=True)
            if self._valid_result_artifact(row, project_id, shot_id, generation_id)
        )
        reviews = [
            row
            for row in snapshot.reviews
            if _text(row.get("generation_id")) == generation_id and _text(row.get("shot_id")) == shot_id
        ]
        generation_ids = {_text(row.get("id")) for row in snapshot.generations if _text(row.get("shot_id")) == shot_id}
        for row in snapshot.reviews:
            if _text(row.get("shot_id")) == shot_id and _text(row.get("generation_id")) not in generation_ids:
                issues.append(
                    _issue(
                        "ORPHAN_REVIEW",
                        "Review references a missing or unrelated Generation; it is excluded from current state.",
                        evidence=(_evidence("review", row.get("id")),),
                    )
                )
        review = sorted(reviews, key=_sort_key, reverse=True)[0] if reviews else None
        return _GenerationSelection(current, submission, result_artifacts, review, _smoke_passed(review))

    def _generation_projection(
        self,
        selection: _GenerationSelection,
        issues: list[ProjectionIssue],
    ) -> tuple[str, str, tuple[StateEvidence, ...]]:
        if selection.current is None:
            return "NOT_STARTED", "No Generation is bound to the current package.", ()
        generation = selection.current
        generation_id = _text(generation.get("id"))
        evidence: list[StateEvidence] = [_evidence("generation", generation_id)]
        if selection.submission is not None:
            evidence.append(_evidence("provider_submission", selection.submission.get("id"), _upper(selection.submission.get("status"))))
        for artifact in selection.result_artifacts:
            evidence.append(_evidence("artifact", artifact.get("id"), "provider_result"))
        if selection.review is not None:
            evidence.append(_evidence("review", selection.review.get("id"), _upper(selection.review.get("decision"))))

        direct = _upper(generation.get("status"))
        submission_status = _upper(selection.submission.get("status")) if selection.submission is not None else ""
        review_retry = _review_retry(selection.review.get("decision")) if selection.review is not None else False
        if direct == "RETRY_REQUIRED" or submission_status == "FAILED" or review_retry:
            return "RETRY_REQUIRED", "Current Generation has explicit retry-required evidence.", tuple(evidence)
        if direct in {"SUBMITTED", "GENERATING"} and selection.submission is None:
            issues.append(_issue("GENERATION_WITHOUT_SUBMISSION", "Generation claims an active provider lifecycle without a ProviderSubmission row; state is unknown.", evidence=tuple(evidence)))
            return "UNKNOWN", "Generation lifecycle evidence is incomplete because ProviderSubmission is missing.", tuple(evidence)
        if direct == "RESULT_READY" and not selection.result_artifacts:
            issues.append(_issue("GENERATION_WITHOUT_RESULT_ARTIFACT", "Generation claims RESULT_READY without a valid provider result Artifact.", evidence=tuple(evidence)))
            return "UNKNOWN", "Generation RESULT_READY evidence is incomplete.", tuple(evidence)
        if direct == "QA_APPROVED" and not (
            selection.result_artifacts and selection.review is not None and _upper(selection.review.get("decision")) == "APPROVED" and selection.review_smoke_passed
        ):
            issues.append(_issue("QA_APPROVAL_EVIDENCE_INCOMPLETE", "Generation claims QA_APPROVED without T48 result, explicit Review, and smoke evidence.", evidence=tuple(evidence)))
        if selection.result_artifacts:
            if direct == "QA_APPROVED" and selection.review is not None and _upper(selection.review.get("decision")) == "APPROVED" and selection.review_smoke_passed:
                return "QA_APPROVED", "Current Generation has a result Artifact, explicit approved Review, and passing smoke evidence.", tuple(evidence)
            return "RESULT_READY", "Current Generation has a valid registered provider result Artifact awaiting final approval.", tuple(evidence)
        if direct == "GENERATING" or submission_status == "SUBMITTING":
            return "GENERATING", "Current Generation has active provider execution evidence.", tuple(evidence)
        if direct == "SUBMITTED" or submission_status == "SUBMITTED":
            return "SUBMITTED", "Current Generation has a persisted ProviderSubmission with submitted evidence.", tuple(evidence)
        if submission_status == "UNKNOWN":
            issues.append(_issue("PROVIDER_SUBMISSION_UNKNOWN", "Provider outcome is ambiguous and requires reconciliation; no retry is inferred.", evidence=tuple(evidence)))
            return "UNKNOWN", "ProviderSubmission is UNKNOWN; reconcile is required before promotion.", tuple(evidence)
        if direct in {"", "CREATED"} or direct in {"DRAFT", "SPEC_READY", "ASSET_READY", "PACKAGE_READY"}:
            return "CREATED", "A current Generation exists but no submit, result, or approval evidence is present.", tuple(evidence)
        issues.append(_issue("GENERATION_STATUS_UNKNOWN", "Generation uses an unknown status; state is not guessed.", evidence=tuple(evidence)))
        return "UNKNOWN", "Generation status is outside the observed Runtime contract.", tuple(evidence)

    def _review_projection(
        self,
        selection: _GenerationSelection,
    ) -> tuple[str, str, tuple[StateEvidence, ...]]:
        if selection.current is None:
            return "NOT_STARTED", "No current Generation is available for Review.", ()
        evidence = [_evidence("generation", selection.current.get("id"))]
        if selection.review is not None:
            decision = _upper(selection.review.get("decision"))
            evidence.append(_evidence("review", selection.review.get("id"), decision))
            if decision == "APPROVED":
                return "APPROVED", "An explicit Review decision is APPROVED; smoke evidence is reported separately.", tuple(evidence)
            if _review_retry(decision):
                return "RETRY_REQUIRED", "The current Review contains explicit retry/rejection evidence.", tuple(evidence)
            return "AWAITING_REVIEW", "A current Review exists but is not an approval decision.", tuple(evidence)
        if selection.result_artifacts:
            return "AWAITING_REVIEW", "A result Artifact exists but no explicit Review row exists.", tuple(evidence)
        return "NOT_STARTED", "No explicit Review evidence exists for the current Generation.", tuple(evidence)

    def get_shot_state(self, shot_id: str) -> ShotState7D:
        shot_id = _text(shot_id)
        snapshot = self._snapshot(shot_id)
        issues: list[ProjectionIssue] = []
        if snapshot.shot is None:
            missing = _evidence("shot", shot_id)
            issues.append(_issue("SHOT_NOT_FOUND", "Shot row does not exist.", evidence=(missing,)))
            dimensions = {
                "spec_state": "UNKNOWN",
                "asset_state": "UNKNOWN",
                "package_state": "UNKNOWN",
                "generation_state": "UNKNOWN",
                "review_state": "UNKNOWN",
                "post_state": "UNKNOWN",
                "delivery_state": "NOT_DELIVERED",
            }
            summary = derive_summary_state(dimensions)
            reasons = {key: "Shot row is missing; state is not guessed." for key in dimensions}
            evidence = {key: (missing,) for key in dimensions}
            return ShotState7D(shot_id, *(dimensions[key] for key in dimensions), summary, "Shot row is missing; no production readiness is inferred.", reasons, evidence, tuple(issues))

        project_id = _text(snapshot.shot.get("project_id"))
        context = self._resolve(shot_id)
        if _decode(snapshot.shot.get("metadata_json")) is None and _text(snapshot.shot.get("metadata_json")):
            issues.append(_issue("METADATA_JSON_INVALID", "shots.metadata_json is not valid JSON; it is ignored because it is not Runtime authority.", blocking=False, evidence=(_evidence("shot", shot_id),)))
        spec_state, spec_reason, spec_evidence = self._spec_projection(shot_id, context, issues)
        asset_state, asset_reason, asset_evidence = self._asset_projection(shot_id, context, spec_state, issues)
        package = self._package_selection(snapshot, context, shot_id, project_id)
        if package.current is not None:
            package_state = "PACKAGE_READY"
            package_reason = "A registered T16 package Artifact matches the current Shot input identity."
            package_evidence = (_evidence("artifact", package.current.get("id"), "current package_manifest"),)
        elif package.preparation is not None and not package.preparation.ready:
            package_state = "NOT_READY"
            package_reason = "The current input has no valid T16 package; existing package Artifacts remain history/stale."
            package_evidence = tuple(_evidence("artifact", item.get("id"), "historical or stale package") for item in package.all_for_shot)
        else:
            package_state = "NOT_READY"
            package_reason = "No registered package Artifact matches the current Shot input identity."
            package_evidence = (_evidence("shot", shot_id),)
        generation = self._generation_selection(snapshot, package, shot_id, project_id, issues)
        generation_state, generation_reason, generation_evidence = self._generation_projection(generation, issues)
        review_state, review_reason, review_evidence = self._review_projection(generation)
        if generation_state == "QA_APPROVED" and review_state == "APPROVED" and generation.review_smoke_passed:
            post_state = "POST_READY"
            post_reason = "T48 POST_READY evidence is complete for the current Generation."
            post_evidence = generation_evidence
        else:
            post_state = "NOT_READY"
            post_reason = "POST_READY requires current QA_APPROVED Generation, explicit approved Review, and passing smoke evidence."
            post_evidence = review_evidence or generation_evidence
        delivery_state = "NOT_DELIVERED"
        delivery_reason = "Delivery subsystem is not implemented in T13; no delivered state is fabricated."
        delivery_evidence = (_evidence("shot", shot_id),)

        reasons = {
            "spec_state": spec_reason,
            "asset_state": asset_reason,
            "package_state": package_reason,
            "generation_state": generation_reason,
            "review_state": review_reason,
            "post_state": post_reason,
            "delivery_state": delivery_reason,
        }
        evidence = {
            "spec_state": spec_evidence,
            "asset_state": asset_evidence,
            "package_state": package_evidence,
            "generation_state": generation_evidence,
            "review_state": review_evidence,
            "post_state": post_evidence,
            "delivery_state": delivery_evidence,
        }
        dimensions = {
            "spec_state": spec_state,
            "asset_state": asset_state,
            "package_state": package_state,
            "generation_state": generation_state,
            "review_state": review_state,
            "post_state": post_state,
            "delivery_state": delivery_state,
        }
        summary = derive_summary_state(dimensions)
        if summary == "QA_APPROVED":
            summary_reason = "Current Generation is explicitly approved and T48 POST_READY evidence is complete."
        elif summary == "RESULT_READY":
            summary_reason = "Current Generation has a registered result awaiting explicit Review approval."
        elif summary == "GENERATING":
            summary_reason = "Current Generation has active provider execution evidence."
        elif summary == "SUBMITTED":
            summary_reason = "Current Generation has a persisted provider submission."
        elif summary == "PACKAGE_READY":
            summary_reason = "Current Shot inputs have a valid current T16 package and no current Generation has advanced further."
        elif summary == "ASSET_READY":
            summary_reason = "T20 resolved the required assets/references; package construction is the next step."
        elif summary == "SPEC_READY":
            summary_reason = "ShotSpec is ready; required assets/references are not resolved yet."
        elif summary == "RETRY_REQUIRED":
            summary_reason = "Current Generation or Review contains explicit retry-required evidence."
        else:
            summary_reason = "Shot is not safely promotable from the current Runtime evidence."
        return ShotState7D(
            shot_id,
            spec_state,
            asset_state,
            package_state,
            generation_state,
            review_state,
            post_state,
            delivery_state,
            summary,
            summary_reason,
            reasons,
            evidence,
            tuple(issues),
            _text(package.current.get("id")) if package.current is not None else None,
            _text(generation.current.get("id")) if generation.current is not None else None,
        )


def get_shot_state(
    store: StateStore,
    shot_id: str,
    *,
    projects_root: Path | str | None = None,
    schema_path: Path | str | None = None,
) -> ShotState7D:
    """Convenience entry point for the pure T13 read model."""

    return ShotStateProjector(store, projects_root=projects_root, schema_path=schema_path).get_shot_state(shot_id)


project_shot_state = get_shot_state


__all__ = [
    "ASSET_STATES",
    "DELIVERY_STATES",
    "GENERATION_STATES",
    "PACKAGE_STATES",
    "POST_STATES",
    "ProjectionIssue",
    "REVIEW_STATES",
    "SUMMARY_STATES",
    "SPEC_STATES",
    "ShotState7D",
    "ShotStateProjector",
    "StateEvidence",
    "derive_summary_state",
    "get_shot_state",
    "project_shot_state",
]
