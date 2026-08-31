from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from core.runtime.minimal_smoke import smoke_video
from core.runtime.mock_media import tiny_uncompressed_avi
from core.runtime.package_builder import PackageBuilder
from core.runtime.prompt import CanonicalPromptCompiler
from core.runtime.providers import MockProviderAdapter
from core.runtime.resolver import ShotResolver
from core.runtime.review import ExplicitReviewService
from core.runtime.state_store import StateStore


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _spec() -> dict[str, Any]:
    return {"shot_id": "SH_T48", "sequence_id": "SEQ_T48", "duration_sec": 1, "story_purpose": "T48 runtime closure fixture.", "characters": ["CHAR_T48"], "scene": "SCENE_T48", "props": ["PROP_T48"], "subject_action": "Walk one step.", "camera": {"size": "medium", "height": "eye", "angle": "front", "motion": "static", "lens_intent": "natural", "composition": "centered"}, "start_state": {"position": "start"}, "end_state": {"position": "end"}, "dialogue": "", "first_frame_artifact_id": "FRAME_FIRST", "last_frame_artifact_id": "FRAME_LAST", "must_keep": ["identity"], "must_avoid": ["extra characters"], "status": "SPEC_READY"}


@pytest.fixture()
def t48_bundle() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2] / ".tmp" / "t48-isolated" / uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    store = StateStore(root / "frameflow.db", initialize=True)
    projects = root / "projects"; project = projects / "PRJ_T48"
    store.create_project("PRJ_T48", "T48 Fixture", "16:9", 24, 1)
    store.create_sequence("SEQ_T48", "PRJ_T48", 1)
    store.create_shot("SH_T48", "PRJ_T48", "SEQ_T48", _spec())
    definitions = (("CHAR_T48", "character", "ART_CHAR"), ("SCENE_T48", "scene", "ART_SCENE"), ("PROP_T48", "prop", "ART_PROP"))
    for asset_id, asset_type, artifact_id in definitions:
        path = project / "assets" / asset_id / "master.png"; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(asset_id.encode("ascii"))
        store.create_asset(asset_id, "PRJ_T48", asset_type, "v1", status="APPROVED", master_artifact_id=artifact_id)
        store.create_artifact(artifact_id, "PRJ_T48", "image", "master", str(path), "v1", asset_id=asset_id, sha256=_sha(path), status="READY")
    for artifact_id, role in (("FRAME_FIRST", "first_frame"), ("FRAME_LAST", "last_frame")):
        path = project / "shots" / "SH_T48" / "references" / f"{artifact_id}.png"; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(artifact_id.encode("ascii"))
        store.create_artifact(artifact_id, "PRJ_T48", "image", role, str(path), "v1", shot_id="SH_T48", sha256=_sha(path), status="READY")
    source = project / "imports" / "mock-result.avi"; source.parent.mkdir(parents=True, exist_ok=True); source.write_bytes(tiny_uncompressed_avi())
    try:
        yield {"store": store, "root": root, "projects": projects, "project": project, "source": source}
    finally:
        store.dispose()


def _runtime_chain(bundle: dict[str, Any]) -> dict[str, Any]:
    store = bundle["store"]
    context = ShotResolver(store).resolve("SH_T48")
    compiled = CanonicalPromptCompiler().compile(context)
    assert context.ready and compiled.success and compiled.prompt is not None
    package = PackageBuilder(store, projects_root=bundle["projects"])
    queued = package.build(context, compiled.prompt); assert queued.task is not None
    assert package.worker().run_once().outcome.value == "succeeded"
    package_result = json.loads(package.tasks.get(queued.task["id"])["result_json"])
    store.create_generation("GEN_T48", "SH_T48", package_result["package_manifest_artifact_id"], "mock")
    provider = MockProviderAdapter(store, result_source_path=bundle["source"], provider_config={"fixture": "tiny-uncompressed-avi"})
    handoff = provider.prepare(compiled.prompt, context, generation_id="GEN_T48")
    assert handoff.submission_ready
    return {"context": context, "prompt": compiled.prompt, "package": package, "package_result": package_result, "provider": provider, "handoff": handoff}


def _submitted_and_imported(bundle: dict[str, Any], chain: dict[str, Any]) -> dict[str, Any]:
    provider, handoff = chain["provider"], chain["handoff"]
    submission = provider.submit(handoff); assert submission.task is not None
    assert provider.worker().run_once().outcome.value == "succeeded"
    available = provider.fetch("GEN_T48"); assert available.action == "MOCK_RESULT_AVAILABLE"
    imported = provider.import_result(handoff, source_path=available.data["source_path"], destination_name="mock-result.avi", version="mock-v1", expected_sha256=_sha(bundle["source"]))
    assert imported.task is not None and provider.worker().run_once().outcome.value == "succeeded"
    artifact = next(item for item in bundle["store"].list_artifacts() if item.get("generation_id") == "GEN_T48")
    return {"submission": submission, "available": available, "imported": imported, "artifact": artifact}


def test_t48_e1_full_runtime_closure_requires_explicit_approval(t48_bundle: dict[str, Any]) -> None:
    chain = _runtime_chain(t48_bundle)
    result = _submitted_and_imported(t48_bundle, chain)
    smoke = smoke_video(result["artifact"])
    reviews = ExplicitReviewService(t48_bundle["store"])
    assert smoke.passed and smoke.duration == 1.0
    artifact = result["artifact"]
    assert artifact["generation_id"] == "GEN_T48" and artifact["project_id"] == "PRJ_T48" and artifact["shot_id"] == "SH_T48"
    assert artifact["asset_id"] is None and artifact["role"] == "provider_result" and artifact["status"] == "READY"
    assert artifact["source_task_id"] == result["imported"].task["id"] and Path(artifact["path"]).is_file() and artifact["sha256"] == _sha(Path(artifact["path"]))
    assert json.loads(artifact["source_artifacts_json"])[0] == chain["package_result"]["package_manifest_artifact_id"]
    assert t48_bundle["store"].list("reviews") == [] and not reviews.post_ready("GEN_T48")
    approval = reviews.approve(generation_id="GEN_T48", result_artifact_id=result["artifact"]["id"], actor="human-test")
    assert approval.action == "TASK_QUEUED" and reviews.worker().run_once().outcome.value == "succeeded"
    review = t48_bundle["store"].list("reviews")[0]
    assert review["decision"] == "APPROVED" and reviews.post_ready("GEN_T48")
    assert t48_bundle["store"].get_generation("GEN_T48")["status"] == "QA_APPROVED"
    assert len(t48_bundle["store"].list("provider_submissions")) == 1
    assert any(event["event_type"] == "T48_EXPLICIT_APPROVAL" for event in t48_bundle["store"].list("events"))


def test_t48_e2_no_automatic_approval_then_explicit_action(t48_bundle: dict[str, Any]) -> None:
    chain = _runtime_chain(t48_bundle); result = _submitted_and_imported(t48_bundle, chain)
    reviews = ExplicitReviewService(t48_bundle["store"])
    assert smoke_video(result["artifact"]).passed
    assert not t48_bundle["store"].list("reviews") and not reviews.post_ready("GEN_T48")
    reviews.approve(generation_id="GEN_T48", result_artifact_id=result["artifact"]["id"], actor="director")
    assert reviews.worker().run_once().outcome.value == "succeeded" and reviews.post_ready("GEN_T48")


def test_t48_e3_undecodable_media_blocks_approval(t48_bundle: dict[str, Any]) -> None:
    t48_bundle["source"].write_bytes(b"not an AVI")
    chain = _runtime_chain(t48_bundle); result = _submitted_and_imported(t48_bundle, chain)
    smoke = smoke_video(result["artifact"]); reviews = ExplicitReviewService(t48_bundle["store"])
    assert not smoke.passed and smoke.code == "UNDECODABLE_MEDIA"
    rejected = reviews.approve(generation_id="GEN_T48", result_artifact_id=result["artifact"]["id"], actor="director")
    assert rejected.code == "SMOKE_REQUIRED" and not t48_bundle["store"].list("reviews") and not reviews.post_ready("GEN_T48")


def test_t48_e4_e7_e8_idempotency_wrong_generation_and_duplicate_import(t48_bundle: dict[str, Any]) -> None:
    chain = _runtime_chain(t48_bundle); provider, handoff = chain["provider"], chain["handoff"]
    first, second = provider.submit(handoff), provider.submit(handoff)
    assert first.task["id"] == second.task["id"] and provider.worker().run_once().outcome.value == "succeeded"
    assert len(t48_bundle["store"].list("provider_submissions")) == 1
    available = provider.fetch("GEN_T48")
    imported = provider.import_result(handoff, source_path=available.data["source_path"], destination_name="mock-result.avi", version="mock-v1", expected_sha256=_sha(t48_bundle["source"]))
    assert provider.worker().run_once().outcome.value == "succeeded"
    duplicate = provider.import_result(handoff, source_path=available.data["source_path"], destination_name="mock-result.avi", version="mock-v1", expected_sha256=_sha(t48_bundle["source"]))
    assert duplicate.task["id"] == imported.task["id"] and len([item for item in t48_bundle["store"].list_artifacts() if item.get("generation_id") == "GEN_T48"]) == 1
    wrong = provider.import_result(replace(handoff, generation_id="GEN_MISSING"), source_path=available.data["source_path"], destination_name="wrong.avi", version="mock-v1", expected_sha256=_sha(t48_bundle["source"]))
    assert wrong.task is not None and provider.worker().run_once().outcome.value == "failed"
    assert len([item for item in t48_bundle["store"].list_artifacts() if item.get("generation_id") == "GEN_T48"]) == 1


def test_t48_mock_provider_surface_is_local_and_typed(t48_bundle: dict[str, Any]) -> None:
    chain = _runtime_chain(t48_bundle); provider, handoff = chain["provider"], chain["handoff"]
    assert provider.fetch("GEN_T48").action == "MOCK_RESULT_PENDING"
    queued = provider.submit(handoff); assert provider.worker().run_once().outcome.value == "succeeded"
    submission = t48_bundle["store"].list("provider_submissions")[0]
    assert provider.reconcile(submission["id"]).action == "RECONCILED"
    assert provider.poll(submission["id"]).action == "RECONCILED"
    assert provider.fetch("GEN_T48").action == "MOCK_RESULT_AVAILABLE"
    assert provider.cancel(submission["id"]).action == "MOCK_CANCELLATION_NOT_REQUIRED"
    normalized = provider.normalize_result({"artifact_id": "ART_NORMAL", "project_id": "PRJ_T48", "shot_id": "SH_T48", "generation_id": "GEN_T48", "asset_id": None, "type": "video", "role": "provider_result", "path": str(t48_bundle["project"] / "shots" / "SH_T48" / "generations" / "GEN_T48" / "normalized.avi"), "sha256": "a" * 64, "version": "mock-v1", "source_task_id": "TASK_NORMAL", "source_artifacts": [chain["package_result"]["package_manifest_artifact_id"]]})
    assert normalized.action == "NORMALIZED"
