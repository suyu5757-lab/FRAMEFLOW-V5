from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

from core.migration.preswap import (
    ARCHIVE_REQUIRED_ARTIFACTS,
    finalize_archive_readonly,
    prepare_v5_runtime_config,
    verify_archive_finalization,
    verify_maintenance_freshness,
    verify_runtime_config_binding,
)


def _make_archive(root: Path) -> Path:
    archive = root / "archive"
    archive.mkdir()
    for name in ARCHIVE_REQUIRED_ARTIFACTS:
        (archive / name).write_bytes((name + "\n").encode("utf-8"))
    return archive


def _make_writable(path: Path) -> None:
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


def test_archive_db_readonly_but_json_writable_fails_aggregate(tmp_path: Path) -> None:
    archive = _make_archive(tmp_path)
    try:
        finalized = finalize_archive_readonly(archive)
        assert finalized["passed"] is True
        _make_writable(archive / "v5_candidate_fingerprint.json")
        result = verify_archive_finalization(archive)
        assert result["passed"] is False
        assert result["count"] == 5
        assert result["readonly_count"] == 4
        assert "writable archive artifacts: v5_candidate_fingerprint.json" in result["errors"]
    finally:
        for path in archive.iterdir():
            _make_writable(path)


def test_archive_finalization_sets_all_five_artifacts_readonly(tmp_path: Path) -> None:
    archive = _make_archive(tmp_path)
    try:
        result = finalize_archive_readonly(archive)
        assert result["passed"] is True
        assert result["count"] == 5
        assert result["readonly_count"] == 5
        assert result["extra_files"] == []
        assert all(item["readonly"] is True for item in result["files"])
    finally:
        for path in archive.iterdir():
            _make_writable(path)


def test_runtime_config_binding_requires_current_run_and_archive(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical.db"
    archive = tmp_path / "legacy_frameflow_v3.db"
    other_archive = tmp_path / "other-legacy.db"
    canonical.write_bytes(b"canonical")
    archive.write_bytes(b"archive")
    other_archive.write_bytes(b"other")
    config_path = tmp_path / "runtime-startup.json"

    prepared = prepare_v5_runtime_config(
        config_path=config_path,
        runtime_db=canonical,
        legacy_archive=archive,
        cutover_run_id="T03-TRIPLE-GATE",
    )
    assert prepared["passed"] is True
    assert prepared["runtime_config_exists"] is True
    assert prepared["runtime_config_run_id"] == "T03-TRIPLE-GATE"
    assert prepared["runtime_config_archive_path"] == str(archive.resolve())

    wrong_run = verify_runtime_config_binding(
        config_path,
        expected_run_id="T03-WRONG-RUN",
        expected_runtime_db=canonical,
        expected_legacy_archive=archive,
    )
    assert wrong_run["passed"] is False
    assert "cutover_run_id is not this run" in wrong_run["errors"]

    wrong_archive = verify_runtime_config_binding(
        config_path,
        expected_run_id="T03-TRIPLE-GATE",
        expected_runtime_db=canonical,
        expected_legacy_archive=other_archive,
    )
    assert wrong_archive["passed"] is False
    assert "legacy_readonly_db is not this run archive" in wrong_archive["errors"]


def _maintenance_state(tmp_path: Path, *, expires_at: str) -> Path:
    state_path = tmp_path / "maintenance-state.json"
    state = {
        "ControllerElevated": True,
        "EnteredAt": "2026-08-28T10:00:00+00:00",
        "MaintenancePaused": True,
        "MaintenanceTaskStates": {
            "FRAMEFLOW Runtime Startup": "Disabled",
            "FRAMEFLOW-V3-Service": "Disabled",
        },
        "MaintenanceToken": {
            "created_at_utc": "2026-08-28T10:00:00+00:00",
            "expires_at_utc": expires_at,
        },
        "PortFree": True,
        "RespawnDetected": False,
        "Restored": False,
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return state_path


def test_maintenance_freshness_positive_gate(tmp_path: Path) -> None:
    state_path = _maintenance_state(tmp_path, expires_at="2026-08-28T12:00:00+00:00")
    result = verify_maintenance_freshness(
        state_path,
        now=datetime(2026, 8, 28, 11, 30, tzinfo=UTC),
        port_probe=lambda: {"classification": "FREE", "owner_pid": None},
    )
    assert result["passed"] is True
    assert result["token_ttl_seconds"] == 7200
    assert result["ttl_remaining_seconds"] == 1800


def test_maintenance_freshness_rejects_expired_token(tmp_path: Path) -> None:
    state_path = _maintenance_state(tmp_path, expires_at="2026-08-28T11:00:00+00:00")
    result = verify_maintenance_freshness(
        state_path,
        now=datetime(2026, 8, 28, 11, 30, tzinfo=UTC),
        port_probe=lambda: {"classification": "FREE", "owner_pid": None},
    )
    assert result["passed"] is False
    assert "maintenance token is expired" in result["errors"]
