from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from core.migration.candidate_b_lifecycle import (
    CandidateBSealError,
    CandidateBState,
    CandidateBTerminalSeal,
)
from core.migration.cutover import (
    CutoverBlocked,
    candidate_b_file_state,
    handle_free_rename_probe,
    stabilize_candidate_b_database,
)
from core.migration.equivalence import (
    B0_STAGE,
    build_candidate_evidence,
    logical_data_fingerprint,
)
from core.runtime.state_store.factory import open_runtime_store


@pytest.fixture
def test_root() -> Path:
    root = Path(os.environ["FRAMEFLOW_TEST_TMP"]) / f"candidate-b-seal-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    return root


def _candidate(root: Path) -> Path:
    path = root / "candidate-b.db"
    with open_runtime_store(path, initialize=True, candidate=True):
        pass
    return path


def _b0(path: Path) -> dict[str, object]:
    evidence = build_candidate_evidence(
        path,
        source_legacy_sha="a" * 64,
        evidence_stage=B0_STAGE,
        captured_before_backend=True,
        captured_before_swap=True,
        backend_opened=False,
    )
    evidence["row_accounting"] = {
        "unknown": 0,
        "unaccounted": 0,
        "required_shots": 17,
        "accounted_shots": 17,
    }
    evidence["validation_passed"] = True
    return evidence


def _seal_candidate(candidate: Path, lifecycle: CandidateBTerminalSeal, b0: dict[str, object]) -> None:
    lifecycle.mark_evidence_complete(b0)
    lifecycle.begin_final_db_stabilization()
    stabilization = stabilize_candidate_b_database(candidate, b0)
    b0["final_db_stabilization"] = stabilization
    lifecycle.complete_final_db_stabilization(stabilization, b0)


def test_terminal_seal_blocks_logical_reopen_after_rename(test_root: Path) -> None:
    candidate = _candidate(test_root)
    lifecycle = CandidateBTerminalSeal(candidate)
    lifecycle.begin_validation()
    b0 = _b0(candidate)
    _seal_candidate(candidate, lifecycle, b0)

    rename = lifecycle.finalize_rename_probe(handle_free_rename_probe)

    assert rename["passed"] is True
    assert lifecycle.state is CandidateBState.SEALED
    assert lifecycle.post_seal_db_open_count == 0
    with pytest.raises(
        CandidateBSealError,
        match="Candidate B is sealed; database reopen after final rename is forbidden",
    ):
        logical_data_fingerprint(candidate)
    assert lifecycle.post_seal_db_open_count == 0
    assert lifecycle.post_seal_db_open_attempts == 1


def test_terminal_seal_positive_evidence_is_complete_and_terminal(test_root: Path) -> None:
    candidate = _candidate(test_root)
    lifecycle = CandidateBTerminalSeal(candidate)
    lifecycle.begin_validation()
    b0 = _b0(candidate)
    _seal_candidate(candidate, lifecycle, b0)
    result = lifecycle.finalize_rename_probe(handle_free_rename_probe)
    terminal = lifecycle.evidence()

    assert result["passed"] is True
    assert terminal["state"] == "SEALED"
    assert terminal["candidate_b_post_seal_db_open_count"] == 0
    assert terminal["candidate_b_reopened_after_rename"] is False
    assert terminal["sealed_at"]


def test_candidate_b_empty_sidecars_are_resolved_by_sqlite_finalization(test_root: Path) -> None:
    candidate = _candidate(test_root)
    lifecycle = CandidateBTerminalSeal(candidate)
    lifecycle.begin_validation()
    b0 = _b0(candidate)
    before = candidate_b_file_state(candidate)
    assert before["wal"]["exists"] is True
    assert before["wal"]["wal_frame_count"] == 0
    assert before["shm"]["exists"] is True

    _seal_candidate(candidate, lifecycle, b0)
    assert lifecycle.final_db_stabilization is not None
    assert lifecycle.final_db_stabilization["journal_mode_after_stabilization"] == "delete"
    assert candidate_b_file_state(candidate)["wal"]["exists"] is False
    assert candidate_b_file_state(candidate)["shm"]["exists"] is False


def test_candidate_b_pending_wal_fails_without_deleting_frames(test_root: Path) -> None:
    candidate = _candidate(test_root)
    lifecycle = CandidateBTerminalSeal(candidate)
    lifecycle.begin_validation()
    b0 = _b0(candidate)
    lifecycle.mark_evidence_complete(b0)
    lifecycle.begin_final_db_stabilization()

    connection = sqlite3.connect(candidate, timeout=1)
    try:
        assert str(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower() == "wal"
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
            "INSERT INTO projects(id,title,aspect_ratio,fps,target_duration,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            ("PENDING_WAL", "Pending WAL", "16:9", 24, 1, "2000", "2000"),
        )
        connection.commit()
        before = candidate_b_file_state(candidate)
        assert before["wal"]["exists"] is True
        assert int(before["wal"]["wal_frame_count"] or 0) > 0
        with pytest.raises(CutoverBlocked, match="uncheckpointed frames"):
            stabilize_candidate_b_database(candidate, b0)
        after = candidate_b_file_state(candidate)
        assert after["wal"]["exists"] is True
        assert int(after["wal"]["wal_frame_count"] or 0) > 0
    finally:
        connection.close()


def test_candidate_b_open_handle_fails_closed(test_root: Path) -> None:
    candidate = _candidate(test_root)
    lifecycle = CandidateBTerminalSeal(candidate)
    lifecycle.begin_validation()
    b0 = _b0(candidate)
    lifecycle.mark_evidence_complete(b0)
    lifecycle.begin_final_db_stabilization()

    connection = sqlite3.connect(candidate, timeout=0.1)
    try:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(CutoverBlocked, match="final checkpoint was busy"):
            stabilize_candidate_b_database(candidate, b0)
    finally:
        connection.rollback()
        connection.close()
