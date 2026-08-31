from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import insert

from core.runtime.package_builder import PackageBuilder
from core.runtime.prompt import CanonicalPromptCompiler
from core.runtime.resolver import ShotResolver
from core.runtime.shot_state import ShotStateProjector, get_shot_state
from core.runtime.state_store import StateStore
from core.schemas.runtime_mvp import RUNTIME_TABLE_NAMES, metadata


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _spec(*, status: str = "SPEC_READY", duration: int = 5, scene: str = "S1") -> dict[str, Any]:
    return {
        "shot_id": "SH1",
        "sequence_id": "SQ1",
        "duration_sec": duration,
        "story_purpose": "T13 projection fixture",
        "characters": ["C1"],
        "scene": scene,
        "props": ["P1"],
        "subject_action": "Walks into frame.",
        "camera": {"size": "medium", "height": "eye", "angle": "front", "motion": "static", "lens_intent": "natural", "composition": "centered"},
        "start_state": {"position": "start"},
        "end_state": {"position": "end"},
        "dialogue": "",
        "first_frame_artifact_id": "F1",
        "last_frame_artifact_id": "L1",
        "must_keep": ["identity"],
        "must_avoid": ["extra characters"],
        "status": status,
        "expression": None,
        "performance_intent": None,
        "lighting": None,
        "weather": None,
        "time_of_day": None,
        "visual_style": None,
        "audio_cues": None,
        "quality_priority": None,
        "cost_priority": None,
        "continuity_state_in": None,
        "continuity_state_out": None,
        "provider_preferences": None,
        "reference_assets": None,
        "motion_reference_artifact_id": None,
    }


@pytest.fixture()
def fixture() -> dict[str, Any]:
    # Match the already validated T16/T48 isolation mechanism.  The host
    # pytest tmp root can have inherited ACLs that reject SQLite operations.
    tmp_path = Path(__file__).resolve().parents[2] / ".tmp" / "t13-isolated" / uuid4().hex
    tmp_path.mkdir(parents=True, exist_ok=False)
    projects_root = tmp_path / "projects"
    project_root = projects_root / "P1"
    store = StateStore(tmp_path / "frameflow.db", initialize=True)
    store.create_project("P1", "T13 Fixture", "16:9", 24, 5)
    store.create_sequence("SQ1", "P1", 1)
    store.create_shot("SH1", "P1", "SQ1", _spec())

    def make_file(relative: str, content: bytes) -> Path:
        path = project_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    for asset_id, asset_type, artifact_id in (("C1", "character", "AC1"), ("S1", "scene", "AS1"), ("P1", "prop", "AP1")):
        path = make_file(f"assets/{asset_id}/master.png", asset_id.encode("ascii"))
        store.create_asset(asset_id, "P1", asset_type, "v1", status="APPROVED", master_artifact_id=artifact_id)
        store.create_artifact(artifact_id, "P1", "image", "master", str(path), "v1", asset_id=asset_id, sha256=_sha(path), status="READY")
    for artifact_id, role in (("F1", "first_frame"), ("L1", "last_frame")):
        path = make_file(f"shots/SH1/references/{artifact_id}.png", artifact_id.encode("ascii"))
        store.create_artifact(artifact_id, "P1", "image", role, str(path), "v1", shot_id="SH1", sha256=_sha(path), status="READY")
    try:
        yield {"store": store, "root": tmp_path, "projects_root": projects_root, "project_root": project_root}
    finally:
        store.dispose()


def _build_package(bundle: dict[str, Any], *, duration: int | None = None) -> str:
    store = bundle["store"]
    if duration is not None:
        spec = _spec(duration=duration)
        store.update_shot("SH1", shot_spec=spec)
    context = ShotResolver(store).resolve("SH1")
    prompt_result = CanonicalPromptCompiler().compile(context)
    assert context.ready and prompt_result.success and prompt_result.prompt is not None
    builder = PackageBuilder(store, projects_root=bundle["projects_root"])
    queued = builder.build(context, prompt_result.prompt)
    assert builder.worker().run_once().outcome.value == "succeeded"
    task = builder.tasks.get(queued.task["id"])
    return json.loads(task["result_json"])["package_manifest_artifact_id"]


def _create_generation(bundle: dict[str, Any], package_id: str, generation_id: str = "GEN1", *, status: str = "CREATED") -> None:
    bundle["store"].create_generation(generation_id, "SH1", package_id, "mock", status=status)


def _create_submission(bundle: dict[str, Any], generation_id: str = "GEN1", *, status: str = "SUBMITTED", submission_id: str = "PSUB1") -> None:
    with bundle["store"].transaction() as connection:
        connection.execute(
            insert(metadata.tables["provider_submissions"]).values(
                id=submission_id,
                generation_id=generation_id,
                provider="mock",
                idempotency_key=f"key:{submission_id}",
                request_hash="a" * 64,
                external_task_id="external-1" if status == "SUBMITTED" else None,
                attempt=1,
                status=status,
                submitted_at=datetime(2026, 8, 31, 10, 0) if status == "SUBMITTED" else None,
            )
        )


def _create_result(bundle: dict[str, Any], generation_id: str = "GEN1", artifact_id: str = "RESULT1") -> Path:
    path = bundle["project_root"] / "shots" / "SH1" / "generations" / generation_id / "result.avi"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"registered result")
    bundle["store"].create_artifact(artifact_id, "P1", "video", "provider_result", str(path), "result-v1", shot_id="SH1", sha256=_sha(path), generation_id=generation_id, status="READY")
    return path


def _create_review(bundle: dict[str, Any], generation_id: str = "GEN1", *, decision: str = "APPROVED", smoke: bool = True, review_id: str = "REV1") -> None:
    evidence = {"smoke": {"passed": smoke}}
    with bundle["store"].transaction() as connection:
        connection.execute(
            insert(metadata.tables["reviews"]).values(
                id=review_id,
                shot_id="SH1",
                generation_id=generation_id,
                qa_json=json.dumps(evidence, separators=(",", ":")),
                decision=decision,
            )
        )


def _rows_snapshot(store: StateStore) -> dict[str, list[dict[str, Any]]]:
    with store.connection() as connection:
        return {
            table_name: [dict(row) for row in connection.execute(metadata.tables[table_name].select()).mappings().all()]
            for table_name in RUNTIME_TABLE_NAMES
        }


def _files_snapshot(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): _sha(path) for path in sorted(root.rglob("*")) if path.is_file()}


def test_t13_s1_to_s3_spec_asset_projection(fixture: dict[str, Any]) -> None:
    store = fixture["store"]
    store.update_shot("SH1", shot_spec=_spec(status="DRAFT"))
    draft = get_shot_state(store, "SH1", projects_root=fixture["projects_root"])
    assert draft.spec_state == "DRAFT" and draft.summary_state == "DRAFT"

    store.update_shot("SH1", shot_spec=_spec(status="SPEC_READY", scene="MISSING_SCENE"))
    spec_ready = get_shot_state(store, "SH1", projects_root=fixture["projects_root"])
    assert spec_ready.spec_state == "SPEC_READY" and spec_ready.asset_state == "NOT_READY" and spec_ready.summary_state == "SPEC_READY"

    store.update_shot("SH1", shot_spec=_spec())
    asset_ready = get_shot_state(store, "SH1", projects_root=fixture["projects_root"])
    assert asset_ready.asset_state == "ASSET_READY" and asset_ready.summary_state == "ASSET_READY"


def test_t13_s4_package_ready_uses_t16_identity(fixture: dict[str, Any]) -> None:
    package_id = _build_package(fixture)
    state = get_shot_state(fixture["store"], "SH1", projects_root=fixture["projects_root"])
    assert state.package_state == "PACKAGE_READY" and state.summary_state == "PACKAGE_READY"
    assert state.current_package_artifact_id == package_id
    assert state.evidence["package_state"][0].entity_id == package_id


def test_t13_s5_to_s8_lifecycle_and_explicit_approval(fixture: dict[str, Any]) -> None:
    package_id = _build_package(fixture)
    _create_generation(fixture, package_id)
    _create_submission(fixture)
    submitted = get_shot_state(fixture["store"], "SH1", projects_root=fixture["projects_root"])
    assert submitted.generation_state == "SUBMITTED" and submitted.summary_state == "SUBMITTED"

    fixture["store"].update_generation("GEN1", status="GENERATING")
    generating = get_shot_state(fixture["store"], "SH1", projects_root=fixture["projects_root"])
    assert generating.generation_state == "GENERATING" and generating.summary_state == "GENERATING"

    _create_result(fixture)
    result_ready = get_shot_state(fixture["store"], "SH1", projects_root=fixture["projects_root"])
    assert result_ready.generation_state == "RESULT_READY" and result_ready.review_state == "AWAITING_REVIEW" and result_ready.summary_state == "RESULT_READY"

    _create_review(fixture)
    fixture["store"].update_generation("GEN1", status="QA_APPROVED")
    approved = get_shot_state(fixture["store"], "SH1", projects_root=fixture["projects_root"])
    assert approved.generation_state == "QA_APPROVED" and approved.review_state == "APPROVED"
    assert approved.post_state == "POST_READY" and approved.summary_state == "QA_APPROVED"


def test_t13_s9_smoke_without_human_approval_never_promotes(fixture: dict[str, Any]) -> None:
    package_id = _build_package(fixture)
    _create_generation(fixture, package_id, status="RESULT_READY")
    _create_result(fixture)
    state = get_shot_state(fixture["store"], "SH1", projects_root=fixture["projects_root"])
    assert state.summary_state == "RESULT_READY"
    assert state.summary_state != "QA_APPROVED" and state.post_state == "NOT_READY"


def test_t13_s10_to_s12_current_input_excludes_history(fixture: dict[str, Any]) -> None:
    old_package_id = _build_package(fixture)
    _create_generation(fixture, old_package_id, "GEN_OLD", status="QA_APPROVED")
    _create_result(fixture, "GEN_OLD", "RESULT_OLD")
    _create_review(fixture, "GEN_OLD", review_id="REV_OLD")

    new_package_id = _build_package(fixture, duration=6)
    _create_generation(fixture, new_package_id, "GEN_NEW", status="GENERATING")
    _create_submission(fixture, "GEN_NEW", submission_id="PSUB_NEW")
    state = get_shot_state(fixture["store"], "SH1", projects_root=fixture["projects_root"])
    assert state.current_package_artifact_id == new_package_id and state.current_generation_id == "GEN_NEW"
    assert state.summary_state == "GENERATING" and state.summary_state != "QA_APPROVED"

    fixture["store"].update_shot("SH1", shot_spec=_spec(duration=7))
    stale = get_shot_state(fixture["store"], "SH1", projects_root=fixture["projects_root"])
    assert stale.package_state == "NOT_READY" and stale.current_package_artifact_id is None
    assert stale.summary_state != "QA_APPROVED"


def test_t13_s13_retry_and_s14_delivery_are_honest(fixture: dict[str, Any]) -> None:
    package_id = _build_package(fixture)
    _create_generation(fixture, package_id)
    _create_submission(fixture, status="FAILED")
    retry = get_shot_state(fixture["store"], "SH1", projects_root=fixture["projects_root"])
    assert retry.generation_state == "RETRY_REQUIRED" and retry.summary_state == "RETRY_REQUIRED"
    assert retry.delivery_state == "NOT_DELIVERED" and retry.summary_state != "DELIVERED"


def test_t13_s15_projection_is_read_only_and_metadata_is_not_authority(fixture: dict[str, Any]) -> None:
    store = fixture["store"]
    store.update_shot("SH1", metadata="{not-json")
    before_rows = _rows_snapshot(store)
    before_files = _files_snapshot(fixture["root"])
    first = ShotStateProjector(store, projects_root=fixture["projects_root"]).get_shot_state("SH1")
    second = ShotStateProjector(store, projects_root=fixture["projects_root"]).get_shot_state("SH1")
    after_rows = _rows_snapshot(store)
    after_files = _files_snapshot(fixture["root"])
    assert first == second
    assert before_rows == after_rows and before_files == after_files
    assert any(issue.code == "METADATA_JSON_INVALID" and not issue.blocking for issue in first.issues)
    assert len(store.list("tasks")) == 0 and len(store.list("events")) == len(before_rows["events"])


def test_t13_s16_missing_and_inconsistent_rows_fail_closed(fixture: dict[str, Any]) -> None:
    missing = get_shot_state(fixture["store"], "MISSING", projects_root=fixture["projects_root"])
    assert missing.summary_state == "DRAFT" and any(issue.code == "SHOT_NOT_FOUND" for issue in missing.issues)

    package_id = _build_package(fixture)
    _create_generation(fixture, package_id, status="SUBMITTED")
    without_submission = get_shot_state(fixture["store"], "SH1", projects_root=fixture["projects_root"])
    assert without_submission.generation_state == "UNKNOWN" and without_submission.summary_state == "DRAFT"
    assert any(issue.code == "GENERATION_WITHOUT_SUBMISSION" for issue in without_submission.issues)

    with fixture["store"].transaction() as connection:
        connection.execute(insert(metadata.tables["reviews"]).values(id="ORPHAN_REV", shot_id="SH1", generation_id=None, qa_json="{}", decision="APPROVED"))
    orphan = get_shot_state(fixture["store"], "SH1", projects_root=fixture["projects_root"])
    assert any(issue.code == "ORPHAN_REVIEW" for issue in orphan.issues)


def test_t13_summary_derivation_is_explicit_and_mapping_friendly() -> None:
    from core.runtime.shot_state import derive_summary_state

    base = {"spec_state": "SPEC_READY", "asset_state": "ASSET_READY", "package_state": "PACKAGE_READY", "generation_state": "NOT_STARTED", "review_state": "NOT_STARTED", "post_state": "NOT_READY", "delivery_state": "NOT_DELIVERED"}
    assert derive_summary_state(base) == "PACKAGE_READY"
    assert derive_summary_state({"dimensions": {**base, "generation_state": "RESULT_READY"}}) == "RESULT_READY"
    assert derive_summary_state({**base, "generation_state": "UNKNOWN"}) == "DRAFT"
