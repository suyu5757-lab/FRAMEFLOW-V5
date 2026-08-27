from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from core.migration.cutover import CutoverBlocked, perform_production_cutover
from core.migration.port_ownership import (
    FOREIGN_PROCESS,
    FRAMEFLOW_EXPECTED,
    FRAMEFLOW_STALE,
    FRAMEFLOW_SUPERVISED,
    FREE,
    UNKNOWN,
    PortOwnershipError,
    assert_exclusive_port_evidence,
    build_exclusive_port_evidence,
    classify_port_owner,
    parse_netstat_listeners,
    verify_lifecycle_restoration,
)


def _sample(classification: str = FREE, pid: int | None = None) -> dict[str, object]:
    return {"classification": classification, "owner_pid": pid}


def _paused_tasks() -> dict[str, str]:
    return {
        "FRAMEFLOW Runtime Startup": "Disabled",
        "FRAMEFLOW-V3-Service": "Disabled",
    }


def test_port1_free_port_passes_exclusive_gate() -> None:
    evidence = build_exclusive_port_evidence(
        [_sample(), _sample(), _sample()], maintenance_tasks=_paused_tasks()
    )
    assert evidence["passed"] is True
    assert_exclusive_port_evidence(evidence)


def test_port2_expected_frameflow_legacy_owner_is_classified() -> None:
    snapshot = {
        "listeners": [{"pid": 39204}],
        "process": {"Name": "python.exe"},
        "doctor_matches_frameflow": True,
        "task_sources": [],
    }
    assert classify_port_owner(snapshot) == FRAMEFLOW_EXPECTED


def test_port3_supervisor_respawn_is_detected_and_fails() -> None:
    observations = [
        _sample(FREE),
        _sample(FRAMEFLOW_SUPERVISED, 100),
        _sample(FRAMEFLOW_SUPERVISED, 101),
    ]
    evidence = build_exclusive_port_evidence(
        observations, maintenance_tasks=_paused_tasks()
    )
    assert evidence["passed"] is False
    assert any("PID changed" in error for error in evidence["errors"])


def test_port4_foreign_process_fails_closed() -> None:
    snapshot = {
        "listeners": [{"pid": 44}],
        "process": {
            "Name": "foreign.exe",
            "ExecutablePath": r"C:\Foreign\foreign.exe",
            "CommandLine": "foreign.exe --listen 8787",
        },
        "doctor_matches_frameflow": False,
        "task_sources": [],
    }
    assert classify_port_owner(snapshot) == FOREIGN_PROCESS
    with pytest.raises(PortOwnershipError):
        assert_exclusive_port_evidence(
            build_exclusive_port_evidence(
                [_sample(FOREIGN_PROCESS, 44)] * 3,
                maintenance_tasks=_paused_tasks(),
            )
        )


def test_port5_unknown_process_fails_closed() -> None:
    snapshot = {
        "listeners": [{"pid": 55}],
        "process": {"Name": ""},
        "doctor_matches_frameflow": False,
        "task_sources": [],
    }
    assert classify_port_owner(snapshot) == UNKNOWN


def test_port6_stale_frameflow_process_is_classified() -> None:
    snapshot = {
        "listeners": [{"pid": 66}],
        "process": {
            "Name": "python.exe",
            "CommandLine": (
                r"D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe "
                "-m uvicorn server:app"
            ),
        },
        "doctor_matches_frameflow": False,
        "task_sources": [],
    }
    assert classify_port_owner(snapshot) == FRAMEFLOW_STALE


def test_port7_owner_pid_change_during_gate_is_detected() -> None:
    evidence = build_exclusive_port_evidence(
        [
            _sample(FRAMEFLOW_SUPERVISED, 70),
            _sample(FRAMEFLOW_SUPERVISED, 71),
            _sample(FREE),
        ],
        maintenance_tasks=_paused_tasks(),
    )
    assert evidence["passed"] is False
    assert "port owner PID changed during the gate" in evidence["errors"]


def test_port7b_live_owner_change_before_swap_is_detected() -> None:
    root = Path(os.environ["FRAMEFLOW_TEST_TMP"]) / f"port7b-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    canonical = root / "canonical.db"
    candidate = root / "candidate.db"
    archive = root / "archive.db"
    canonical.write_bytes(b"legacy-production")
    candidate.write_bytes(b"candidate")
    archive.write_bytes(b"archive")
    free_evidence = build_exclusive_port_evidence(
        [_sample(), _sample(), _sample()], maintenance_tasks=_paused_tasks()
    )
    probe_values = iter([_sample(), _sample(FOREIGN_PROCESS, 77)])
    with patch("core.migration.cutover.CANONICAL_DATABASE_PATH", canonical), patch(
        "core.migration.cutover.verify_production_interpreter"
    ), patch("core.migration.cutover.verify_formal_launcher_evidence"), patch(
        "core.migration.cutover.inspect_legacy_archive", return_value={"passed": True}
    ), patch("core.migration.cutover.os.replace") as replace:
        with pytest.raises(CutoverBlocked, match="production port changed"):
            perform_production_cutover(
                candidate,
                legacy_archive=archive,
                legacy_source=canonical,
                production_cutover=True,
                no_active_writer=lambda: True,
                candidate_handle_free=True,
                legacy_archive_verified=True,
                formal_launcher_evidence={},
                port_ownership_evidence=free_evidence,
                port_ownership_probe=lambda: next(probe_values),
            )
    assert canonical.read_bytes() == b"legacy-production"
    replace.assert_not_called()


def test_port8_pre_swap_port_failure_leaves_production_untouched() -> None:
    root = Path(os.environ["FRAMEFLOW_TEST_TMP"]) / f"port8-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    canonical = root / "canonical.db"
    candidate = root / "candidate.db"
    archive = root / "archive.db"
    canonical.write_bytes(b"legacy-production")
    candidate.write_bytes(b"candidate")
    archive.write_bytes(b"archive")
    before = canonical.read_bytes()
    evidence = build_exclusive_port_evidence(
        [_sample(FOREIGN_PROCESS, 88)] * 3,
        maintenance_tasks=_paused_tasks(),
    )
    with patch("core.migration.cutover.CANONICAL_DATABASE_PATH", canonical), patch(
        "core.migration.cutover.verify_production_interpreter"
    ), patch("core.migration.cutover.verify_formal_launcher_evidence"), patch(
        "core.migration.cutover.os.replace"
    ) as replace:
        with pytest.raises(CutoverBlocked, match="exclusive production port gate failed"):
            perform_production_cutover(
                candidate,
                legacy_archive=archive,
                legacy_source=canonical,
                production_cutover=True,
                no_active_writer=lambda: True,
                candidate_handle_free=True,
                legacy_archive_verified=True,
                formal_launcher_evidence={},
                port_ownership_evidence=evidence,
                port_ownership_probe=lambda: _sample(FOREIGN_PROCESS, 88),
            )
    assert canonical.read_bytes() == before
    replace.assert_not_called()


def test_port9_paused_maintenance_sources_have_no_respawn_window() -> None:
    evidence = build_exclusive_port_evidence(
        [_sample(), _sample(), _sample(), _sample()],
        maintenance_tasks=_paused_tasks(),
    )
    assert evidence["passed"] is True
    assert evidence["maintenance_paused"] is True


def test_port10_rollback_restores_process_lifecycle_state() -> None:
    original = {
        "FRAMEFLOW Runtime Startup": {"Enabled": True},
        "FRAMEFLOW-V3-Service": {"Enabled": True},
    }
    restored = {
        "FRAMEFLOW Runtime Startup": {"Enabled": True},
        "FRAMEFLOW-V3-Service": {"Enabled": True},
    }
    result = verify_lifecycle_restoration(
        original,
        restored,
        runtime_was_listening=True,
        restored_owner_pid=39204,
    )
    assert result["passed"] is True


def test_netstat_parser_returns_exact_listening_pid() -> None:
    output = """
      TCP    127.0.0.1:8787    0.0.0.0:0    LISTENING    39204
      TCP    127.0.0.1:8787    127.0.0.1:50000    TIME_WAIT    0
    """
    assert parse_netstat_listeners(output) == [
        {
            "local_address": "127.0.0.1",
            "local_port": 8787,
            "state": "LISTENING",
            "pid": 39204,
        }
    ]
