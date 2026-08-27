from __future__ import annotations

import os
import hashlib
import shutil
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from core.migration.cutover import fresh_candidate_from_production, perform_production_cutover
from core.migration.production_environment import FORMAL_PYTHON
from core.runtime.persistence import RuntimeStartupConfig, write_runtime_startup_config
from core.runtime.state_store.factory import inspect_database


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_DATABASE = PROJECT_ROOT / "data" / "frameflow.db"


def _port_evidence() -> dict[str, object]:
    free = {"classification": "FREE", "owner_pid": None}
    return {
        "passed": True,
        "errors": [],
        "observations": [dict(free), dict(free), dict(free)],
        "maintenance_paused": True,
        "maintenance_tasks": {
            "FRAMEFLOW Runtime Startup": "Disabled",
            "FRAMEFLOW-V3-Service": "Disabled",
        },
    }


def _free_port() -> dict[str, object]:
    return {"classification": "FREE", "owner_pid": None}


def _formal_evidence(candidate: Path, archive: Path) -> dict[str, object]:
    def boot(name: str) -> dict[str, object]:
        return {
            "boot": name,
            "health": {"runtime_mode": "v5"},
            "api_passed": 19,
            "api_failed": 0,
            "historical_passed": 17,
            "historical_failed": 0,
        }

    return {
        "formal_launcher_evidence_version": 1,
        "status": "PASS",
        "candidate": str(candidate.resolve()),
        "legacy": str(archive.resolve()),
        "interpreter_gate": {
            "passed": True,
            "interpreter": str(FORMAL_PYTHON.resolve()),
        },
        "formal_launcher_command": [
            str(FORMAL_PYTHON.resolve()),
            "-m",
            "uvicorn",
            "server:app",
        ],
        "runtime_config_payload": {
            "runtime_mode": "v5",
            "runtime_db": str(candidate.resolve()),
            "legacy_readonly_db": str(archive.resolve()),
        },
        "ownership_environment_fields_injected": [],
        "candidate_sha256_after_probe": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "probe_fixture_cleanup": {"passed": True, "remaining": []},
        "boots": [boot("first_start"), boot("restart")],
    }


def _cutover_fixture() -> tuple[Path, Path, Path, Path]:
    root = Path(os.environ["FRAMEFLOW_TEST_TMP"]) / f"runtime-cutover-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    migrated = fresh_candidate_from_production(
        source=PRODUCTION_DATABASE,
        work_dir=root / "migration",
        run_id="runtime-config-cutover-test",
    )
    candidate = Path(migrated["candidate_path"])
    archive = Path(migrated["backup_path"])
    canonical = root / "canonical.db"
    shutil.copy2(archive, canonical)
    return root, canonical, candidate, archive


def test_authorized_cutover_persists_explicit_restart_safe_v5_configuration() -> None:
    root, canonical, candidate, archive = _cutover_fixture()
    config_path = root / "runtime-startup.json"
    with patch("core.migration.cutover.CANONICAL_DATABASE_PATH", canonical):
        result = perform_production_cutover(
            candidate,
            legacy_archive=archive,
            legacy_source=canonical,
            production_cutover=True,
            no_active_writer=lambda: True,
            candidate_handle_free=True,
            legacy_archive_verified=True,
            runtime_config_path=config_path,
            cutover_run_id="cutover-config-test",
            formal_launcher_evidence=_formal_evidence(candidate, archive),
            port_ownership_evidence=_port_evidence(),
            port_ownership_probe=_free_port,
        )

    config = RuntimeStartupConfig.read(config_path)
    assert config.runtime_mode == "v5"
    assert config.runtime_db == str(canonical.resolve())
    assert config.legacy_readonly_db == str(archive.resolve())
    assert config.production is True
    assert config.cutover_run_id == "cutover-config-test"
    assert result["runtime_config"] == str(config_path.resolve())
    assert inspect_database(canonical)["schema"] == "V5_RUNTIME"
    assert inspect_database(archive)["schema"] == "LEGACY_V3"


def test_failed_replacement_restores_the_prior_runtime_configuration() -> None:
    root, canonical, candidate, archive = _cutover_fixture()
    config_path = root / "runtime-startup.json"
    prior = RuntimeStartupConfig.build(
        runtime_mode="legacy",
        runtime_db=canonical,
        legacy_readonly_db=None,
        production=False,
        generated_by="test-prior-legacy-runtime",
    )
    write_runtime_startup_config(prior, config_path)
    original_replace = os.replace

    def fail_candidate_replace(source: Path | str, destination: Path | str) -> None:
        if Path(source).resolve() == candidate.resolve() and Path(destination).resolve() == canonical.resolve():
            raise PermissionError("injected candidate replacement failure")
        original_replace(source, destination)

    with patch("core.migration.cutover.CANONICAL_DATABASE_PATH", canonical), patch(
        "core.migration.cutover.os.replace", side_effect=fail_candidate_replace
    ):
        with pytest.raises(PermissionError, match="injected candidate replacement failure"):
            perform_production_cutover(
                candidate,
                legacy_archive=archive,
                legacy_source=canonical,
                production_cutover=True,
                no_active_writer=lambda: True,
                candidate_handle_free=True,
                legacy_archive_verified=True,
                runtime_config_path=config_path,
                cutover_run_id="failed-cutover-config-test",
                formal_launcher_evidence=_formal_evidence(candidate, archive),
                port_ownership_evidence=_port_evidence(),
                port_ownership_probe=_free_port,
            )

    restored = RuntimeStartupConfig.read(config_path)
    assert restored == prior
    assert inspect_database(canonical)["schema"] == "LEGACY_V3"
    assert inspect_database(candidate)["schema"] == "V5_RUNTIME"
