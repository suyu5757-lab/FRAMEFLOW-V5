from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from core.runtime.continuity import ContinuityChecker, ContinuityStatus, check_continuity
from core.runtime.state_store import StateStore
from core.schemas.runtime_mvp import RUNTIME_TABLE_NAMES, metadata


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _spec(shot_id: str, sequence_id: str = "SQ1", *, continuity_in: Any = None, continuity_out: Any = None) -> dict[str, Any]:
    return {
        "shot_id": shot_id,
        "sequence_id": sequence_id,
        "duration_sec": 5,
        "story_purpose": "T14 structured continuity fixture",
        "characters": [],
        "scene": "S1",
        "props": [],
        "subject_action": "Hold position.",
        "camera": {"size": "medium", "height": "eye", "angle": "front", "motion": "static", "lens_intent": "natural", "composition": "centered"},
        "start_state": {"not_continuity": "start"},
        "end_state": {"not_continuity": "end"},
        "dialogue": "",
        "first_frame_artifact_id": None,
        "last_frame_artifact_id": None,
        "must_keep": [],
        "must_avoid": [],
        "status": "SPEC_READY",
        "expression": None,
        "performance_intent": None,
        "lighting": None,
        "weather": None,
        "time_of_day": None,
        "visual_style": None,
        "audio_cues": None,
        "quality_priority": None,
        "cost_priority": None,
        "continuity_state_in": continuity_in,
        "continuity_state_out": continuity_out,
        "provider_preferences": None,
        "reference_assets": None,
        "motion_reference_artifact_id": None,
    }


@pytest.fixture()
def fixture() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2] / ".tmp" / "t14-isolated" / uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    store = StateStore(root / "frameflow.db", initialize=True)
    store.create_project("P1", "T14 Fixture", "16:9", 24, 10)
    store.create_sequence("SQ1", "P1", 1)
    store.create_sequence("SQ2", "P1", 2)
    store.create_project("P2", "Other Project", "16:9", 24, 10)
    store.create_sequence("SQ_OTHER", "P2", 1)
    store.create_shot("SH_UP", "P1", "SQ1", _spec("SH_UP"))
    store.create_shot("SH_DOWN", "P1", "SQ1", _spec("SH_DOWN"))
    store.create_shot("SH_OTHER_SEQ", "P1", "SQ2", _spec("SH_OTHER_SEQ", "SQ2"))
    store.create_shot("SH_OTHER_PROJECT", "P2", "SQ_OTHER", _spec("SH_OTHER_PROJECT", "SQ_OTHER"))
    try:
        yield {"store": store, "root": root}
    finally:
        store.dispose()


def _set_spec(fixture: dict[str, Any], shot_id: str, *, continuity_in: Any = None, continuity_out: Any = None, sequence_id: str = "SQ1") -> None:
    fixture["store"].update_shot(
        shot_id,
        shot_spec=_spec(shot_id, sequence_id, continuity_in=continuity_in, continuity_out=continuity_out),
    )


def _set_runtime(fixture: dict[str, Any], shot_id: str, *, continuity_in: Any = None, continuity_out: Any = None) -> None:
    fixture["store"].update_shot(
        shot_id,
        continuity_in=None if continuity_in is None else json.dumps(continuity_in, ensure_ascii=False),
        continuity_out=None if continuity_out is None else json.dumps(continuity_out, ensure_ascii=False),
    )


def _files(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): _sha(path) for path in sorted(root.rglob("*")) if path.is_file()}


def _rows(store: StateStore) -> dict[str, list[dict[str, Any]]]:
    with store.connection() as connection:
        return {
            table_name: [dict(row) for row in connection.execute(metadata.tables[table_name].select()).mappings().all()]
            for table_name in RUNTIME_TABLE_NAMES
        }


def test_t14_c1_exact_match_uses_explicit_upstream_out_to_downstream_in(fixture: dict[str, Any]) -> None:
    value = {"character": {"C001": {"position": "door_left", "wardrobe": "blue_coat"}}, "prop": {"P001": {"owner": "C001"}}}
    _set_spec(fixture, "SH_UP", continuity_out=value)
    _set_spec(fixture, "SH_DOWN", continuity_in=value)
    result = check_continuity(fixture["store"], "SH_UP", "SH_DOWN")
    assert result.status == ContinuityStatus.MATCH.value
    assert result.conflicts == () and result.missing_in == () and result.missing_out == ()
    assert result.evidence["direction"] == "upstream.OUT -> downstream.IN"


def test_t14_c2_c3_c4_conflicts_are_nested_complete_and_deterministic(fixture: dict[str, Any]) -> None:
    upstream = {"character": {"C001": {"wardrobe": {"color": "blue", "size": "M"}}}, "prop": {"P001": {"owner": "C001"}}}
    downstream = {"character": {"C001": {"wardrobe": {"color": "red", "size": "L"}}}, "prop": {"P001": {"owner": "P999"}}}
    _set_spec(fixture, "SH_UP", continuity_out=upstream)
    _set_spec(fixture, "SH_DOWN", continuity_in=downstream)
    first = check_continuity(fixture["store"], "SH_UP", "SH_DOWN")
    second = check_continuity(fixture["store"], "SH_UP", "SH_DOWN")
    assert first == second and first.status == ContinuityStatus.CONFLICT.value
    assert [item.path for item in first.conflicts] == [
        "character.C001.wardrobe.color",
        "character.C001.wardrobe.size",
        "prop.P001.owner",
    ]
    assert first.conflicts[0].upstream_value == "blue" and first.conflicts[0].downstream_value == "red"
    assert all(item.reason == "explicit_value_mismatch" for item in first.conflicts)


def test_t14_c5_c6_c7_missing_data_is_not_a_conflict(fixture: dict[str, Any]) -> None:
    none = check_continuity(fixture["store"], "SH_UP", "SH_DOWN")
    assert none.status == ContinuityStatus.NOT_APPLICABLE.value

    _set_spec(fixture, "SH_UP", continuity_out={"a": 1, "nested": {"b": 2}})
    missing_in = check_continuity(fixture["store"], "SH_UP", "SH_DOWN")
    assert missing_in.status == ContinuityStatus.INCOMPLETE.value
    assert missing_in.missing_in == ("a", "nested.b") and not missing_in.conflicts

    _set_spec(fixture, "SH_UP")
    _set_spec(fixture, "SH_DOWN", continuity_in={"a": 1})
    missing_out = check_continuity(fixture["store"], "SH_UP", "SH_DOWN")
    assert missing_out.status == ContinuityStatus.INCOMPLETE.value
    assert missing_out.missing_out == ("a",) and not missing_out.conflicts


def test_t14_c8_c9_partial_overlap_preserves_matches_conflicts_and_missing(fixture: dict[str, Any]) -> None:
    _set_spec(fixture, "SH_UP", continuity_out={"a": 1, "b": 2})
    _set_spec(fixture, "SH_DOWN", continuity_in={"a": 1})
    partial = check_continuity(fixture["store"], "SH_UP", "SH_DOWN")
    assert partial.status == ContinuityStatus.INCOMPLETE.value and partial.compared_keys == ("a",)
    assert partial.missing_in == ("b",) and partial.conflicts == ()

    _set_spec(fixture, "SH_DOWN", continuity_in={"a": 9, "c": 3})
    mixed = check_continuity(fixture["store"], "SH_UP", "SH_DOWN")
    assert mixed.status == ContinuityStatus.CONFLICT.value
    assert mixed.compared_keys == ("a",) and mixed.missing_in == ("b",) and mixed.missing_out == ("c",)


def test_t14_c10_c14_runtime_authority_and_t13_boundary(fixture: dict[str, Any]) -> None:
    _set_spec(fixture, "SH_UP", continuity_out={"a": 1})
    _set_runtime(fixture, "SH_UP", continuity_out={"a": 1})
    _set_spec(fixture, "SH_DOWN", continuity_in={"a": 1})
    result = ContinuityChecker(fixture["store"]).check_pair("SH_UP", "SH_DOWN")
    assert result.status == ContinuityStatus.MATCH.value
    assert result.evidence["upstream"]["selected_source"] == "shots.continuity_out"
    assert result.evidence["upstream"]["corroborated_by"] == "shot_spec.continuity_state_out"

    _set_runtime(fixture, "SH_UP", continuity_out=None)
    fallback = ContinuityChecker(fixture["store"]).check_pair("SH_UP", "SH_DOWN")
    assert fallback.status == ContinuityStatus.MATCH.value
    assert fallback.evidence["upstream"]["selected_source"] == "shot_spec.continuity_state_out"


def test_t14_c11_c12_pair_validation_is_explicit_and_never_guesses_order(fixture: dict[str, Any]) -> None:
    checker = ContinuityChecker(fixture["store"])
    assert checker.check_pair("SH_UP", "SH_UP").status == ContinuityStatus.INVALID.value
    assert checker.check_pair("SH_UP", "MISSING").status == ContinuityStatus.INVALID.value
    assert checker.check_pair("SH_UP", "SH_OTHER_PROJECT").status == ContinuityStatus.INVALID.value
    assert checker.check_pair("SH_UP", "SH_OTHER_SEQ").status == ContinuityStatus.INVALID.value
    assert not hasattr(checker, "check_adjacent_shots")


def test_t14_c13_c15_malformed_and_unsupported_values_fail_closed(fixture: dict[str, Any]) -> None:
    _set_runtime(fixture, "SH_UP", continuity_out="{malformed")
    _set_spec(fixture, "SH_DOWN", continuity_in={"a": 1})
    malformed = check_continuity(fixture["store"], "SH_UP", "SH_DOWN")
    assert malformed.status == ContinuityStatus.UNKNOWN.value and malformed.issues[0].code == "MALFORMED_RUNTIME_CONTINUITY"

    _set_runtime(fixture, "SH_UP", continuity_out=5)
    unsupported = check_continuity(fixture["store"], "SH_UP", "SH_DOWN")
    assert unsupported.status == ContinuityStatus.UNKNOWN.value
    assert unsupported.issues[0].code == "MALFORMED_RUNTIME_CONTINUITY"

    _set_runtime(fixture, "SH_UP", continuity_out={"a": 1})
    _set_spec(fixture, "SH_UP", continuity_out={"a": 2})
    inconsistent = check_continuity(fixture["store"], "SH_UP", "SH_DOWN")
    assert inconsistent.status == ContinuityStatus.UNKNOWN.value
    assert inconsistent.issues[0].code == "INCONSISTENT_CONTINUITY_SOURCES"


def test_t14_c14_list_order_and_numeric_equality_are_exact(fixture: dict[str, Any]) -> None:
    _set_spec(fixture, "SH_UP", continuity_out={"items": ["a", "b"], "distance": 5})
    _set_spec(fixture, "SH_DOWN", continuity_in={"items": ["b", "a"], "distance": 5.0})
    result = check_continuity(fixture["store"], "SH_UP", "SH_DOWN")
    assert result.status == ContinuityStatus.CONFLICT.value
    assert [item.path for item in result.conflicts] == ["distance", "items"]


def test_t14_c13_projection_has_zero_side_effects(fixture: dict[str, Any]) -> None:
    before_rows = _rows(fixture["store"])
    before_files = _files(fixture["root"])
    first = check_continuity(fixture["store"], "SH_UP", "SH_DOWN")
    second = check_continuity(fixture["store"], "SH_UP", "SH_DOWN")
    after_rows = _rows(fixture["store"])
    after_files = _files(fixture["root"])
    assert first == second
    assert before_rows == after_rows and before_files == after_files
    assert len(before_rows["tasks"]) == len(after_rows["tasks"]) == 0
    assert len(before_rows["events"]) == len(after_rows["events"])
    json.dumps(first.to_dict(), ensure_ascii=False)
