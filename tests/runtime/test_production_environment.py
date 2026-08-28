from __future__ import annotations

import hashlib
import json
import os
import socket
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from core.migration.backup import create_backup
from core.migration.cutover import CutoverBlocked, fresh_candidate_from_production, perform_production_cutover
from core.migration.production_environment import (
    FORMAL_PYTHON,
    REQUIRED_RUNTIME_IMPORTS,
    ProductionEnvironmentError,
    declared_jsonschema_version,
    verify_production_interpreter,
)
from tests.conftest import isolated_legacy_v3_path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.fixture(scope="module")
def formal_probe() -> dict[str, object]:
    root = Path(os.environ["FRAMEFLOW_TEST_TMP"]) / f"formal-launcher-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    legacy_source = isolated_legacy_v3_path("formal-launcher-source")
    production_before = _sha256(legacy_source)
    legacy = root / "legacy-readonly.db"
    create_backup(legacy_source, legacy)
    legacy.chmod(stat.S_IREAD)
    migrated = fresh_candidate_from_production(
        source=legacy,
        work_dir=root / "migration",
        run_id="formal-launcher-environment-test",
    )
    candidate = Path(migrated["candidate_path"])
    config = root / "runtime-startup.json"
    output = root / "formal-launcher-evidence.json"
    completed = subprocess.run(
        [
            str(FORMAL_PYTHON),
            str(PROJECT_ROOT / "scripts" / "verify_t03_sol_final.py"),
            "--candidate",
            str(candidate),
            "--legacy",
            str(legacy),
            "--config",
            str(config),
            "--port",
            str(_free_port()),
            "--output",
            str(output),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(
            "formal launcher probe failed:\n"
            f"STDOUT={completed.stdout}\nSTDERR={completed.stderr}"
        )
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["test_root"] = str(root)
    payload["production_before"] = production_before
    payload["production_after"] = _sha256(legacy_source)
    payload["legacy_source"] = str(legacy_source)
    return payload


def test_e1_formal_venv_interpreter_identity() -> None:
    result = verify_production_interpreter()
    assert Path(result["interpreter"]) == FORMAL_PYTHON.resolve()
    assert Path(result["identity"]["prefix"]) == (PROJECT_ROOT / ".venv").resolve()


def test_e2_required_runtime_import_smoke() -> None:
    result = verify_production_interpreter()
    assert tuple(result["identity"]["imports"]) == REQUIRED_RUNTIME_IMPORTS


def test_e3_jsonschema_is_declared_and_installed() -> None:
    result = verify_production_interpreter()
    assert declared_jsonschema_version() == "4.26.0"
    assert result["jsonschema_installed"] == "4.26.0"
    assert result["pip_check"] == "No broken requirements found."
    assert result["manifest_check"] == "PASS"


def test_e4_formal_launcher_candidate_startup(formal_probe: dict[str, object]) -> None:
    first = formal_probe["boots"][0]
    assert formal_probe["status"] == "PASS"
    assert first["boot"] == "first_start"
    assert first["health"]["runtime_mode"] == "v5"


def test_e5_formal_launcher_first_start_19_of_19(formal_probe: dict[str, object]) -> None:
    first = formal_probe["boots"][0]
    assert (first["api_passed"], first["api_failed"]) == (19, 0)


def test_e6_formal_launcher_first_start_17_of_17(formal_probe: dict[str, object]) -> None:
    first = formal_probe["boots"][0]
    assert (first["historical_passed"], first["historical_failed"]) == (17, 0)


def test_e7_formal_launcher_restart_gates(formal_probe: dict[str, object]) -> None:
    restarted = formal_probe["boots"][1]
    assert restarted["boot"] == "restart"
    assert restarted["health"]["runtime_mode"] == "v5"
    assert (restarted["api_passed"], restarted["api_failed"]) == (19, 0)
    assert (restarted["historical_passed"], restarted["historical_failed"]) == (17, 0)


def test_e8_wrong_interpreter_fails_identity_gate(formal_probe: dict[str, object]) -> None:
    wrong_python = Path(sys.base_prefix) / "python.exe"
    assert wrong_python.resolve() != FORMAL_PYTHON.resolve()
    with pytest.raises(ProductionEnvironmentError, match="wrong production interpreter"):
        verify_production_interpreter(wrong_python)
    root = Path(str(formal_probe["test_root"]))
    completed = subprocess.run(
        [
            str(wrong_python),
            str(PROJECT_ROOT / "scripts" / "verify_t03_sol_final.py"),
            "--candidate",
            str(formal_probe["candidate"]),
            "--legacy",
            str(formal_probe["legacy"]),
            "--config",
            str(root / "wrong-interpreter-config.json"),
            "--port",
            str(_free_port()),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "formal launcher probe requires" in completed.stderr
    assert not (root / "wrong-interpreter-config.json").exists()


def test_e9_missing_dependency_fails_import_gate_before_launcher() -> None:
    failure = subprocess.CompletedProcess(
        args=[str(FORMAL_PYTHON)],
        returncode=1,
        stdout="",
        stderr="ModuleNotFoundError: No module named 'jsonschema'",
    )
    with patch("core.migration.production_environment.subprocess.run", return_value=failure):
        with pytest.raises(ProductionEnvironmentError, match="import smoke failed before swap"):
            verify_production_interpreter()


def test_e10_pre_swap_failure_leaves_production_untouched(
    formal_probe: dict[str, object],
) -> None:
    legacy_source = Path(str(formal_probe["legacy_source"]))
    before = _sha256(legacy_source)
    candidate = Path(str(formal_probe["candidate"]))
    legacy = Path(str(formal_probe["legacy"]))
    with patch("core.migration.cutover.os.replace") as replace:
        with pytest.raises(CutoverBlocked, match="formal launcher pre-swap gate failed"):
            perform_production_cutover(
                candidate,
                legacy_archive=legacy,
                production_cutover=True,
                no_active_writer=lambda: True,
                candidate_handle_free=True,
                legacy_archive_verified=True,
                formal_launcher_evidence=None,
            )
    replace.assert_not_called()
    assert _sha256(legacy_source) == before
    assert formal_probe["production_before"] == formal_probe["production_after"]
