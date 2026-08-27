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
    build_candidate_evidence,
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


def _evidence(path: Path, *, source_sha: str = "a" * 64, **changes: object) -> dict[str, object]:
    evidence = build_candidate_evidence(path, source_legacy_sha=source_sha)
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
            "backend_opened": False,
            "rename_passed": True,
        }
    )
    evidence.update(changes)
    return evidence


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
    result = verify_final_candidate_gate(
        _evidence(
            candidate_a,
            formal_launcher_evidence={
                "status": "PASS",
                "boots": [
                    {"boot": "first_start", "health": {"runtime_mode": "v5"}, "api_passed": 19, "api_failed": 0, "historical_passed": 17, "historical_failed": 0},
                    {"boot": "restart", "health": {"runtime_mode": "v5"}, "api_passed": 19, "api_failed": 0, "historical_passed": 17, "historical_failed": 0},
                ],
            },
        ),
        _evidence(candidate_b, rename_passed=False),
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
        "candidate_a_evidence": _evidence(
            candidate_a,
            formal_launcher_evidence={
                "status": "PASS",
                "boots": [
                    {"boot": "first_start", "health": {"runtime_mode": "v5"}, "api_passed": 19, "api_failed": 0, "historical_passed": 17, "historical_failed": 0},
                    {"boot": "restart", "health": {"runtime_mode": "v5"}, "api_passed": 19, "api_failed": 0, "historical_passed": 17, "historical_failed": 0},
                ],
            },
        ),
        "candidate_b_evidence": _evidence(candidate_b, rename_passed=False),
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
