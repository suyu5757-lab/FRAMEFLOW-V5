from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest import TestCase

from jsonschema import Draft202012Validator

from scripts.migrate_shot_spec_v1_to_v2_2 import (
    CORE_FIELDS,
    OPTIONAL_FIELDS,
    downgrade_shot_spec_v2_2_to_v1,
    migrate_shot_spec_v1_to_v2_2,
)


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (ROOT / "core" / "schemas" / "shot_spec_v2.2.schema.json").read_text(encoding="utf-8")
)
VALIDATOR = Draft202012Validator(SCHEMA)

LEGACY_FIXTURES = (
    {
        "id": "SH001",
        "sequenceId": "SQ001",
        "duration": 4,
        "purpose": "Establish the crossing.",
        "characters": [{"id": "C001"}],
        "scene": {"id": "S001"},
        "props": [{"id": "P001"}],
        "action": "Walks into frame.",
        "camera": {"size": "medium", "height": "eye", "angle": "front", "motion": "static"},
        "status": "approved",
    },
    {
        "shotId": "SH002",
        "sequence_id": "SQ001",
        "durationSec": 5,
        "storyPurpose": "Reveal the threat.",
        "characterIds": ["C001", "C002"],
        "sceneId": "S001",
        "propIds": ["P002"],
        "subjectAction": "Turns toward the sound.",
        "startState": {"facing": "left"},
        "endState": {"facing": "right"},
        "firstFrameArtifactId": "ART001",
        "lastFrameArtifactId": "ART002",
        "status": "ready",
        "visualStyle": "cinematic",
    },
    {
        "id": "SH003",
        "characters": [],
        "action": "Hold.",
    },
)


class ShotSpecMigrationTests(TestCase):
    def assert_valid_v22(self, value: dict) -> None:
        errors = list(VALIDATOR.iter_errors(value))
        self.assertEqual([], errors, errors)

    def test_three_legacy_shots_migrate_to_valid_v22(self) -> None:
        migrated = [migrate_shot_spec_v1_to_v2_2(fixture) for fixture in LEGACY_FIXTURES]
        for fixture, value in zip(LEGACY_FIXTURES, migrated):
            self.assert_valid_v22(value)
            self.assertEqual(fixture.get("id", fixture.get("shotId")), value["shot_id"])
            self.assertEqual(set(CORE_FIELDS) | set(OPTIONAL_FIELDS), set(value))
            self.assertEqual(6, len(value["camera"]))

    def test_missing_optional_extensions_are_explicit_null(self) -> None:
        value = migrate_shot_spec_v1_to_v2_2(LEGACY_FIXTURES[2])
        self.assertTrue(all(value[field] is None for field in OPTIONAL_FIELDS))
        self.assertEqual("SQ001", value["sequence_id"])
        self.assertEqual("S_UNKNOWN", value["scene"])
        self.assertEqual(1.0, value["duration_sec"])

    def test_locked_and_approved_assets_are_not_rewritten(self) -> None:
        legacy = copy.deepcopy(LEGACY_FIXTURES[0])
        legacy["assets"] = [
            {"id": "C001", "status": "LOCKED", "master": "master-v4"},
            {"id": "S001", "status": "APPROVED", "master": "scene-v2"},
        ]
        before = copy.deepcopy(legacy["assets"])
        migrate_shot_spec_v1_to_v2_2(legacy)
        self.assertEqual(before, legacy["assets"])

    def test_downgrade_then_upgrade_preserves_shot_identity_and_core_intent(self) -> None:
        upgraded = migrate_shot_spec_v1_to_v2_2(LEGACY_FIXTURES[0])
        downgraded = downgrade_shot_spec_v2_2_to_v1(upgraded)
        round_trip = migrate_shot_spec_v1_to_v2_2(downgraded)
        self.assert_valid_v22(round_trip)
        for field in ("shot_id", "sequence_id", "duration_sec", "story_purpose", "characters", "scene", "props", "subject_action"):
            self.assertEqual(upgraded[field], round_trip[field])

    def test_invalid_legacy_duration_is_rejected(self) -> None:
        legacy = {"id": "SH001", "duration": 0}
        with self.assertRaises(ValueError):
            migrate_shot_spec_v1_to_v2_2(legacy)
