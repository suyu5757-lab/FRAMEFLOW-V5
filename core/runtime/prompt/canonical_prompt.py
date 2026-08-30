"""T23 deterministic, provider-agnostic Canonical Prompt compiler.

This module composes an already-resolved ``ResolvedShotContext``. It does not
query SQLite, resolve Asset IDs, read manifests, open Artifact paths, call an
LLM/provider, or persist a prompt/package. Prompt text is a semantic contract;
Artifact IDs and hashes remain structured provenance only.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from frameflow.idempotency import canonical_json

from core.runtime.resolver import ResolvedArtifact, ResolvedAsset, ResolvedShotContext


SHOT_SPEC_VERSION = "2.2"
CANONICAL_SECTION_NAMES = (
    "SUBJECT",
    "ACTION",
    "PERFORMANCE",
    "ENVIRONMENT",
    "CAMERA",
    "LIGHTING",
    "TIMING",
    "CONTINUITY",
    "AUDIO",
    "CONSTRAINTS",
)


@dataclass(frozen=True, slots=True)
class PromptCompileIssue:
    """A typed compiler issue; blocking issues prevent prompt creation."""

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
class CanonicalPrompt:
    """The in-memory T23 prompt contract."""

    shot_id: str
    shot_spec_version: str
    sections: tuple[tuple[str, str], ...]
    canonical_text: str
    source_artifact_ids: tuple[str, ...]
    warnings: tuple[PromptCompileIssue, ...] = ()
    prompt_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "shot_spec_version": self.shot_spec_version,
            "sections": [
                {"name": name, "text": text}
                for name, text in self.sections
            ],
            "canonical_text": self.canonical_text,
            "source_artifact_ids": list(self.source_artifact_ids),
            "warnings": [warning.to_dict() for warning in self.warnings],
            "prompt_sha256": self.prompt_sha256,
        }


@dataclass(frozen=True, slots=True)
class PromptCompileResult:
    """Success/failure envelope for Canonical Prompt compilation."""

    success: bool
    canonical_prompt: CanonicalPrompt | None = None
    issues: tuple[PromptCompileIssue, ...] = ()
    warnings: tuple[PromptCompileIssue, ...] = ()

    @property
    def prompt(self) -> CanonicalPrompt | None:
        """Short alias for callers that use ``result.prompt``."""

        return self.canonical_prompt

    @property
    def canonical_text(self) -> str | None:
        return self.canonical_prompt.canonical_text if self.canonical_prompt else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "canonical_prompt": self.canonical_prompt.to_dict() if self.canonical_prompt else None,
            "issues": [issue.to_dict() for issue in self.issues],
            "warnings": [warning.to_dict() for warning in self.warnings],
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


def _normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _text(value: Any, *, preserve: bool = False) -> str | None:
    if value is None:
        return None
    if isinstance(value, (Mapping, list, tuple)):
        rendered = canonical_json(_json_safe(value))
    else:
        rendered = _normalize_newlines(str(value))
    if preserve:
        return rendered
    rendered = "\n".join(line.rstrip() for line in rendered.strip().split("\n"))
    return rendered or None


def _value_or_none(value: Any) -> str:
    return _text(value) or "NONE"


def _list_lines(label: str, values: Sequence[Any]) -> list[str]:
    if not values:
        return [f"{label}: NONE"]
    return [f"{label}:", *[f"- {_text(value, preserve=True) or ''}" for value in values]]


def _asset_line(asset: ResolvedAsset, ordinal: int | None = None) -> str:
    prefix = f"{ordinal}. " if ordinal is not None else ""
    return (
        f"- {prefix}{asset.asset_id}"
        f" | type={_value_or_none(asset.type)}"
        f" | status={_value_or_none(asset.status)}"
        f" | version={_value_or_none(asset.version)}"
    )


def _asset_group(label: str, assets: Sequence[ResolvedAsset]) -> list[str]:
    if not assets:
        return [f"{label}: NONE"]
    return [f"{label}:", *[_asset_line(asset, index) for index, asset in enumerate(assets, 1)]]


def _state_lines(label: str, value: Any) -> list[str]:
    return [f"{label}: {_value_or_none(value)}"]


def _artifact_ids(context: ResolvedShotContext) -> tuple[str, ...]:
    values: list[str] = []

    def add(artifact: ResolvedArtifact | None) -> None:
        if artifact is not None and artifact.resolved and artifact.artifact_id:
            values.append(artifact.artifact_id)

    for asset in context.characters:
        add(asset.master_artifact)
    if context.scene is not None:
        add(context.scene.master_artifact)
    for asset in context.props:
        add(asset.master_artifact)
    add(context.first_frame)
    add(context.last_frame)
    return tuple(values)


def _warning_for_unresolved_optional_references(context: ResolvedShotContext) -> tuple[PromptCompileIssue, ...]:
    spec = context.shot_spec or {}
    warnings: list[PromptCompileIssue] = []
    # T20's current typed output does not expose resolved optional motion or
    # reference-asset entries. T23 never re-resolves them from raw IDs.
    if spec.get("motion_reference_artifact_id"):
        warnings.append(
            PromptCompileIssue(
                "OPTIONAL_REFERENCE_NOT_RESOLVED",
                "motion_reference_artifact_id was not part of the T20 resolved output and is not guessed or injected.",
                blocking=False,
                details={"field": "motion_reference_artifact_id"},
            )
        )
    if spec.get("reference_assets"):
        warnings.append(
            PromptCompileIssue(
                "OPTIONAL_REFERENCE_NOT_RESOLVED",
                "reference_assets were not part of the T20 resolved output and are not re-resolved by T23.",
                blocking=False,
                details={"field": "reference_assets"},
            )
        )
    return tuple(warnings)


def _resolver_issue(issue: Any) -> PromptCompileIssue:
    if hasattr(issue, "code"):
        details = getattr(issue, "details", {})
        return PromptCompileIssue(
            code="RESOLVER_NOT_READY",
            message="T20 ResolvedShotContext is not ready; Canonical Prompt compilation is blocked.",
            blocking=True,
            details={"resolver_code": getattr(issue, "code", "UNKNOWN"), "resolver_details": _json_safe(details)},
        )
    return PromptCompileIssue(
        "RESOLVER_NOT_READY",
        "T20 ResolvedShotContext is not ready; Canonical Prompt compilation is blocked.",
        details={"resolver_issue": _json_safe(issue)},
    )


class CanonicalPromptCompiler:
    """Pure compiler from T20 output to a fixed ten-section prompt."""

    def compile(self, context: ResolvedShotContext) -> PromptCompileResult:
        if not isinstance(context, ResolvedShotContext):
            return PromptCompileResult(
                success=False,
                issues=(PromptCompileIssue("INVALID_RESOLVED_CONTEXT", "T23 requires a T20 ResolvedShotContext."),),
            )
        if not context.ready:
            resolver_issues = tuple(_resolver_issue(issue) for issue in context.issues)
            if not resolver_issues:
                resolver_issues = (
                    PromptCompileIssue(
                        "RESOLVER_NOT_READY",
                        "T20 ResolvedShotContext is not ready; Canonical Prompt compilation is blocked.",
                    ),
                )
            return PromptCompileResult(success=False, issues=resolver_issues)
        if not isinstance(context.shot_spec, Mapping):
            return PromptCompileResult(
                success=False,
                issues=(PromptCompileIssue("INVALID_RESOLVED_CONTEXT", "Resolved context has no embedded ShotSpec."),),
            )

        spec = context.shot_spec
        camera = spec.get("camera") if isinstance(spec.get("camera"), Mapping) else {}
        lighting = spec.get("lighting")
        visual_style = spec.get("visual_style")
        weather = spec.get("weather")
        time_of_day = spec.get("time_of_day")
        continuity_in = spec.get("continuity_state_in")
        continuity_out = spec.get("continuity_state_out")
        optional_warnings = _warning_for_unresolved_optional_references(context)

        subject = [
            *_asset_group("Characters", context.characters),
            _asset_line(context.scene, 1) if context.scene is not None else "Scene: NONE",
            *_asset_group("Props", context.props),
        ]
        action = [
            f"subject_action: {_value_or_none(spec.get('subject_action'))}",
            *_state_lines("start_state", spec.get("start_state")),
            *_state_lines("end_state", spec.get("end_state")),
        ]
        performance = [
            f"expression: {_value_or_none(spec.get('expression'))}",
            f"performance_intent: {_value_or_none(spec.get('performance_intent'))}",
        ]
        environment = [
            f"scene_reference: {_value_or_none(context.scene.asset_id if context.scene else spec.get('scene'))}",
            f"weather: {_value_or_none(weather)}",
            f"time_of_day: {_value_or_none(time_of_day)}",
            f"visual_style: {_value_or_none(visual_style)}",
        ]
        camera_section = [
            f"size: {_value_or_none(camera.get('size'))}",
            f"height: {_value_or_none(camera.get('height'))}",
            f"angle: {_value_or_none(camera.get('angle'))}",
            f"motion: {_value_or_none(camera.get('motion'))}",
            f"lens_intent: {_value_or_none(camera.get('lens_intent'))}",
            f"composition: {_value_or_none(camera.get('composition'))}",
        ]
        lighting_section = [
            f"lighting: {_value_or_none(lighting)}",
            f"visual_style: {_value_or_none(visual_style)}",
        ]
        timing = [f"duration_sec: {_value_or_none(spec.get('duration_sec'))}"]
        continuity = [
            f"continuity_state_in: {_value_or_none(continuity_in)}",
            f"continuity_state_out: {_value_or_none(continuity_out)}",
            f"start_state: {_value_or_none(spec.get('start_state'))}",
            f"end_state: {_value_or_none(spec.get('end_state'))}",
            f"first_frame_reference: {'PRESENT' if context.first_frame else 'ABSENT'}",
            f"last_frame_reference: {'PRESENT' if context.last_frame else 'ABSENT'}",
        ]
        audio = [
            f"dialogue: {_text(spec.get('dialogue'), preserve=True) if spec.get('dialogue') is not None else 'NONE'}",
            f"audio_cues: {_value_or_none(spec.get('audio_cues'))}",
        ]
        constraints = [
            *_list_lines("must_keep", context.must_keep),
            *_list_lines("must_avoid", context.must_avoid),
        ]
        bodies = (
            subject,
            action,
            performance,
            environment,
            camera_section,
            lighting_section,
            timing,
            continuity,
            audio,
            constraints,
        )
        sections = tuple((name, "\n".join(lines)) for name, lines in zip(CANONICAL_SECTION_NAMES, bodies))
        canonical_text = "\n\n".join(f"[{name}]\n{body}" for name, body in sections)
        source_artifact_ids = _artifact_ids(context)
        prompt_sha256 = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
        prompt = CanonicalPrompt(
            shot_id=context.shot_id,
            shot_spec_version=SHOT_SPEC_VERSION,
            sections=sections,
            canonical_text=canonical_text,
            source_artifact_ids=source_artifact_ids,
            warnings=optional_warnings,
            prompt_sha256=prompt_sha256,
        )
        return PromptCompileResult(
            success=True,
            canonical_prompt=prompt,
            warnings=optional_warnings,
        )


def compile_canonical_prompt(context: ResolvedShotContext) -> PromptCompileResult:
    """Compile one T20 context without any external or persistent side effect."""

    return CanonicalPromptCompiler().compile(context)


__all__ = [
    "CANONICAL_SECTION_NAMES",
    "CanonicalPrompt",
    "CanonicalPromptCompiler",
    "PromptCompileIssue",
    "PromptCompileResult",
    "compile_canonical_prompt",
]
