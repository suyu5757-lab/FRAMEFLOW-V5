"""Pure v1 -> v2.2 ShotSpec compatibility migration.

The migration only transforms an in-memory ShotSpec mapping. It never opens a
database and never writes or rewrites assets. This makes the path safe to use
for dry-run migration tests before a later Runtime task adds persistence.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping


CORE_FIELDS = (
    "shot_id",
    "sequence_id",
    "duration_sec",
    "story_purpose",
    "characters",
    "scene",
    "props",
    "subject_action",
    "camera",
    "start_state",
    "end_state",
    "dialogue",
    "first_frame_artifact_id",
    "last_frame_artifact_id",
    "must_keep",
    "must_avoid",
    "status",
)

OPTIONAL_FIELDS = (
    "expression",
    "performance_intent",
    "lighting",
    "weather",
    "time_of_day",
    "visual_style",
    "audio_cues",
    "quality_priority",
    "cost_priority",
    "continuity_state_in",
    "continuity_state_out",
    "provider_preferences",
    "reference_assets",
    "motion_reference_artifact_id",
)

CAMERA_FIELDS = (
    "size",
    "height",
    "angle",
    "motion",
    "lens_intent",
    "composition",
)

_MISSING = object()


def _first(source: Mapping[str, Any], *names: str, default: Any = _MISSING) -> Any:
    for name in names:
        if name in source and source[name] is not None:
            return source[name]
    if default is not _MISSING:
        return default
    return None


def _as_text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _as_id(value: Any, default: str | None = None) -> str | None:
    if isinstance(value, Mapping):
        value = _first(value, "id", "asset_id", "assetId", "scene_id", "sceneId", "name")
    if value is None or value == "":
        return default
    return str(value)


def _as_id_list(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple)) else [value]
    result: list[str] = []
    for item in values:
        item_id = _as_id(item)
        if item_id:
            result.append(item_id)
    return result


def _as_object(value: Any) -> dict[str, Any]:
    return deepcopy(value) if isinstance(value, Mapping) else {}


def _as_duration(value: Any) -> int | float:
    if value is None:
        return 1.0
    if isinstance(value, bool):
        raise ValueError("duration must be a positive number")
    try:
        duration = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("duration must be a positive number") from exc
    if duration <= 0:
        raise ValueError("duration must be greater than zero")
    return int(duration) if duration.is_integer() else duration


def _as_camera(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, Mapping) else {}
    camera: dict[str, Any] = {}
    aliases = {
        "size": ("size",),
        "height": ("height",),
        "angle": ("angle",),
        "motion": ("motion",),
        "lens_intent": ("lens_intent", "lensIntent"),
        "composition": ("composition",),
    }
    for field in CAMERA_FIELDS:
        value = _first(source, *aliases[field], default=None)
        camera[field] = None if value is None else _as_text(value)
    return camera


def _as_status(value: Any) -> str:
    status = _as_text(value, "DRAFT").strip().upper().replace(" ", "_")
    aliases = {
        "APPROVED": "QA_APPROVED",
        "READY": "SPEC_READY",
        "GENERATED": "RESULT_READY",
    }
    return aliases.get(status, status if status else "DRAFT")


def _source_mapping(legacy: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = _first(legacy, "shot_spec", "shotSpec", default=None)
    return nested if isinstance(nested, Mapping) else legacy


def migrate_shot_spec_v1_to_v2_2(legacy: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a legacy V3/ShotSpec v1 mapping into canonical v2.2.

    Missing core values receive conservative defaults so the result can be
    validated. Unknown legacy keys are ignored rather than copied into the
    strict contract. The input mapping, including any nested asset records, is
    never mutated; LOCKED and APPROVED assets therefore cannot be rewritten by
    this function.
    """

    if not isinstance(legacy, Mapping):
        raise TypeError("legacy ShotSpec must be a mapping")

    source = _source_mapping(legacy)
    shot_id = _as_id(_first(source, "shot_id", "shotId", "id"))
    if not shot_id:
        raise ValueError("legacy ShotSpec requires shot_id or id")

    sequence_id = _as_id(_first(source, "sequence_id", "sequenceId"), default="SQ001")
    scene = _as_id(_first(source, "scene", "scene_id", "sceneId"), default="S_UNKNOWN")

    aliases: dict[str, tuple[str, ...]] = {
        "expression": ("expression",),
        "performance_intent": ("performance_intent", "performanceIntent"),
        "lighting": ("lighting",),
        "weather": ("weather",),
        "time_of_day": ("time_of_day", "timeOfDay"),
        "visual_style": ("visual_style", "visualStyle", "style"),
        "audio_cues": ("audio_cues", "audioCues"),
        "quality_priority": ("quality_priority", "qualityPriority"),
        "cost_priority": ("cost_priority", "costPriority"),
        "continuity_state_in": ("continuity_state_in", "continuityStateIn"),
        "continuity_state_out": ("continuity_state_out", "continuityStateOut"),
        "provider_preferences": ("provider_preferences", "providerPreferences"),
        "reference_assets": ("reference_assets", "referenceAssets"),
        "motion_reference_artifact_id": (
            "motion_reference_artifact_id",
            "motionReferenceArtifactId",
        ),
    }

    result: dict[str, Any] = {
        "shot_id": shot_id,
        "sequence_id": sequence_id,
        "duration_sec": _as_duration(_first(source, "duration_sec", "duration", "durationSec")),
        "story_purpose": _as_text(_first(source, "story_purpose", "storyPurpose", "purpose")),
        "characters": _as_id_list(_first(source, "characters", "character_ids", "characterIds")),
        "scene": scene,
        "props": _as_id_list(_first(source, "props", "prop_ids", "propIds", "assets")),
        "subject_action": _as_text(_first(source, "subject_action", "subjectAction", "action")),
        "camera": _as_camera(_first(source, "camera", default=None)),
        "start_state": _as_object(_first(source, "start_state", "startState")),
        "end_state": _as_object(_first(source, "end_state", "endState")),
        "dialogue": _as_text(_first(source, "dialogue")),
        "first_frame_artifact_id": _as_id(
            _first(source, "first_frame_artifact_id", "firstFrameArtifactId", "first_frame")
        ),
        "last_frame_artifact_id": _as_id(
            _first(source, "last_frame_artifact_id", "lastFrameArtifactId", "last_frame")
        ),
        "must_keep": _as_id_list(_first(source, "must_keep", "mustKeep")),
        "must_avoid": _as_id_list(_first(source, "must_avoid", "mustAvoid")),
        "status": _as_status(_first(source, "status", default="DRAFT")),
    }

    for field in OPTIONAL_FIELDS:
        value = _first(source, *aliases[field], default=None)
        result[field] = deepcopy(value)

    return result


def downgrade_shot_spec_v2_2_to_v1(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Produce a conservative legacy-shaped representation for rollback tests."""

    if not isinstance(spec, Mapping):
        raise TypeError("v2.2 ShotSpec must be a mapping")
    shot_id = _as_id(_first(spec, "shot_id"))
    if not shot_id:
        raise ValueError("v2.2 ShotSpec requires shot_id")
    return {
        "id": shot_id,
        "sequenceId": _as_id(_first(spec, "sequence_id"), default="SQ001"),
        "duration": _first(spec, "duration_sec", default=1.0),
        "purpose": _as_text(_first(spec, "story_purpose")),
        "characters": deepcopy(_first(spec, "characters", default=[])),
        "scene": _as_id(_first(spec, "scene"), default="S_UNKNOWN"),
        "props": deepcopy(_first(spec, "props", default=[])),
        "action": _as_text(_first(spec, "subject_action")),
        "camera": deepcopy(_first(spec, "camera", default={})),
        "startState": deepcopy(_first(spec, "start_state", default={})),
        "endState": deepcopy(_first(spec, "end_state", default={})),
        "dialogue": _as_text(_first(spec, "dialogue")),
        "firstFrameArtifactId": deepcopy(_first(spec, "first_frame_artifact_id")),
        "lastFrameArtifactId": deepcopy(_first(spec, "last_frame_artifact_id")),
        "mustKeep": deepcopy(_first(spec, "must_keep", default=[])),
        "mustAvoid": deepcopy(_first(spec, "must_avoid", default=[])),
        "status": _as_text(_first(spec, "status", default="DRAFT")).lower(),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direction", choices=("upgrade", "downgrade"), default="upgrade")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    source = json.loads(args.input.read_text(encoding="utf-8"))
    result = (
        migrate_shot_spec_v1_to_v2_2(source)
        if args.direction == "upgrade"
        else downgrade_shot_spec_v2_2_to_v1(source)
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
