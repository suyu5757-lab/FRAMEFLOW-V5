from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import insert, update

from core.schemas.runtime_mvp import RUNTIME_TABLE_NAMES, metadata
from core.runtime.resolver import ShotResolver
from core.runtime.state_store import StateStore


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _spec() -> dict[str, Any]:
    return {
        "shot_id": "SH1",
        "sequence_id": "SEQ1",
        "duration_sec": 4,
        "story_purpose": "Establish the crossing.",
        "characters": ["C1", "C2"],
        "scene": "SCENE1",
        "props": ["P1", "P2"],
        "subject_action": "Walks into frame.",
        "camera": {
            "size": "medium",
            "height": "eye",
            "angle": "front",
            "motion": "static",
            "lens_intent": "natural",
            "composition": "centered",
        },
        "start_state": {"door": "closed"},
        "end_state": {"door": "open"},
        "dialogue": "Keep moving.",
        "first_frame_artifact_id": "F1",
        "last_frame_artifact_id": "L1",
        "must_keep": ["identity", "wardrobe"],
        "must_avoid": ["extra characters"],
        "status": "SPEC_READY",
        "expression": "focused",
        "performance_intent": "measured",
        "lighting": "soft",
        "weather": None,
        "time_of_day": "dawn",
        "visual_style": {"palette": "cool"},
        "audio_cues": ["footsteps"],
        "quality_priority": "identity",
        "cost_priority": "normal",
        "continuity_state_in": None,
        "continuity_state_out": None,
        "provider_preferences": None,
        "reference_assets": None,
        "motion_reference_artifact_id": None,
    }


def _snapshot(store: StateStore) -> dict[str, list[str]]:
    snapshot: dict[str, list[str]] = {}
    with store.connection() as connection:
        for table_name in RUNTIME_TABLE_NAMES:
            rows = connection.execute(
                metadata.tables[table_name].select().order_by(*metadata.tables[table_name].primary_key.columns)
            ).mappings().all()
            snapshot[table_name] = [
                json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str)
                for row in rows
            ]
    return snapshot


def _files(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): _sha(path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _set_spec(bundle: dict[str, Any], **changes: Any) -> None:
    spec = dict(bundle["spec"])
    spec.update(changes)
    bundle["store"].update_shot("SH1", shot_spec=spec)
    bundle["spec"] = spec


def _issue_codes(context) -> set[str]:
    return {issue.code for issue in context.issues}


@pytest.fixture()
def bundle(tmp_path: Path):
    projects_root = tmp_path / "projects"
    project_root = projects_root / "P1"
    store = StateStore(tmp_path / "runtime.db", initialize=True)
    store.create_project("P1", "Resolver Test", "16:9", 24, 10)
    store.create_sequence("SEQ1", "P1", 1)
    spec = _spec()
    store.create_shot("SH1", "P1", "SEQ1", spec)

    assets = {
        "C1": ("character", "APPROVED", "M_C1"),
        "C2": ("character", "LOCKED", "M_C2"),
        "SCENE1": ("scene", "APPROVED", "M_SCENE1"),
        "P1": ("prop", "CANDIDATE", "M_P1"),
        "P2": ("prop", "DRAFT", "M_P2"),
    }
    for asset_id, (asset_type, status, master_id) in assets.items():
        store.create_asset(asset_id, "P1", asset_type, "v1", status=status, master_artifact_id=master_id)

    artifact_dir = project_root / "shots" / "SH1" / "references"
    for artifact_id, asset_id, role in (
        ("M_C1", "C1", "master"),
        ("M_C2", "C2", "master"),
        ("M_SCENE1", "SCENE1", "master"),
        ("M_P1", "P1", "master"),
        ("M_P2", "P2", "master"),
    ):
        path = artifact_dir / f"{artifact_id}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = artifact_id.encode("ascii")
        path.write_bytes(payload)
        store.create_artifact(
            artifact_id, "P1", "image", role, str(path), "v1",
            asset_id=asset_id, sha256=_sha(payload), status="APPROVED",
        )
    for artifact_id, role in (("F1", "first_frame"), ("L1", "last_frame")):
        path = artifact_dir / f"{artifact_id}.png"
        payload = artifact_id.encode("ascii")
        path.write_bytes(payload)
        store.create_artifact(
            artifact_id, "P1", "image", role, str(path), "v1",
            shot_id="SH1", sha256=_sha(payload), status="APPROVED",
        )

    value = {"store": store, "db_path": store.path, "projects_root": projects_root, "project_root": project_root, "spec": spec}
    try:
        yield value
    finally:
        store.dispose()


def test_t20_01_basic_resolution_is_ready(bundle) -> None:
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert context.ready is True
    assert context.issues == ()
    assert context.project_id == "P1"
    assert context.sequence_id == "SEQ1"


def test_t20_02_character_order_and_masters_are_preserved(bundle) -> None:
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert [asset.asset_id for asset in context.characters] == ["C1", "C2"]
    assert [asset.master_artifact.artifact_id for asset in context.characters] == ["M_C1", "M_C2"]


def test_t20_03_scene_resolution(bundle) -> None:
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert context.scene.asset_id == "SCENE1"
    assert context.scene.master_artifact.artifact_id == "M_SCENE1"


def test_t20_04_props_order_is_preserved(bundle) -> None:
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert [asset.asset_id for asset in context.props] == ["P1", "P2"]


def test_t20_05_first_frame_direct_reference(bundle) -> None:
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert context.first_frame.artifact_id == "F1"
    assert context.first_frame.shot_id == "SH1"


def test_t20_06_last_frame_direct_reference(bundle) -> None:
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert context.last_frame.artifact_id == "L1"
    assert context.last_frame.shot_id == "SH1"


def test_t20_07_missing_asset_reports_without_task_or_artifact_creation(bundle) -> None:
    _set_spec(bundle, characters=["C404", "C2"])
    before = _snapshot(bundle["store"])
    context = ShotResolver(bundle["store"]).resolve("SH1")
    after = _snapshot(bundle["store"])
    assert context.ready is False
    assert "ASSET_NOT_FOUND" in _issue_codes(context)
    assert before == after


def test_t20_08_null_master_reports_without_replacement(bundle) -> None:
    bundle["store"].update_asset("C1", master_artifact_id=None)
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert context.ready is False
    assert "MASTER_ARTIFACT_MISSING" in _issue_codes(context)
    assert context.characters[0].master_artifact is None


def test_t20_09_missing_master_artifact_row_reports(bundle) -> None:
    bundle["store"].update_asset("C1", master_artifact_id="ART404")
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert context.ready is False
    assert "ARTIFACT_NOT_FOUND" in _issue_codes(context)


def test_t20_10_cross_project_asset_is_rejected(bundle) -> None:
    store = bundle["store"]
    store.create_project("P2", "Other", "16:9", 24, 10)
    store.create_sequence("SEQ2", "P2", 1)
    store.create_asset("CROSS", "P2", "character", "v1", status="APPROVED", master_artifact_id="M_CROSS")
    path = bundle["projects_root"] / "P2" / "cross.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"cross"
    path.write_bytes(payload)
    store.create_artifact("M_CROSS", "P2", "image", "master", str(path), "v1", asset_id="CROSS", sha256=_sha(payload), status="APPROVED")
    _set_spec(bundle, characters=["CROSS", "C2"])
    context = ShotResolver(store).resolve("SH1")
    assert context.ready is False
    assert "PROJECT_MISMATCH" in _issue_codes(context)


def test_t20_11_asset_artifact_mismatch_is_rejected(bundle) -> None:
    bundle["store"].update_artifact("M_C1", asset_id="C2")
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert context.ready is False
    assert "ARTIFACT_ASSET_MISMATCH" in _issue_codes(context)


def test_t20_12_missing_direct_frame_does_not_create_first_frame_task(bundle) -> None:
    _set_spec(bundle, first_frame_artifact_id="ART404")
    before = _snapshot(bundle["store"])
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert context.ready is False
    assert "DIRECT_ARTIFACT_NOT_FOUND" in _issue_codes(context)
    assert before == _snapshot(bundle["store"])


def test_t20_13_locked_asset_resolves_existing_master_only(bundle) -> None:
    before = _snapshot(bundle["store"])
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert context.characters[1].status == "LOCKED"
    assert context.characters[1].master_artifact.artifact_id == "M_C2"
    assert before == _snapshot(bundle["store"])


def test_t20_14_retired_status_is_observed_without_replacement(bundle) -> None:
    bundle["store"].update_asset("C1", status="RETIRED")
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert context.characters[0].status == "RETIRED"
    assert any(issue.code == "ASSET_STATUS_OBSERVED" and not issue.blocking for issue in context.issues)
    assert context.characters[0].master_artifact.artifact_id == "M_C1"


def test_t20_15_all_runtime_rows_are_unchanged(bundle) -> None:
    before = _snapshot(bundle["store"])
    ShotResolver(bundle["store"]).resolve("SH1")
    assert before == _snapshot(bundle["store"])


def test_t20_16_tasks_and_events_have_zero_side_effect(bundle) -> None:
    store = bundle["store"]
    before = {name: len(store.list(name)) for name in ("tasks", "events")}
    ShotResolver(store).resolve("SH1")
    assert before == {name: len(store.list(name)) for name in ("tasks", "events")}


def test_t20_17_filesystem_inventory_and_hashes_are_unchanged(bundle) -> None:
    before = _files(bundle["projects_root"])
    ShotResolver(bundle["store"]).resolve("SH1")
    assert before == _files(bundle["projects_root"])


def test_t20_18_repeated_resolution_is_deterministic(bundle) -> None:
    resolver = ShotResolver(bundle["store"])
    assert resolver.resolve("SH1").to_dict() == resolver.resolve("SH1").to_dict()


def test_t20_19_exported_manifest_cannot_override_sqlite(bundle) -> None:
    manifest = bundle["project_root"] / "project_manifest.json"
    manifest.write_text(json.dumps({"artifact_id": "ART999", "asset_id": "C1"}), encoding="utf-8")
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert context.characters[0].master_artifact.artifact_id == "M_C1"
    assert "ART999" not in json.dumps(context.to_dict(), ensure_ascii=False)


def test_t20_20_reopen_state_store_returns_same_resolution(bundle) -> None:
    first = ShotResolver(bundle["store"]).resolve("SH1").to_dict()
    bundle["store"].dispose()
    reopened = StateStore(bundle["db_path"])
    try:
        assert ShotResolver(reopened).resolve("SH1").to_dict() == first
    finally:
        reopened.dispose()


def test_t20_21_invalid_shot_spec_is_typed_and_not_repaired(bundle) -> None:
    with bundle["store"].transaction() as connection:
        connection.execute(
            update(metadata.tables["shots"])
            .where(metadata.tables["shots"].c.id == "SH1")
            .values(shot_spec_json="{not-json")
        )
    before = _snapshot(bundle["store"])
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert context.ready is False
    assert "INVALID_SHOT_SPEC" in _issue_codes(context)
    assert before == _snapshot(bundle["store"])


def test_t20_22_shot_spec_identity_conflict_fails_closed(bundle) -> None:
    _set_spec(bundle, shot_id="OTHER_SHOT", sequence_id="OTHER_SEQUENCE")
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert context.ready is False
    assert {"SHOT_SPEC_ID_MISMATCH", "SEQUENCE_MISMATCH"}.issubset(_issue_codes(context))


def test_t20_23_duplicate_references_preserve_input_order_and_report(bundle) -> None:
    _set_spec(bundle, characters=["C1", "C1"])
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert [asset.asset_id for asset in context.characters] == ["C1", "C1"]
    assert "DUPLICATE_ASSET_REFERENCE" in _issue_codes(context)


def test_t20_24_direct_frame_wrong_shot_is_rejected(bundle) -> None:
    bundle["store"].create_shot("OTHER_SHOT", "P1", "SEQ1", _spec())
    bundle["store"].update_artifact("F1", shot_id="OTHER_SHOT")
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert context.ready is False
    assert "SHOT_MISMATCH" in _issue_codes(context)


def test_t20_25_archived_direct_artifact_is_observed_without_replacement(bundle) -> None:
    bundle["store"].update_artifact("F1", status="ARCHIVED")
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert context.first_frame.status == "ARCHIVED"
    assert "ARTIFACT_ARCHIVED" in _issue_codes(context)
    assert context.first_frame.artifact_id == "F1"


def test_t20_26_null_direct_frames_are_reported_as_nonblocking_absence(bundle) -> None:
    _set_spec(bundle, first_frame_artifact_id=None, last_frame_artifact_id=None)
    context = ShotResolver(bundle["store"]).resolve("SH1")
    assert context.ready is True
    assert sum(issue.code == "DIRECT_ARTIFACT_ABSENT" for issue in context.issues) == 2
