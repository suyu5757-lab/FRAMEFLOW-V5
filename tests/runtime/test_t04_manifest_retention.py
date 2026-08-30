from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import insert, update

from core.schemas.runtime_mvp import metadata
from core.runtime.manifest import AtomicJsonWriter, ManifestExportError, ManifestExporter
from core.runtime.retention import RetentionError, RetentionPolicy, RetentionService
from core.runtime.state_store import StateStore


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _store(tmp_path: Path) -> tuple[StateStore, Path, Path]:
    projects_root = tmp_path / "projects"
    archive_root = tmp_path / "archives"
    store = StateStore(tmp_path / "frameflow.db", initialize=True)
    store.create_project("PRJ_T04", "T04", "16:9", 24, 10)
    store.create_sequence("SEQ_T04", "PRJ_T04", 1)
    store.create_shot("SH_T04", "PRJ_T04", "SEQ_T04", {"status": "DRAFT", "duration_sec": 1})
    return store, projects_root, archive_root


def _generation(
    store: StateStore,
    projects_root: Path,
    generation_id: str,
    *,
    extra: bool = False,
    created_at: datetime | None = None,
) -> tuple[Path, list[str]]:
    root = projects_root / "PRJ_T04" / "shots" / "SH_T04" / "generations" / generation_id
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "package.json"
    manifest.write_text(generation_id, encoding="utf-8")
    artifact_ids = [f"ART_{generation_id}_PACKAGE"]
    store.create_artifact(
        artifact_ids[0],
        "PRJ_T04",
        "package_manifest",
        "package",
        str(manifest),
        "1",
        shot_id="SH_T04",
        sha256=_sha256(manifest),
        status="READY",
        source_artifacts={"api_key": "do-not-export", "source": "test"},
    )
    if extra:
        extra_path = root / "result.mp4"
        extra_path.write_bytes((generation_id + "-result").encode("utf-8"))
        extra_id = f"ART_{generation_id}_RESULT"
        artifact_ids.append(extra_id)
        store.create_artifact(
            extra_id,
            "PRJ_T04",
            "video",
            "result",
            str(extra_path),
            "1",
            shot_id="SH_T04",
            sha256=_sha256(extra_path),
            status="READY",
        )
    store.create_generation(generation_id, "SH_T04", artifact_ids[0], "test-provider")
    if created_at is not None:
        with store.transaction() as connection:
            connection.execute(
                update(metadata.tables["generations"])
                .where(metadata.tables["generations"].c.id == generation_id)
                .values(created_at=created_at)
            )
    return root, artifact_ids


@pytest.fixture()
def isolated_store(tmp_path: Path):
    store, projects_root, archive_root = _store(tmp_path)
    try:
        yield store, projects_root, archive_root
    finally:
        store.dispose()


def test_t04_manifest_is_deterministic_authoritative_and_secret_safe(isolated_store) -> None:
    store, projects_root, _archive_root = isolated_store
    exporter = ManifestExporter(store, projects_root=projects_root)
    first = exporter.build_manifest("PRJ_T04")
    assert set(first) == {
        "manifest_type", "manifest_version", "project_id", "project", "sequences",
        "shots", "assets", "artifacts", "generations", "reviews",
    }
    assert "tasks" not in first
    assert "do-not-export" not in str(first)
    destination = projects_root / "PRJ_T04" / "project_manifest.json"
    exporter.export_project("PRJ_T04", destination)
    first_bytes = destination.read_bytes()
    exporter.export_project("PRJ_T04", destination)
    assert destination.read_bytes() == first_bytes


def test_t04_manifest_atomic_failure_preserves_previous_final(tmp_path: Path) -> None:
    destination = tmp_path / "project_manifest.json"
    destination.write_bytes(b"previous\n")
    writer = AtomicJsonWriter()
    with patch("core.runtime.manifest.exporter.os.fsync", side_effect=OSError("injected")):
        with pytest.raises(OSError):
            writer.write(destination, {"new": True})
    assert destination.read_bytes() == b"previous\n"
    assert list(tmp_path.glob("*.tmp")) == []


def test_t04_manifest_path_escape_is_rejected(isolated_store) -> None:
    store, projects_root, _archive_root = isolated_store
    exporter = ManifestExporter(store, projects_root=projects_root)
    with pytest.raises(ManifestExportError, match="inside the project root"):
        exporter.export_project("PRJ_T04", projects_root / "outside.json")


def test_t04_retention_keeps_last_two_and_archives_generation_as_one_unit(isolated_store) -> None:
    store, projects_root, archive_root = isolated_store
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(4):
        _generation(store, projects_root, f"GEN_{index}", extra=True, created_at=base + timedelta(days=index))
    service = RetentionService(
        store,
        projects_root=projects_root,
        archive_root=archive_root,
        policy=RetentionPolicy(max_archive_size_gb=1),
    )
    events_before = len(store.list("events"))
    tasks_before = len(store.list("tasks"))
    plan = service.plan("PRJ_T04")
    assert [u["generation_id"] for u in plan["units"] if u["action"] == "archive"] == ["GEN_1", "GEN_0"]
    assert all(len(u["artifacts"]) == 2 for u in plan["units"] if u["action"] == "archive")
    result = service.apply(plan)
    assert result["status"] == "APPLIED"
    assert len(store.list("events")) == events_before
    assert len(store.list("tasks")) == tasks_before
    for generation_id in ("GEN_0", "GEN_1"):
        destination = archive_root / "PRJ_T04" / "SH_T04" / generation_id
        assert (destination / "package.json").is_file()
        assert (destination / "result.mp4").is_file()
        for artifact_id in (f"ART_{generation_id}_PACKAGE", f"ART_{generation_id}_RESULT"):
            assert store.get_artifact(artifact_id)["status"] == "ARCHIVED"
    assert (projects_root / "PRJ_T04" / "shots" / "SH_T04" / "generations" / "GEN_0" / "package.json").exists() is False
    assert all(u["action"] != "archive" for u in service.plan("PRJ_T04")["units"] if u["generation_id"] in {"GEN_0", "GEN_1"})


def test_t04_retention_protects_locked_master_and_approved_generation(isolated_store) -> None:
    store, projects_root, archive_root = isolated_store
    old_root, ids = _generation(store, projects_root, "GEN_OLD", created_at=datetime(2025, 1, 1, tzinfo=UTC))
    _generation(store, projects_root, "GEN_NEW", created_at=datetime(2026, 1, 1, tzinfo=UTC))
    store.create_asset("ASSET_LOCKED", "PRJ_T04", "character", "1", status="LOCKED", master_artifact_id=ids[0])
    with store.transaction() as connection:
        connection.execute(
            insert(metadata.tables["reviews"]).values(
                id="REV_APPROVED", shot_id="SH_T04", generation_id="GEN_NEW",
                qa_json="{}", decision="APPROVED", created_at=datetime(2026, 1, 2, tzinfo=UTC),
            )
        )
    service = RetentionService(store, projects_root=projects_root, archive_root=archive_root, policy=RetentionPolicy(keep_last_generations_per_shot=0))
    units = {unit["generation_id"]: unit for unit in service.plan("PRJ_T04")["units"]}
    assert "locked_asset_master" in units["GEN_OLD"]["reasons"]
    assert "approved_generation" in units["GEN_NEW"]["reasons"]
    assert old_root.joinpath("package.json").is_file()


def test_t04_retention_dry_run_and_path_escape_make_no_changes(isolated_store, tmp_path: Path) -> None:
    store, projects_root, archive_root = isolated_store
    _generation(store, projects_root, "GEN_OLD", created_at=datetime(2025, 1, 1, tzinfo=UTC))
    service = RetentionService(store, projects_root=projects_root, archive_root=archive_root, policy=RetentionPolicy(keep_last_generations_per_shot=0))
    plan = service.plan("PRJ_T04")
    assert service.apply(plan, dry_run=True)["status"] == "DRY_RUN"
    assert (projects_root / "PRJ_T04" / "shots" / "SH_T04" / "generations" / "GEN_OLD" / "package.json").is_file()
    with store.transaction() as connection:
        connection.execute(
            update(metadata.tables["artifacts"])
            .where(metadata.tables["artifacts"].c.id == "ART_GEN_OLD_PACKAGE")
            .values(path=str(tmp_path / "outside.bin"))
        )
    blocked = service.plan("PRJ_T04")["units"][0]
    assert blocked["action"] == "protect"
    assert "source_outside_project_root" in blocked["reasons"]


@pytest.mark.parametrize("failure_point", ["verify", "database"])
def test_t04_retention_compensates_after_post_move_failure(isolated_store, failure_point: str) -> None:
    store, projects_root, archive_root = isolated_store
    _generation(store, projects_root, "GEN_OLD", extra=True, created_at=datetime(2025, 1, 1, tzinfo=UTC))
    service = RetentionService(store, projects_root=projects_root, archive_root=archive_root, policy=RetentionPolicy(keep_last_generations_per_shot=0))
    plan = service.plan("PRJ_T04")
    package = projects_root / "PRJ_T04" / "shots" / "SH_T04" / "generations" / "GEN_OLD" / "package.json"
    if failure_point == "verify":
        patcher = patch.object(service, "_verify_moved_files", side_effect=RetentionError("VERIFY", "injected"))
    else:
        patcher = patch.object(service, "_commit_archive_metadata", side_effect=RetentionError("DATABASE", "injected"))
    with patcher:
        result = service.apply(plan)
    assert result["status"] == "FAILED"
    assert package.is_file()
    assert store.get_artifact("ART_GEN_OLD_PACKAGE")["status"] == "READY"
    assert not (archive_root / "PRJ_T04" / "SH_T04" / "GEN_OLD" / "package.json").exists()


def test_t04_retention_move_failure_and_collision_fail_closed(isolated_store) -> None:
    store, projects_root, archive_root = isolated_store
    _generation(store, projects_root, "GEN_OLD", created_at=datetime(2025, 1, 1, tzinfo=UTC))
    service = RetentionService(store, projects_root=projects_root, archive_root=archive_root, policy=RetentionPolicy(keep_last_generations_per_shot=0))
    plan = service.plan("PRJ_T04")
    with patch("core.runtime.retention.service.os.replace", side_effect=OSError("injected")):
        result = service.apply(plan)
    assert result["status"] == "FAILED"
    assert store.get_artifact("ART_GEN_OLD_PACKAGE")["status"] == "READY"

    collision = archive_root / "PRJ_T04" / "SH_T04" / "GEN_OLD" / "package.json"
    collision.parent.mkdir(parents=True, exist_ok=True)
    collision.write_text("collision", encoding="utf-8")
    result = service.apply(plan)
    assert result["status"] == "FAILED"
    assert collision.read_text(encoding="utf-8") == "collision"


def test_t04_retention_rerun_is_idempotent(isolated_store) -> None:
    store, projects_root, archive_root = isolated_store
    _generation(store, projects_root, "GEN_OLD", created_at=datetime(2025, 1, 1, tzinfo=UTC))
    service = RetentionService(store, projects_root=projects_root, archive_root=archive_root, policy=RetentionPolicy(keep_last_generations_per_shot=0))
    plan = service.plan("PRJ_T04")
    assert service.apply(plan)["status"] == "APPLIED"
    second = service.apply(plan)
    assert second["status"] == "APPLIED"
    assert second["failed"] == []


def test_t04_partial_archived_generation_is_protected(isolated_store) -> None:
    store, projects_root, archive_root = isolated_store
    _generation(store, projects_root, "GEN_PARTIAL", extra=True, created_at=datetime(2025, 1, 1, tzinfo=UTC))
    source = projects_root / "PRJ_T04" / "shots" / "SH_T04" / "generations" / "GEN_PARTIAL" / "package.json"
    destination = archive_root / "PRJ_T04" / "SH_T04" / "GEN_PARTIAL" / "package.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.replace(destination)
    with store.transaction() as connection:
        connection.execute(
            update(metadata.tables["artifacts"])
            .where(metadata.tables["artifacts"].c.id == "ART_GEN_PARTIAL_PACKAGE")
            .values(path=str(destination), status="ARCHIVED")
        )
    service = RetentionService(
        store,
        projects_root=projects_root,
        archive_root=archive_root,
        policy=RetentionPolicy(keep_last_generations_per_shot=0),
    )
    unit = service.plan("PRJ_T04")["units"][0]
    assert unit["action"] == "protect"
    assert unit["reasons"] == ["partial_archive"]
