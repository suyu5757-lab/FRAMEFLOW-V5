from __future__ import annotations

import json
import hashlib
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from core.migration.cutover import fresh_candidate_from_production
from core.migration.port_ownership import parse_netstat_listeners
from core.runtime.persistence import RuntimeStartupConfig, write_runtime_startup_config
from core.runtime.state_store.factory import CANONICAL_DATABASE_PATH
from scripts.verify_t03_sol_final import cleanup_probe_fixtures, request_json, run_http_gate
from tests.conftest import isolated_legacy_v3_path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = PROJECT_ROOT / "scripts" / "start-frameflow-stack.ps1"


def _free_port() -> int:
    import socket

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _listener_pid(port: int) -> int | None:
    output = subprocess.run(
        ["netstat.exe", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    ).stdout
    listeners = parse_netstat_listeners(output, port)
    if not listeners:
        return None
    assert len(listeners) == 1
    return int(listeners[0]["pid"])


def _stop_owned_listener(port: int) -> None:
    pid = _listener_pid(port)
    if pid is None:
        return
    info = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'; $p.CommandLine",
        ],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    ).stdout
    # Windows may hide CIM command-line fields from a non-elevated test
    # process.  The listener PID is still exact and was created by this
    # isolated test port; use the identity check when the fields are visible.
    if info:
        assert "server:app" in info and str(PROJECT_ROOT).lower() in info.lower()
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", f"Stop-Process -Id {pid}"],
        check=True,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and _listener_pid(port) is not None:
        time.sleep(0.2)
    assert _listener_pid(port) is None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _runtime_config_bytes() -> bytes | None:
    path = PROJECT_ROOT / "data" / "runtime-startup.json"
    return path.read_bytes() if path.is_file() else None


def _assert_live_runtime_contract(port: int, candidate: Path) -> None:
    status, payload = request_json(port, "GET", "/api/v2/system/runtime-contract")
    assert status == 200
    assert payload == {
        "database": str(candidate.resolve()),
        "journal_mode": "wal",
        "foreign_keys": 1,
        "busy_timeout": 5000,
    }


def test_exact_runtime_launcher_honors_v5_config_on_first_start_and_restart() -> None:
    root = Path(os.environ["FRAMEFLOW_TEST_TMP"]) / f"mode-aware-integration-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    legacy_source = isolated_legacy_v3_path("mode-aware-integration")
    migrated = fresh_candidate_from_production(
        source=legacy_source,
        work_dir=root / "migration",
        run_id="mode-aware-integration",
    )
    candidate = Path(migrated["candidate_path"])
    legacy = Path(migrated["backup_path"])
    ambient = fresh_candidate_from_production(
        source=legacy_source,
        work_dir=root / "ambient-migration",
        run_id="mode-aware-ambient-production",
    )
    ambient_candidate = Path(ambient["candidate_path"])
    ambient_legacy = Path(ambient["backup_path"])
    ambient_config_path = root / "ambient-runtime-startup.json"
    write_runtime_startup_config(
        RuntimeStartupConfig.build(
            runtime_mode="v5",
            runtime_db=ambient_candidate,
            legacy_readonly_db=ambient_legacy,
            production=True,
            generated_by="tests.runtime.test_mode_aware_launcher_integration",
            cutover_run_id="mode-aware-ambient-production",
        ),
        ambient_config_path,
    )
    config_path = root / "runtime-startup.json"
    write_runtime_startup_config(
        RuntimeStartupConfig.build(
            runtime_mode="v5",
            runtime_db=candidate,
            legacy_readonly_db=legacy,
            production=False,
            generated_by="tests.runtime.test_mode_aware_launcher_integration",
            cutover_run_id="mode-aware-integration",
        ),
        config_path,
    )
    port = _free_port()
    ambient_port = _free_port()
    while ambient_port == port:
        ambient_port = _free_port()
    isolated_maintenance_path = root / "isolated-maintenance-state.json"
    fixture_ids: list[str] = []
    canonical_before = _sha256(CANONICAL_DATABASE_PATH)
    runtime_config_before = _runtime_config_bytes()
    ambient_config_before = ambient_config_path.read_bytes()
    ambient_environment = os.environ.copy()
    ambient_environment.update(
        {
            "FRAMEFLOW_RUNTIME_CONFIG": str(ambient_config_path),
            "FRAMEFLOW_V5_PRODUCTION_SIMULATION": "1",
        }
    )
    try:
        ambient_start = subprocess.run(
            [
                str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"),
                "-m",
                "core.runtime.production_launcher",
                "--start",
                "--config",
                str(ambient_config_path),
                "--host",
                "127.0.0.1",
                "--port",
                str(ambient_port),
            ],
            cwd=PROJECT_ROOT,
            env=ambient_environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )
        assert ambient_start.returncode == 0, ambient_start.stdout + ambient_start.stderr
        assert _listener_pid(ambient_port) is not None
        ambient_after_start = _sha256(ambient_candidate)
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(LAUNCHER),
            "-RuntimeOnly",
            "-RuntimeConfigPath",
            str(config_path),
            "-MaintenanceStatePath",
            str(isolated_maintenance_path),
            "-Port",
            str(port),
        ]
        first = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            env=ambient_environment,
            check=False,
            timeout=90,
        )
        assert first.returncode == 0, first.stdout + first.stderr
        first_gate = run_http_gate(port)
        fixture_ids.append(str(first_gate["fixture_id"]))
        assert first_gate["api_passed"] == 19
        assert first_gate["historical_passed"] == 17
        assert Path(first_gate["doctor"]["database"]).resolve() == candidate.resolve()
        _assert_live_runtime_contract(port, candidate)
        _stop_owned_listener(port)

        second = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            env=ambient_environment,
            check=False,
            timeout=90,
        )
        assert second.returncode == 0, second.stdout + second.stderr
        second_gate = run_http_gate(port, persisted_fixture=fixture_ids[0])
        fixture_ids.append(str(second_gate["fixture_id"]))
        assert second_gate["api_passed"] == 19
        assert second_gate["historical_passed"] == 17
        assert Path(second_gate["doctor"]["database"]).resolve() == candidate.resolve()
        _assert_live_runtime_contract(port, candidate)
        _stop_owned_listener(port)

        invalid_payload = json.loads(config_path.read_text(encoding="utf-8"))
        invalid_payload["legacy_readonly_db"] = str(root / "missing-legacy.db")
        config_path.write_text(json.dumps(invalid_payload), encoding="utf-8")
        invalid = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            env=ambient_environment,
            check=False,
            timeout=30,
        )
        assert invalid.returncode != 0
        assert _listener_pid(port) is None
        assert ambient_config_path.read_bytes() == ambient_config_before
        assert _sha256(ambient_candidate) == ambient_after_start
        assert _sha256(CANONICAL_DATABASE_PATH) == canonical_before
        assert _runtime_config_bytes() == runtime_config_before
    finally:
        _stop_owned_listener(port)
        _stop_owned_listener(ambient_port)
        assert _listener_pid(port) is None
        assert _listener_pid(ambient_port) is None
        if fixture_ids:
            cleanup_probe_fixtures(candidate, fixture_ids)
