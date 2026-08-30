from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from core.runtime.idempotency import ProviderIdempotencyService, ProviderSubmissionStore
from core.runtime.prompt import CanonicalPrompt
from core.runtime.providers import (
    ManualAction,
    ManualProviderAdapter,
)
from core.runtime.resolver import ResolvedArtifact, ResolvedAsset, ResolvedShotContext
from core.runtime.state_store import StateStore, TaskState
from core.schemas.runtime_mvp import metadata


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(
    artifact_id: str,
    path: Path,
    *,
    role: str,
    asset_id: str | None = None,
    shot_id: str | None = None,
) -> ResolvedArtifact:
    return ResolvedArtifact(
        artifact_id=artifact_id,
        type="image",
        role=role,
        path=str(path),
        sha256=_sha(path),
        version="v1",
        status="APPROVED",
        project_id="P1",
        asset_id=asset_id,
        shot_id=shot_id,
        resolved=True,
    )


@pytest.fixture()
def manual_fixture(tmp_path: Path) -> dict[str, Any]:
    store = StateStore(tmp_path / "frameflow.db", initialize=True)
    projects_root = tmp_path / "projects"
    project_root = projects_root / "P1"
    package_path = project_root / "shots" / "SH1" / "packages" / "package.json"
    package_path.parent.mkdir(parents=True, exist_ok=True)
    package_path.write_text("pre-existing T16 fixture", encoding="utf-8")

    def make_file(relative: str, content: bytes) -> Path:
        path = project_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    character_path = make_file("assets/C1/master.png", b"character")
    scene_path = make_file("assets/S1/master.png", b"scene")
    prop_path = make_file("assets/P1/master.png", b"prop")
    first_path = make_file("shots/SH1/frames/first.png", b"first")
    last_path = make_file("shots/SH1/frames/last.png", b"last")

    store.create_project("P1", "Manual Test", "16:9", 24, 5)
    store.create_sequence("SEQ1", "P1", 1)
    store.create_shot("SH1", "P1", "SEQ1", {"shot_id": "SH1"})
    store.create_asset("C1", "P1", "character", "asset-v1", status="APPROVED", master_artifact_id="AC1")
    store.create_asset("S1", "P1", "scene", "asset-v1", status="APPROVED", master_artifact_id="AS1")
    store.create_asset("PROP1", "P1", "prop", "asset-v1", status="APPROVED", master_artifact_id="AP1")
    store.create_artifact("AC1", "P1", "image", "master", str(character_path), "v1", asset_id="C1", sha256=_sha(character_path), status="READY")
    store.create_artifact("AS1", "P1", "image", "master", str(scene_path), "v1", asset_id="S1", sha256=_sha(scene_path), status="READY")
    store.create_artifact("AP1", "P1", "image", "master", str(prop_path), "v1", asset_id="PROP1", sha256=_sha(prop_path), status="READY")
    store.create_artifact("F1", "P1", "image", "first_frame", str(first_path), "v1", shot_id="SH1", sha256=_sha(first_path), status="READY")
    store.create_artifact("L1", "P1", "image", "last_frame", str(last_path), "v1", shot_id="SH1", sha256=_sha(last_path), status="READY")
    store.create_artifact("PKG1", "P1", "json", "package_manifest", str(package_path), "package-v7", shot_id="SH1", sha256=_sha(package_path), status="READY")
    store.create_generation("GEN1", "SH1", "PKG1", "manual")

    context = ResolvedShotContext(
        shot_id="SH1",
        project_id="P1",
        sequence_id="SEQ1",
        shot={"id": "SH1", "project_id": "P1", "sequence_id": "SEQ1"},
        shot_spec={"shot_id": "SH1", "duration_sec": 5},
        characters=(
            ResolvedAsset("C1", "character", "APPROVED", "asset-v1", _artifact("AC1", character_path, role="master", asset_id="C1"), True),
        ),
        scene=ResolvedAsset("S1", "scene", "APPROVED", "asset-v1", _artifact("AS1", scene_path, role="master", asset_id="S1"), True),
        props=(
            ResolvedAsset("PROP1", "prop", "APPROVED", "asset-v1", _artifact("AP1", prop_path, role="master", asset_id="PROP1"), True),
        ),
        first_frame=_artifact("F1", first_path, role="first_frame", shot_id="SH1"),
        last_frame=_artifact("L1", last_path, role="last_frame", shot_id="SH1"),
        ready=True,
    )
    prompt_text = "[SUBJECT]\nC1 enters the room."
    prompt = CanonicalPrompt(
        shot_id="SH1",
        shot_spec_version="2.2",
        sections=(("SUBJECT", "C1 enters the room."),),
        canonical_text=prompt_text,
        source_artifact_ids=("AC1", "AS1", "AP1", "F1", "L1"),
        prompt_sha256=hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
    )
    try:
        yield {
            "store": store,
            "db_path": store.path,
            "projects_root": projects_root,
            "package_path": package_path,
            "context": context,
            "prompt": prompt,
            "adapter": ManualProviderAdapter(store, provider_config={"mode": "manual"}),
        }
    finally:
        store.dispose()


def _handoff(bundle: dict[str, Any]):
    return bundle["adapter"].prepare(bundle["prompt"], bundle["context"], generation_id="GEN1")


def _counts(store: StateStore) -> dict[str, int]:
    with store.connection() as connection:
        return {
            table: int(connection.execute(select(metadata.tables[table])).fetchall().__len__())
            for table in ("tasks", "events", "provider_submissions", "artifacts", "resource_locks", "reviews")
        }


def test_t26_01_prepare_returns_deterministic_ready_handoff(manual_fixture) -> None:
    first = _handoff(manual_fixture)
    second = _handoff(manual_fixture)
    assert first == second
    assert first.provider == "manual"
    assert first.submission_ready is True
    assert first.package_manifest_artifact_id == "PKG1"
    assert first.package_version == "package-v7"
    assert first.cost_status == "UNKNOWN"
    assert first.upload_checklist.to_dict()["first_frame_artifact_id"] == "F1"
    assert [item.artifact_id for item in first.reference_artifacts] == ["AC1", "AS1", "AP1", "F1", "L1"]


def test_t26_02_missing_package_is_reported_without_package_creation(manual_fixture) -> None:
    manual_fixture["package_path"].unlink()
    handoff = _handoff(manual_fixture)
    assert handoff.submission_ready is False
    assert any(issue.code == "PACKAGE_NOT_READY" for issue in handoff.issues)
    assert not list(manual_fixture["projects_root"].glob("**/canonical_prompt.md"))


def test_t26_03_submit_is_manual_handoff_only(manual_fixture) -> None:
    adapter = manual_fixture["adapter"]
    handoff = _handoff(manual_fixture)
    before = _counts(manual_fixture["store"])
    result = adapter.submit(handoff)
    after = _counts(manual_fixture["store"])
    assert result.action == ManualAction.MANUAL_ACTION_REQUIRED
    assert result.handoff.canonical_prompt_text == handoff.canonical_prompt_text
    assert before == after


def test_t26_04_provider_surface_never_fakes_remote_operations(manual_fixture) -> None:
    adapter = manual_fixture["adapter"]
    assert adapter.reconcile("PSUB_MISSING").action == ManualAction.MANUAL_CONFIRMATION_REQUIRED
    assert adapter.poll("PSUB_MISSING").action == ManualAction.MANUAL_CONFIRMATION_REQUIRED
    assert adapter.fetch("GEN1").action == ManualAction.MANUAL_IMPORT_REQUIRED
    assert adapter.cancel("PSUB_MISSING").action == ManualAction.MANUAL_CANCELLATION_REQUIRED


def test_t26_05_mark_submitted_uses_real_task_queue_worker_and_t09(manual_fixture) -> None:
    adapter = manual_fixture["adapter"]
    queued = adapter.mark_submitted(_handoff(manual_fixture), external_task_id="manual-job-001")
    assert queued.action == ManualAction.TASK_QUEUED
    assert manual_fixture["store"].list("provider_submissions") == []
    outcome = adapter.worker().run_once()
    assert outcome.outcome.value == "succeeded"
    submissions = manual_fixture["store"].list("provider_submissions")
    assert len(submissions) == 1
    assert submissions[0]["provider"] == "manual"
    assert submissions[0]["status"] == "SUBMITTED"
    assert submissions[0]["external_task_id"] == "manual-job-001"
    assert submissions[0]["submitted_at"] is not None


def test_t26_06_double_mark_submitted_is_one_task_and_one_submission(manual_fixture) -> None:
    adapter = manual_fixture["adapter"]
    handoff = _handoff(manual_fixture)
    first = adapter.mark_submitted(handoff, external_task_id="manual-job-002")
    second = adapter.mark_submitted(handoff, external_task_id="manual-job-002")
    assert first.task["id"] == second.task["id"]
    adapter.worker().run_once()
    assert len(manual_fixture["store"].list("provider_submissions")) == 1


def test_t26_06b_different_external_id_cannot_overwrite_submission(manual_fixture) -> None:
    adapter = manual_fixture["adapter"]
    handoff = _handoff(manual_fixture)
    adapter.mark_submitted(handoff, external_task_id="manual-job-002a")
    assert adapter.worker().run_once().outcome.value == "succeeded"
    conflicting = adapter.mark_submitted(handoff, external_task_id="manual-job-002b")
    assert conflicting.action == ManualAction.TASK_QUEUED
    assert adapter.worker().run_once().outcome.value == "failed"
    assert manual_fixture["store"].list("provider_submissions")[0]["external_task_id"] == "manual-job-002a"


def test_t26_07_same_key_different_request_is_rejected(manual_fixture) -> None:
    adapter = manual_fixture["adapter"]
    handoff = _handoff(manual_fixture)
    changed = replace(handoff, submission_request={**handoff.submission_request, "prompt_text": "tampered"})
    assert adapter.mark_submitted(handoff, external_task_id="manual-job-003").action == ManualAction.TASK_QUEUED
    conflict = adapter.mark_submitted(changed, external_task_id="manual-job-003")
    assert conflict.action == ManualAction.INVALID_REQUEST
    assert conflict.issues[0].code == "TASK_ID_CONFLICT"


def test_t26_08_external_task_id_first_same_and_different_conflict(manual_fixture) -> None:
    adapter = manual_fixture["adapter"]
    handoff = _handoff(manual_fixture)
    submission_store = ProviderSubmissionStore(manual_fixture["store"])
    reservation = submission_store.prepare_intent(
        generation_id="GEN1", project_id="P1", shot_id="SH1", provider="manual",
        idempotency_key=handoff.idempotency_key, request_hash=handoff.request_hash,
    )
    first = adapter.bind_external_task_id(reservation.submission["id"], external_task_id="manual-job-004")
    adapter.worker().run_once()
    same = adapter.bind_external_task_id(reservation.submission["id"], external_task_id="manual-job-004")
    different = adapter.bind_external_task_id(reservation.submission["id"], external_task_id="manual-job-005")
    assert first.action == ManualAction.TASK_QUEUED
    assert same.action == ManualAction.TASK_QUEUED
    assert different.action == ManualAction.TASK_QUEUED
    failed = adapter.worker().run_once()
    assert failed.outcome.value == "failed"
    assert manual_fixture["store"].list("provider_submissions")[0]["external_task_id"] == "manual-job-004"


def test_t26_09_restart_preserves_submission_state(manual_fixture) -> None:
    adapter = manual_fixture["adapter"]
    adapter.mark_submitted(_handoff(manual_fixture), external_task_id="manual-job-006")
    adapter.worker().run_once()
    manual_fixture["store"].dispose()
    reopened = StateStore(manual_fixture["db_path"], initialize=False)
    try:
        submission = reopened.list("provider_submissions")[0]
        assert submission["status"] == "SUBMITTED"
        assert submission["external_task_id"] == "manual-job-006"
        assert submission["submitted_at"] is not None
    finally:
        reopened.dispose()


def test_t26_10_result_import_creates_provenance_and_review_handoff(manual_fixture) -> None:
    adapter = manual_fixture["adapter"]
    source = manual_fixture["projects_root"] / "P1" / "imports" / "external-result.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"manual result")
    source_hash = _sha(source)
    queued = adapter.import_result(_handoff(manual_fixture), source_path=str(source), destination_name="result.mp4", version="result-v1", expected_sha256=source_hash)
    outcome = adapter.worker().run_once()
    assert queued.action == ManualAction.TASK_QUEUED
    assert outcome.outcome.value == "succeeded"
    artifact = next(
        row
        for row in manual_fixture["store"].list_artifacts()
        if row["generation_id"] == "GEN1"
    )
    assert artifact["generation_id"] == "GEN1"
    assert artifact["role"] == "provider_result"
    assert artifact["asset_id"] is None
    assert artifact["source_task_id"] == queued.task["id"]
    assert artifact["sha256"] == source_hash
    assert Path(artifact["path"]).resolve() == (manual_fixture["projects_root"] / "P1" / "shots" / "SH1" / "generations" / "GEN1" / "result.mp4").resolve()
    task = adapter.tasks.get(queued.task["id"])
    result_json = json.loads(task["result_json"])
    assert result_json["review_required"] is True
    assert result_json["result_artifact_ids"] == [artifact["id"]]
    assert manual_fixture["store"].list("reviews") == []
    assert _sha(source) == source_hash


def test_t26_11_import_two_results_supports_generation_one_to_many(manual_fixture) -> None:
    adapter = manual_fixture["adapter"]
    for name, content in (("result-a.mp4", b"a"), ("result-b.mp4", b"b")):
        source = manual_fixture["projects_root"] / "P1" / "imports" / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(content)
        adapter.import_result(_handoff(manual_fixture), source_path=str(source), destination_name=name, version="result-v1", expected_sha256=_sha(source))
        assert adapter.worker().run_once().outcome.value == "succeeded"
    results = [row for row in manual_fixture["store"].list_artifacts() if row["generation_id"] == "GEN1"]
    assert len(results) == 2
    assert {row["role"] for row in results} == {"provider_result"}


def test_t26_12_import_hash_mismatch_and_collision_fail_closed(manual_fixture) -> None:
    adapter = manual_fixture["adapter"]
    source = manual_fixture["projects_root"] / "P1" / "imports" / "bad-result.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"source")
    mismatch = adapter.import_result(_handoff(manual_fixture), source_path=str(source), destination_name="bad.mp4", version="result-v1", expected_sha256="0" * 64)
    assert adapter.worker().run_once().outcome.value == "failed"
    assert mismatch.task is not None
    assert not [row for row in manual_fixture["store"].list_artifacts() if row["generation_id"] == "GEN1"]

    destination = manual_fixture["projects_root"] / "P1" / "shots" / "SH1" / "generations" / "GEN1" / "collision.mp4"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"existing")
    collision = adapter.import_result(_handoff(manual_fixture), source_path=str(source), destination_name="collision.mp4", version="result-v1")
    assert adapter.worker().run_once().outcome.value == "failed"
    assert collision.task is not None
    assert not [row for row in manual_fixture["store"].list_artifacts() if row["generation_id"] == "GEN1"]


def test_t26_13_import_db_failure_compensates_and_retry_is_idempotent(manual_fixture) -> None:
    adapter = manual_fixture["adapter"]
    source = manual_fixture["projects_root"] / "P1" / "imports" / "retry-result.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"retry")
    queued = adapter.import_result(_handoff(manual_fixture), source_path=str(source), destination_name="retry.mp4", version="result-v1", expected_sha256=_sha(source))
    original = manual_fixture["store"].create_artifact

    def fail_db(*args, **kwargs):
        raise RuntimeError("injected artifact insert failure")

    manual_fixture["store"].create_artifact = fail_db
    try:
        assert adapter.worker().run_once().outcome.value == "failed"
    finally:
        manual_fixture["store"].create_artifact = original
    destination = manual_fixture["projects_root"] / "P1" / "shots" / "SH1" / "generations" / "GEN1" / "retry.mp4"
    assert not destination.exists()
    assert not [row for row in manual_fixture["store"].list_artifacts() if row["generation_id"] == "GEN1"]
    adapter.queue.retry(queued.task["id"])
    assert adapter.worker().run_once().outcome.value == "succeeded"
    assert len([row for row in manual_fixture["store"].list_artifacts() if row["generation_id"] == "GEN1"]) == 1


def test_t26_14_import_path_policy_rejects_arbitrary_source(manual_fixture) -> None:
    result = manual_fixture["adapter"].import_result(_handoff(manual_fixture), source_path=r"C:\Windows\system32\result.mp4", destination_name="result.mp4", version="result-v1")
    assert result.action == ManualAction.INVALID_REQUEST
    assert result.issues[0].code == "SOURCE_PATH_NOT_ALLOWED"
    assert manual_fixture["store"].list("tasks") == []


def test_t26_15_cross_generation_payload_fails_closed(manual_fixture) -> None:
    adapter = manual_fixture["adapter"]
    source = manual_fixture["projects_root"] / "P1" / "imports" / "cross.mp4"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"cross")
    tampered = replace(_handoff(manual_fixture), generation_id="GEN404")
    queued = adapter.import_result(tampered, source_path=str(source), destination_name="cross.mp4", version="result-v1")
    assert queued.action == ManualAction.TASK_QUEUED
    assert adapter.worker().run_once().outcome.value == "failed"
    assert not [row for row in manual_fixture["store"].list_artifacts() if row["generation_id"] == "GEN1"]


def test_t26_16_normalize_result_validates_binding_without_writing(manual_fixture) -> None:
    adapter = manual_fixture["adapter"]
    result = adapter.normalize_result(
        {
            "artifact_id": "ART_NORMALIZED",
            "project_id": "P1",
            "shot_id": "SH1",
            "generation_id": "GEN1",
            "asset_id": None,
            "type": "video",
            "role": "provider_result",
            "path": str(manual_fixture["projects_root"] / "P1" / "shots" / "SH1" / "generations" / "GEN1" / "normalized.mp4"),
            "sha256": "a" * 64,
            "version": "result-v1",
            "source_task_id": "TASK_IMPORT",
            "source_artifacts": ["PKG1", "F1", "L1"],
        }
    )
    assert result.action == ManualAction.NORMALIZED
    assert result.data["review_required"] is True
    assert not [row for row in manual_fixture["store"].list_artifacts() if row["generation_id"] == "GEN1"]


def test_t26_17_normalize_result_rejects_cross_project_and_non_result_asset(manual_fixture) -> None:
    adapter = manual_fixture["adapter"]
    result = adapter.normalize_result(
        {
            "artifact_id": "ART_BAD",
            "project_id": "P2",
            "shot_id": "SH1",
            "generation_id": "GEN1",
            "asset_id": "C1",
            "type": "video",
            "role": "provider_result",
            "path": "bad.mp4",
            "sha256": "a" * 64,
            "version": "result-v1",
            "source_task_id": "TASK_IMPORT",
            "source_artifacts": [],
        }
    )
    assert result.action == ManualAction.INVALID_REQUEST
    assert result.issues[0].code == "RESULT_ASSET_ID_MUST_BE_NULL"


def test_t26_18_forbidden_config_and_external_id_are_rejected(manual_fixture) -> None:
    with pytest.raises(Exception, match="INVALID_PROVIDER_CONFIG"):
        ManualProviderAdapter(manual_fixture["store"], provider_config={"shell": "no"})
    result = manual_fixture["adapter"].mark_submitted(_handoff(manual_fixture), external_task_id=r"C:\fake")
    assert result.action == ManualAction.INVALID_REQUEST
    assert result.issues[0].code == "INVALID_EXTERNAL_TASK_ID"


def test_t26_19_no_resource_lock_and_package_files_created_by_adapter(manual_fixture) -> None:
    adapter = manual_fixture["adapter"]
    before_files = sorted(str(path.relative_to(manual_fixture["projects_root"])) for path in manual_fixture["projects_root"].rglob("*"))
    with manual_fixture["store"].connection() as connection:
        before_locks = connection.execute(select(metadata.tables["resource_locks"])).fetchall()
    adapter.prepare(manual_fixture["prompt"], manual_fixture["context"], generation_id="GEN1")
    adapter.submit(_handoff(manual_fixture))
    after_files = sorted(str(path.relative_to(manual_fixture["projects_root"])) for path in manual_fixture["projects_root"].rglob("*"))
    assert before_files == after_files
    with manual_fixture["store"].connection() as connection:
        after_locks = connection.execute(select(metadata.tables["resource_locks"])).fetchall()
    assert before_locks == after_locks
    assert not any(Path(path).name in {"canonical_prompt.md", "provider_prompt.txt", "submit_manifest.json"} for path in manual_fixture["projects_root"].rglob("*"))
