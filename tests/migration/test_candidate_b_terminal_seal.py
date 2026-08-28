from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from core.migration.candidate_b_lifecycle import (
    CandidateBSealError,
    CandidateBState,
    CandidateBTerminalSeal,
)
from core.migration.cutover import handle_free_rename_probe
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


def test_terminal_seal_blocks_logical_reopen_after_rename(test_root: Path) -> None:
    candidate = _candidate(test_root)
    lifecycle = CandidateBTerminalSeal(candidate)
    lifecycle.begin_validation()
    b0 = _b0(candidate)
    lifecycle.mark_evidence_complete(b0)
    lifecycle.mark_handles_closed()

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
    lifecycle.mark_evidence_complete(b0)
    lifecycle.mark_handles_closed()
    result = lifecycle.finalize_rename_probe(handle_free_rename_probe)
    terminal = lifecycle.evidence()

    assert result["passed"] is True
    assert terminal["state"] == "SEALED"
    assert terminal["candidate_b_post_seal_db_open_count"] == 0
    assert terminal["candidate_b_reopened_after_rename"] is False
    assert terminal["sealed_at"]
