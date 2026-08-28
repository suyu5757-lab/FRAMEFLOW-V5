from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from core.migration.cutover import CutoverBlocked, perform_production_cutover
from core.migration.equivalence import (
    A0_STAGE,
    A1_STAGE,
    B0_STAGE,
    build_candidate_a_lifecycle_evidence,
    build_candidate_evidence,
    build_smoke_delta,
    compare_logical_fingerprints,
    logical_data_fingerprint,
    schema_fingerprint,
    verify_candidate_equivalence,
    verify_final_candidate_gate,
)
from core.runtime.state_store.factory import open_runtime_store


@pytest.fixture
def test_root() -> Path:
    root = Path(os.environ["FRAMEFLOW_TEST_TMP"]) / f"candidate-equivalence-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    return root


def _candidate(root: Path, name: str) -> Path:
    path = root / f"{name}.db"
    with open_runtime_store(path, initialize=True, candidate=True):
        pass
    return path


def _evidence(
    path: Path,
    *,
    source_sha: str = "a" * 64,
    stage: str = A0_STAGE,
    **changes: object,
) -> dict[str, object]:
    evidence = build_candidate_evidence(
        path,
        source_legacy_sha=source_sha,
        evidence_stage=stage,
        captured_before_backend=stage == A0_STAGE,
        captured_after_smoke=stage == A1_STAGE,
        captured_before_swap=stage == B0_STAGE,
        backend_opened=stage == A1_STAGE,
    )
    evidence.update(
        {
            "row_accounting": {
                "unknown": 0,
                "unaccounted": 0,
                "required_shots": 17,
                "accounted_shots": 17,
                "comparison": {
                    "unknown": 0,
                    "unaccounted": 0,
                    "required_shots": 17,
                    "accounted_shots": 17,
                },
            },
            "validation_passed": True,
            "backend_opened": stage == A1_STAGE,
            "rename_passed": True,
        }
    )
    if stage == B0_STAGE:
        evidence["final_db_stabilization"] = {
            "passed": True,
            "checkpoint_passed": True,
            "journal_mode_after_stabilization": "delete",
            "sidecars_absent": True,
            "stable_samples": [{"sample": index} for index in range(4)],
            "final_file_state": {
                "main": {"exists": True},
                "wal": {"exists": False},
                "shm": {"exists": False},
            },
            "logical_fingerprint": evidence["logical_fingerprint"],
            "schema_fingerprint": evidence["schema_fingerprint"],
            "row_accounting": evidence["row_accounting"],
        }
        evidence["terminal_seal"] = {
            "candidate": str(path.resolve()),
            "state": "SEALED",
            "candidate_db_open_count": 3,
            "candidate_b_post_seal_db_open_count": 0,
            "post_seal_db_open_count": 0,
            "post_seal_db_open_attempts": 0,
            "candidate_b_reopened_after_rename": False,
        }
    evidence.update(changes)
    return evidence


def _launcher_evidence() -> dict[str, object]:
    return {
        "status": "PASS",
        "boots": [
            {"boot": "first_start", "health": {"runtime_mode": "v5"}, "api_passed": 19, "api_failed": 0, "historical_passed": 17, "historical_failed": 0},
            {"boot": "restart", "health": {"runtime_mode": "v5"}, "api_passed": 19, "api_failed": 0, "historical_passed": 17, "historical_failed": 0},
        ],
    }


def _candidate_a_lifecycle(
    a0: dict[str, object],
    a1: dict[str, object],
    *,
    fixture_ids: tuple[str, ...] = (),
    expected_runtime_tables: tuple[str, ...] = (),
    rename_passed: bool = True,
) -> dict[str, object]:
    return build_candidate_a_lifecycle_evidence(
        a0,
        a1,
        formal_launcher=_launcher_evidence(),
        rename={"passed": rename_passed},
        smoke_delta=build_smoke_delta(
            a0,
            a1,
            fixture_ids=fixture_ids,
            expected_runtime_tables=expected_runtime_tables,
        ),
    )


def test_c1_same_source_migration_schema_and_data_pass(test_root: Path) -> None:
    candidate_a = _candidate(test_root, "candidate-a")
    candidate_b = _candidate(test_root, "candidate-b")
    result = verify_candidate_equivalence(_evidence(candidate_a), _evidence(candidate_b))
    assert result["passed"] is True


def test_c2_different_source_sha_fails(test_root: Path) -> None:
    candidate_a = _candidate(test_root, "candidate-a")
    candidate_b = _candidate(test_root, "candidate-b")
    result = verify_candidate_equivalence(
        _evidence(candidate_a, source_sha="a" * 64),
        _evidence(candidate_b, source_sha="b" * 64),
    )
    assert result["passed"] is False
    assert any("source_legacy_sha differs" in error for error in result["errors"])


def test_c3_schema_difference_fails(test_root: Path) -> None:
    candidate_a = _candidate(test_root, "candidate-a")
    candidate_b = _candidate(test_root, "candidate-b")
    connection = sqlite3.connect(candidate_b)
    try:
        connection.execute("ALTER TABLE projects ADD COLUMN gate_mutation TEXT")
        connection.commit()
    finally:
        connection.close()
    result = verify_candidate_equivalence(_evidence(candidate_a), _evidence(candidate_b))
    assert result["passed"] is False
    assert result["checks"]["schema_equivalence"] is False


def test_c4_domain_row_difference_fails(test_root: Path) -> None:
    candidate_a = _candidate(test_root, "candidate-a")
    candidate_b = _candidate(test_root, "candidate-b")
    with open_runtime_store(candidate_b, candidate=True) as store:
        store.create_project("C4", "Different", "16:9", 24, 1)
    result = verify_candidate_equivalence(_evidence(candidate_a), _evidence(candidate_b))
    assert result["passed"] is False
    assert result["checks"]["logical_data_equivalence"] is False


def test_c5_migration_revision_difference_fails(test_root: Path) -> None:
    candidate_a = _candidate(test_root, "candidate-a")
    candidate_b = _candidate(test_root, "candidate-b")
    result = verify_candidate_equivalence(
        _evidence(candidate_a),
        _evidence(candidate_b, migration_revision="different-revision"),
    )
    assert result["passed"] is False
    assert result["checks"]["migration_revision"] is False


def test_c6_candidate_b_backend_opened_fails(test_root: Path) -> None:
    candidate_a = _candidate(test_root, "candidate-a")
    candidate_b = _candidate(test_root, "candidate-b")
    result = verify_candidate_equivalence(
        _evidence(candidate_a), _evidence(candidate_b, backend_opened=True)
    )
    assert result["passed"] is False
    assert result["checks"]["candidate_b_backend_opened"] is False


def test_c7_candidate_b_rename_failure_fails_closed(test_root: Path) -> None:
    candidate_a = _candidate(test_root, "candidate-a")
    candidate_b = _candidate(test_root, "candidate-b")
    a0 = _evidence(candidate_a)
    a1 = _evidence(candidate_a, stage=A1_STAGE)
    result = verify_final_candidate_gate(
        _candidate_a_lifecycle(a0, a1),
        _evidence(candidate_b, stage=B0_STAGE, rename_passed=False),
    )
    assert result["passed"] is False
    assert result["checks"]["candidate_b_rename"] is False


def test_c8_equivalence_failure_leaves_production_untouched(test_root: Path) -> None:
    canonical = test_root / "canonical.db"
    legacy_archive = test_root / "legacy-archive.db"
    candidate_a = _candidate(test_root, "candidate-a")
    candidate_b = _candidate(test_root, "candidate-b")
    shutil.copy2(candidate_a, canonical)
    shutil.copy2(canonical, legacy_archive)
    before = hashlib.sha256(canonical.read_bytes()).hexdigest()
    formal_evidence = {
        "candidate_a_evidence": _candidate_a_lifecycle(
            _evidence(candidate_a), _evidence(candidate_a, stage=A1_STAGE)
        ),
        "candidate_b_evidence": _evidence(
            candidate_b, stage=B0_STAGE, rename_passed=False
        ),
    }
    with patch("core.migration.cutover.CANONICAL_DATABASE_PATH", canonical), patch(
        "core.migration.cutover.verify_production_interpreter"
    ), patch("core.migration.cutover.os.replace") as replace:
        with pytest.raises(CutoverBlocked, match="final A/B candidate equivalence gate failed"):
            perform_production_cutover(
                candidate_b,
                legacy_archive=legacy_archive,
                legacy_source=canonical,
                production_cutover=True,
                no_active_writer=lambda: True,
                candidate_handle_free=True,
                legacy_archive_verified=True,
                formal_launcher_evidence=formal_evidence,
            )
    assert hashlib.sha256(canonical.read_bytes()).hexdigest() == before
    replace.assert_not_called()


def test_schema_fingerprint_is_explicitly_11_domain_tables(test_root: Path) -> None:
    candidate = _candidate(test_root, "candidate")
    fingerprint = schema_fingerprint(candidate)
    assert fingerprint["domain_table_count"] == 11
    assert len(fingerprint["domain_tables"]) == 11


def test_f1_a0_equals_b0_while_expected_a1_delta_passes(test_root: Path) -> None:
    candidate_a = _candidate(test_root, "candidate-a")
    candidate_b = _candidate(test_root, "candidate-b")
    a0 = _evidence(candidate_a)
    b0 = _evidence(candidate_b, stage=B0_STAGE)
    with open_runtime_store(candidate_a, candidate=True) as store:
        store.create_project("RUNTIME_META_F1", "Expected", "16:9", 24, 1)
    a1 = _evidence(candidate_a, stage=A1_STAGE)
    result = verify_final_candidate_gate(
        _candidate_a_lifecycle(
            a0, a1, expected_runtime_tables=("projects",)
        ),
        b0,
    )
    assert a0["logical_fingerprint"]["sha256"] != a1["logical_fingerprint"]["sha256"]
    assert result["passed"] is True
    assert result["comparison_stage"] == "A0_VS_B0"


def test_f2_a0_not_equal_b0_fails(test_root: Path) -> None:
    candidate_a = _candidate(test_root, "candidate-a")
    candidate_b = _candidate(test_root, "candidate-b")
    with open_runtime_store(candidate_b, candidate=True) as store:
        store.create_project("F2", "Different baseline", "16:9", 24, 1)
    result = verify_candidate_equivalence(
        _evidence(candidate_a), _evidence(candidate_b, stage=B0_STAGE)
    )
    assert result["passed"] is False
    assert result["checks"]["logical_data_equivalence"] is False


def test_f3_a1_not_equal_b0_does_not_replace_a0_equivalence(test_root: Path) -> None:
    candidate_a = _candidate(test_root, "candidate-a")
    candidate_b = _candidate(test_root, "candidate-b")
    a0 = _evidence(candidate_a)
    b0 = _evidence(candidate_b, stage=B0_STAGE)
    with open_runtime_store(candidate_a, candidate=True) as store:
        store.create_project("EXPECTED_RUNTIME_F3", "Runtime", "16:9", 24, 1)
    a1 = _evidence(candidate_a, stage=A1_STAGE)
    lifecycle = _candidate_a_lifecycle(
        a0, a1, expected_runtime_tables=("projects",)
    )
    assert a1["logical_fingerprint"]["sha256"] != b0["logical_fingerprint"]["sha256"]
    assert verify_final_candidate_gate(lifecycle, b0)["passed"] is True


def test_f4_migration_generated_domain_value_difference_fails(test_root: Path) -> None:
    candidate_a = _candidate(test_root, "candidate-a")
    candidate_b = _candidate(test_root, "candidate-b")
    connection = sqlite3.connect(candidate_b)
    try:
        connection.execute(
            "INSERT INTO projects(id,title,aspect_ratio,fps,target_duration,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            ("F4", "Same PK", "16:9", 24, 1, "2000-01-01", "2000-01-01"),
        )
        connection.commit()
    finally:
        connection.close()
    with open_runtime_store(candidate_a, candidate=True) as store:
        store.create_project("F4", "Same PK", "16:9", 24, 1)
    result = verify_candidate_equivalence(
        _evidence(candidate_a), _evidence(candidate_b, stage=B0_STAGE)
    )
    assert result["passed"] is False
    assert result["logical_delta"]["different_tables"] == ["projects"]


def test_f5_smoke_fixture_created_and_cleaned_passes(test_root: Path) -> None:
    candidate_a = _candidate(test_root, "candidate-a")
    candidate_b = _candidate(test_root, "candidate-b")
    a0 = _evidence(candidate_a)
    fixture_id = "T03R3_SMOKE_F5"
    with open_runtime_store(candidate_a, candidate=True) as store:
        store.create_project(fixture_id, "Fixture", "16:9", 24, 1)
    connection = sqlite3.connect(candidate_a)
    try:
        connection.execute("DELETE FROM projects WHERE id=?", (fixture_id,))
        connection.commit()
    finally:
        connection.close()
    a1 = _evidence(candidate_a, stage=A1_STAGE)
    lifecycle = _candidate_a_lifecycle(a0, a1, fixture_ids=(fixture_id,))
    result = verify_final_candidate_gate(
        lifecycle, _evidence(candidate_b, stage=B0_STAGE)
    )
    assert lifecycle["smoke_delta"]["smoke_fixture_cleanup_passed"] is True
    assert result["passed"] is True


def test_f6_remaining_smoke_fixture_fails_cleanup(test_root: Path) -> None:
    candidate_a = _candidate(test_root, "candidate-a")
    candidate_b = _candidate(test_root, "candidate-b")
    a0 = _evidence(candidate_a)
    fixture_id = "T03R3_SMOKE_F6"
    with open_runtime_store(candidate_a, candidate=True) as store:
        store.create_project(fixture_id, "Fixture", "16:9", 24, 1)
    a1 = _evidence(candidate_a, stage=A1_STAGE)
    lifecycle = _candidate_a_lifecycle(a0, a1, fixture_ids=(fixture_id,))
    result = verify_final_candidate_gate(
        lifecycle, _evidence(candidate_b, stage=B0_STAGE)
    )
    assert lifecycle["smoke_delta"]["smoke_fixture_cleanup_passed"] is False
    assert result["passed"] is False


def test_f7_expected_runtime_delta_is_reported_separately(test_root: Path) -> None:
    candidate = _candidate(test_root, "candidate")
    a0 = _evidence(candidate)
    with open_runtime_store(candidate, candidate=True) as store:
        store.create_project("EXPECTED_F7", "Expected", "16:9", 24, 1)
    a1 = _evidence(candidate, stage=A1_STAGE)
    delta = build_smoke_delta(a0, a1, expected_runtime_tables=("projects",))
    assert delta["passed"] is True
    assert delta["classifications"] == [
        {"table": "projects", "classification": "EXPECTED_RUNTIME_METADATA"}
    ]


def test_f8_candidate_b_backend_opened_yes_fails_final_gate(test_root: Path) -> None:
    candidate_a = _candidate(test_root, "candidate-a")
    candidate_b = _candidate(test_root, "candidate-b")
    lifecycle = _candidate_a_lifecycle(
        _evidence(candidate_a), _evidence(candidate_a, stage=A1_STAGE)
    )
    b0 = _evidence(candidate_b, stage=B0_STAGE, backend_opened=True)
    assert verify_final_candidate_gate(lifecycle, b0)["passed"] is False


def test_f9_candidate_b_rename_failure_fails_final_gate(test_root: Path) -> None:
    candidate_a = _candidate(test_root, "candidate-a")
    candidate_b = _candidate(test_root, "candidate-b")
    lifecycle = _candidate_a_lifecycle(
        _evidence(candidate_a), _evidence(candidate_a, stage=A1_STAGE)
    )
    b0 = _evidence(candidate_b, stage=B0_STAGE, rename_passed=False)
    result = verify_final_candidate_gate(lifecycle, b0)
    assert result["passed"] is False
    assert result["checks"]["candidate_b_rename"] is False


def test_f10_pre_swap_failure_does_not_call_replacement(test_root: Path) -> None:
    canonical = test_root / "canonical.db"
    archive = test_root / "archive.db"
    candidate_a = _candidate(test_root, "candidate-a")
    candidate_b = _candidate(test_root, "candidate-b")
    shutil.copy2(candidate_a, canonical)
    shutil.copy2(candidate_a, archive)
    before = hashlib.sha256(canonical.read_bytes()).hexdigest()
    lifecycle = _candidate_a_lifecycle(
        _evidence(candidate_a), _evidence(candidate_a, stage=A1_STAGE)
    )
    evidence = {
        "candidate_a_evidence": lifecycle,
        "candidate_b_evidence": _evidence(
            candidate_b, stage=B0_STAGE, backend_opened=True
        ),
    }
    with patch("core.migration.cutover.CANONICAL_DATABASE_PATH", canonical), patch(
        "core.migration.cutover.verify_production_interpreter"
    ), patch("core.migration.cutover.os.replace") as replace:
        with pytest.raises(CutoverBlocked, match="Candidate B backend-opened must be NO"):
            perform_production_cutover(
                candidate_b,
                legacy_archive=archive,
                legacy_source=canonical,
                production_cutover=True,
                no_active_writer=lambda: True,
                candidate_handle_free=True,
                legacy_archive_verified=True,
                formal_launcher_evidence=evidence,
            )
    assert hashlib.sha256(canonical.read_bytes()).hexdigest() == before
    replace.assert_not_called()


def test_f11_table_level_delta_names_exact_table(test_root: Path) -> None:
    left = _candidate(test_root, "left")
    right = _candidate(test_root, "right")
    with open_runtime_store(right, candidate=True) as store:
        store.create_project("F11", "Different", "16:9", 24, 1)
    delta = compare_logical_fingerprints(
        logical_data_fingerprint(left), logical_data_fingerprint(right)
    )
    assert delta["different_tables"] == ["projects"]


def test_f12_row_level_delta_names_exact_primary_key(test_root: Path) -> None:
    left = _candidate(test_root, "left")
    right = _candidate(test_root, "right")
    with open_runtime_store(right, candidate=True) as store:
        store.create_project("F12", "Different", "16:9", 24, 1)
    delta = compare_logical_fingerprints(
        logical_data_fingerprint(left), logical_data_fingerprint(right)
    )
    projects = next(item for item in delta["tables"] if item["table"] == "projects")
    assert projects["only_in_right"] == [["F12"]]
