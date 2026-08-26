from __future__ import annotations

import json
from pathlib import Path
from unittest import TestCase

from jsonschema import Draft202012Validator

from scripts.migrate_shot_spec_v1_to_v2_2 import migrate_shot_spec_v1_to_v2_2


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "core" / "schemas" / "shot_spec_v2.2.schema.json"

CORE_FIELDS = {
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
}
OPTIONAL_FIELDS = {
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
}


def canonical_core_shot() -> dict:
    return {
        "shot_id": "SH001",
        "sequence_id": "SQ001",
        "duration_sec": 4,
        "story_purpose": "Establish the crossing.",
        "characters": ["C001"],
        "scene": "S001",
        "props": ["P001"],
        "subject_action": "Walks into frame.",
        "camera": {
            "size": "medium",
            "height": "eye",
            "angle": "front",
            "motion": "static",
            "lens_intent": "natural",
            "composition": "centered",
        },
        "start_state": {},
        "end_state": {},
        "dialogue": "",
        "first_frame_artifact_id": None,
        "last_frame_artifact_id": None,
        "must_keep": ["identity"],
        "must_avoid": ["extra characters"],
        "status": "DRAFT",
    }


class ShotSpecV22SchemaTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def assert_valid(self, instance: dict) -> None:
        errors = sorted(self.validator.iter_errors(instance), key=lambda error: list(error.path))
        self.assertEqual([], errors, errors)

    def test_declares_17_core_and_14_optional_fields(self) -> None:
        properties = set(self.schema["properties"])
        self.assertEqual(CORE_FIELDS | OPTIONAL_FIELDS, properties)
        self.assertEqual(31, len(properties))
        self.assertEqual(CORE_FIELDS, set(self.schema["required"]))
        self.assertEqual(
            {"size", "height", "angle", "motion", "lens_intent", "composition"},
            set(self.schema["properties"]["camera"]["properties"]),
        )
        for field in OPTIONAL_FIELDS:
            self.assertIsNone(self.schema["properties"][field]["default"])

    def test_core_shot_is_valid_without_optional_extensions(self) -> None:
        self.assert_valid(canonical_core_shot())

    def test_invalid_input_is_rejected(self) -> None:
        missing_id = canonical_core_shot()
        del missing_id["shot_id"]
        self.assertTrue(list(self.validator.iter_errors(missing_id)))

        bad_duration = canonical_core_shot()
        bad_duration["duration_sec"] = 0
        self.assertTrue(list(self.validator.iter_errors(bad_duration)))

        bad_camera = canonical_core_shot()
        del bad_camera["camera"]["motion"]
        self.assertTrue(list(self.validator.iter_errors(bad_camera)))

        unknown_field = canonical_core_shot()
        unknown_field["provider_config"] = "must not leak into ShotSpec"
        self.assertTrue(list(self.validator.iter_errors(unknown_field)))

    def test_migrated_compatibility_example_is_valid_and_has_null_extensions(self) -> None:
        legacy = {
            "id": "SH001",
            "sequenceId": "SQ001",
            "duration": 4,
            "purpose": "Establish the crossing.",
            "characters": [{"id": "C001"}],
            "scene": {"id": "S001"},
            "props": [{"id": "P001"}],
            "action": "Walks into frame.",
        }
        migrated = migrate_shot_spec_v1_to_v2_2(legacy)
        self.assert_valid(migrated)
        self.assertEqual(17 + 14, len(migrated))
        self.assertTrue(all(migrated[field] is None for field in OPTIONAL_FIELDS))
