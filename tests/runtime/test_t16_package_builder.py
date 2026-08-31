from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from core.runtime.package_builder import PackageAtomicJsonWriter, PackageBuilder
from core.runtime.prompt import CanonicalPrompt
from core.runtime.providers import ManualProviderAdapter
from core.runtime.resolver import ResolvedArtifact, ResolvedAsset, ResolvedShotContext
from core.runtime.state_store import StateStore
from core.schemas.runtime_mvp import metadata


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _counts(store: StateStore) -> dict[str, int]:
    with store.connection() as connection:
        return {name: len(connection.execute(select(metadata.tables[name])).fetchall()) for name in ("tasks", "events", "artifacts", "generations", "provider_submissions", "reviews")}


@pytest.fixture()
def t16_root() -> Path:
    """Avoid host-owned pytest tmp ACLs while retaining an isolated workspace root."""
    root = Path(__file__).resolve().parents[2] / ".tmp" / "t16-isolated" / uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    return root


@pytest.fixture()
def package_fixture(t16_root: Path) -> dict[str, Any]:
    store = StateStore(t16_root / "frameflow.db", initialize=True)
    root = t16_root / "projects"
    project = root / "P1"

    def file(name: str, data: bytes) -> Path:
        result = project / name
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_bytes(data)
        return result

    char, scene, prop = file("assets/C1/master.png", b"char"), file("assets/S1/master.png", b"scene"), file("assets/PROP1/master.png", b"prop")
    first, last = file("shots/SH1/references/first.png", b"first"), file("shots/SH1/references/last.png", b"last")
    store.create_project("P1", "Package Test", "16:9", 24, 5)
    store.create_sequence("SEQ1", "P1", 1)
    store.create_shot("SH1", "P1", "SEQ1", {"shot_id": "SH1", "duration_sec": 5})
    for asset_id, asset_type, artifact_id, path in (("C1", "character", "AC1", char), ("S1", "scene", "AS1", scene), ("PROP1", "prop", "AP1", prop)):
        store.create_asset(asset_id, "P1", asset_type, "asset-v1", status="APPROVED", master_artifact_id=artifact_id)
        store.create_artifact(artifact_id, "P1", "image", "master", str(path), "v1", asset_id=asset_id, sha256=_sha(path), status="READY")
    for artifact_id, role, path in (("F1", "first_frame", first), ("L1", "last_frame", last)):
        store.create_artifact(artifact_id, "P1", "image", role, str(path), "v1", shot_id="SH1", sha256=_sha(path), status="READY")

    def artifact(artifact_id: str, path: Path, *, asset_id: str | None = None, shot_id: str | None = None, role: str = "master") -> ResolvedArtifact:
        return ResolvedArtifact(artifact_id, "image", role, str(path), _sha(path), "v1", "READY", "P1", asset_id, shot_id, True)

    context = ResolvedShotContext("SH1", "P1", "SEQ1", {"id": "SH1", "project_id": "P1"}, {"shot_id": "SH1", "duration_sec": 5}, (ResolvedAsset("C1", "character", "APPROVED", "asset-v1", artifact("AC1", char, asset_id="C1"), True),), ResolvedAsset("S1", "scene", "APPROVED", "asset-v1", artifact("AS1", scene, asset_id="S1"), True), (ResolvedAsset("PROP1", "prop", "APPROVED", "asset-v1", artifact("AP1", prop, asset_id="PROP1"), True),), artifact("F1", first, shot_id="SH1", role="first_frame"), artifact("L1", last, shot_id="SH1", role="last_frame"), ready=True)
    text = "[SUBJECT]\nA deterministic package test."
    prompt = CanonicalPrompt("SH1", "2.2", (("SUBJECT", "A deterministic package test."),), text, ("AC1", "AS1", "AP1", "F1", "L1"), prompt_sha256=hashlib.sha256(text.encode()).hexdigest())
    try:
        yield {"store": store, "root": root, "context": context, "prompt": prompt, "builder": PackageBuilder(store, projects_root=root)}
    finally:
        store.dispose()


def _build(bundle: dict[str, Any]):
    queued = bundle["builder"].build(bundle["context"], bundle["prompt"])
    assert queued.action == "TASK_QUEUED"
    outcome = bundle["builder"].worker().run_once()
    return queued, outcome


def test_t16_happy_path_creates_registered_shot_package(package_fixture: dict[str, Any]) -> None:
    queued, outcome = _build(package_fixture)
    assert outcome.outcome.value == "succeeded"
    result = json.loads(outcome.task["result_json"])
    artifact = package_fixture["store"].get_artifact(result["package_manifest_artifact_id"])
    assert artifact is not None and artifact["role"] == "package_manifest" and artifact["status"] == "READY"
    assert Path(artifact["path"]).is_file() and "/shots/SH1/packages/" in Path(artifact["path"]).as_posix()
    manifest = json.loads(Path(artifact["path"]).read_text(encoding="utf-8"))
    assert manifest["project_id"] == "P1" and manifest["shot_id"] == "SH1"
    assert manifest["source_artifact_ids"] == ["AC1", "AS1", "AP1", "F1", "L1"]
    assert [item["reference_type"] for item in manifest["references"]] == ["character_master", "scene_master", "prop_master", "first_frame", "last_frame"]
    assert artifact["sha256"] == _sha(Path(artifact["path"]))
    assert queued.preparation.package_version == artifact["version"]


def test_t16_prepare_is_pure_and_repeat_build_reuses_one_task_and_artifact(package_fixture: dict[str, Any]) -> None:
    before = _counts(package_fixture["store"])
    first = package_fixture["builder"].prepare(package_fixture["context"], package_fixture["prompt"])
    second = package_fixture["builder"].prepare(package_fixture["context"], package_fixture["prompt"])
    assert first == second and _counts(package_fixture["store"]) == before
    queued = package_fixture["builder"].build(package_fixture["context"], package_fixture["prompt"])
    duplicate = package_fixture["builder"].build(package_fixture["context"], package_fixture["prompt"])
    assert queued.task["id"] == duplicate.task["id"]
    assert package_fixture["builder"].worker().run_once().outcome.value == "succeeded"
    assert package_fixture["builder"].worker().run_once().outcome.value == "idle"
    assert len([item for item in package_fixture["store"].list_artifacts() if item["role"] == "package_manifest"]) == 1


def test_t16_rapid_duplicate_requests_elect_one_task_and_one_package(package_fixture: dict[str, Any]) -> None:
    results: list[Any] = []
    errors: list[BaseException] = []
    ready = threading.Barrier(2)

    def request() -> None:
        try:
            ready.wait(timeout=3)
            results.append(package_fixture["builder"].build(package_fixture["context"], package_fixture["prompt"]))
        except BaseException as exc:  # pragma: no cover - assertion reports concrete concurrency failure
            errors.append(exc)

    first, second = threading.Thread(target=request), threading.Thread(target=request)
    first.start(); second.start(); first.join(timeout=5); second.join(timeout=5)
    assert not first.is_alive() and not second.is_alive() and not errors
    assert len(results) == 2 and len({result.task["id"] for result in results}) == 1
    assert package_fixture["builder"].worker().run_once().outcome.value == "succeeded"
    assert len([item for item in package_fixture["store"].list_artifacts() if item["role"] == "package_manifest"]) == 1


def test_t16_changed_input_versions_non_destructively(package_fixture: dict[str, Any]) -> None:
    _build(package_fixture)
    changed_context = replace(package_fixture["context"], shot_spec={"shot_id": "SH1", "duration_sec": 6})
    changed_text = "[SUBJECT]\nChanged package input."
    changed_prompt = replace(package_fixture["prompt"], canonical_text=changed_text, prompt_sha256=hashlib.sha256(changed_text.encode()).hexdigest())
    queued = package_fixture["builder"].build(changed_context, changed_prompt)
    assert queued.preparation.ready
    assert package_fixture["builder"].worker().run_once().outcome.value == "succeeded"
    packages = [item for item in package_fixture["store"].list_artifacts() if item["role"] == "package_manifest"]
    assert len(packages) == 2 and len({item["version"] for item in packages}) == 2 and all(Path(item["path"]).is_file() for item in packages)


@pytest.mark.parametrize("mode, expected", [("missing_row", "MISSING_ARTIFACT"), ("missing_file", "MISSING_ARTIFACT_FILE"), ("outside_path", "INVALID_ARTIFACT_PATH"), ("wrong_project", "CROSS_PROJECT_ARTIFACT"), ("wrong_shot", "CROSS_SHOT_ARTIFACT"), ("hash", "ARTIFACT_INTEGRITY_MISMATCH")])
def test_t16_input_validation_fails_closed(package_fixture: dict[str, Any], mode: str, expected: str, t16_root: Path) -> None:
    store, context = package_fixture["store"], package_fixture["context"]
    if mode == "missing_row":
        with store.transaction() as connection:
            connection.execute(metadata.tables["artifacts"].delete().where(metadata.tables["artifacts"].c.id == "AC1"))
    elif mode == "missing_file":
        Path(context.characters[0].master_artifact.path).unlink()
    elif mode == "outside_path":
        outside = t16_root / "outside.png"; outside.write_bytes(b"outside")
        store.update_artifact("AC1", path=str(outside), sha256=_sha(outside))
        context = replace(context, characters=(replace(context.characters[0], master_artifact=replace(context.characters[0].master_artifact, path=str(outside), sha256=_sha(outside))),))
    elif mode == "wrong_project":
        store.create_project("P2", "Other", "16:9", 24, 5)
        store.update_artifact("AC1", project_id="P2")
        context = replace(context, characters=(replace(context.characters[0], master_artifact=replace(context.characters[0].master_artifact, project_id="P2")),))
    elif mode == "wrong_shot":
        store.create_shot("SH2", "P1", "SEQ1", {"shot_id": "SH2"})
        store.update_artifact("F1", shot_id="SH2")
        context = replace(context, first_frame=replace(context.first_frame, shot_id="SH2"))
    else:
        store.update_artifact("AC1", sha256="0" * 64)
        context = replace(context, characters=(replace(context.characters[0], master_artifact=replace(context.characters[0].master_artifact, sha256="0" * 64)),))
    result = package_fixture["builder"].build(context, package_fixture["prompt"])
    assert result.action == "INVALID_REQUEST" and any(issue.code == expected for issue in result.issues)
    assert not [item for item in store.list_artifacts() if item["role"] == "package_manifest"]


def test_t16_destination_collision_and_atomic_write_failure_leave_no_artifact(package_fixture: dict[str, Any]) -> None:
    prepared = package_fixture["builder"].prepare(package_fixture["context"], package_fixture["prompt"])
    destination = Path(prepared.destination); destination.parent.mkdir(parents=True); destination.write_text("collision", encoding="utf-8")
    assert _build(package_fixture)[1].outcome.value == "failed"
    assert destination.read_text(encoding="utf-8") == "collision"
    assert not [item for item in package_fixture["store"].list_artifacts() if item["role"] == "package_manifest"]


def test_t16_atomic_writer_failure_leaves_no_final_or_temp(package_fixture: dict[str, Any]) -> None:
    class FailingWriter(PackageAtomicJsonWriter):
        def write_new(self, destination: Path, payload: dict[str, Any]) -> str:
            temporary = destination.with_name(f".{destination.name}.tmp")
            temporary.write_text("partial", encoding="utf-8")
            raise OSError("injected write failure")

    package_fixture["builder"].writer = FailingWriter()
    queued, outcome = _build(package_fixture)
    assert outcome.outcome.value == "failed"
    destination = Path(queued.preparation.destination)
    assert not destination.exists() and not destination.with_name(f".{destination.name}.tmp").exists()
    assert not [item for item in package_fixture["store"].list_artifacts() if item["role"] == "package_manifest"]


@pytest.mark.parametrize("operation", ["fsync", "replace"])
def test_t16_atomic_finalize_failures_leave_no_valid_package(package_fixture: dict[str, Any], monkeypatch: pytest.MonkeyPatch, operation: str) -> None:
    import core.runtime.package_builder as package_module

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise OSError(f"injected {operation} failure")

    monkeypatch.setattr(package_module.os, operation, fail)
    queued, outcome = _build(package_fixture)
    assert outcome.outcome.value == "failed"
    destination = Path(queued.preparation.destination)
    assert not destination.exists() and not destination.with_name(f".{destination.name}.tmp").exists()
    assert not [item for item in package_fixture["store"].list_artifacts() if item["role"] == "package_manifest"]


def test_t16_db_failure_compensates_then_retry_succeeds(package_fixture: dict[str, Any]) -> None:
    queued = package_fixture["builder"].build(package_fixture["context"], package_fixture["prompt"])
    original = package_fixture["store"].create_artifact
    package_fixture["store"].create_artifact = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected database failure"))
    try:
        assert package_fixture["builder"].worker().run_once().outcome.value == "failed"
    finally:
        package_fixture["store"].create_artifact = original
    assert not Path(queued.preparation.destination).exists()
    package_fixture["builder"].queue.retry(queued.task["id"])
    assert package_fixture["builder"].worker().run_once().outcome.value == "succeeded"
    assert len([item for item in package_fixture["store"].list_artifacts() if item["role"] == "package_manifest"]) == 1


def test_t16_t26_consumes_real_package_without_t26_mutation(package_fixture: dict[str, Any]) -> None:
    queued, outcome = _build(package_fixture)
    artifact_id = json.loads(outcome.task["result_json"])["package_manifest_artifact_id"]
    package_fixture["store"].create_generation("GEN1", "SH1", artifact_id, "manual")
    handoff = ManualProviderAdapter(package_fixture["store"]).prepare(package_fixture["prompt"], package_fixture["context"], generation_id="GEN1")
    assert handoff.submission_ready and handoff.package_manifest_artifact_id == artifact_id
    assert handoff.package_version == queued.preparation.package_version
    assert Path(handoff.package_manifest_path).is_file()
