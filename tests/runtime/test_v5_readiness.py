from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from core.migration.cutover import fresh_candidate_from_production
from core.runtime import production_launcher
from core.runtime.persistence import RuntimePersistence, RuntimeStartupConfig, write_runtime_startup_config
from core.runtime.readiness import evaluate_capabilities, readiness_summary
from core.runtime.state_store.factory import open_runtime_store
from scripts.verify_t03_sol_final import cleanup_probe_fixtures, run_http_gate
from tests.conftest import isolated_legacy_v3_path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FORMAL_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def _root(label: str) -> Path:
    root = Path(os.environ["FRAMEFLOW_TEST_TMP"]) / f"{label}-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    return root


def _provider_legacy_fixture(label: str, *, dependency_valid: bool = True) -> Path:
    """Create an isolated Legacy archive with the real provider readiness shape."""

    path = isolated_legacy_v3_path(label)
    if dependency_valid:
        return path
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE provider_profiles SET last_health_json=? WHERE id=?",
            (json.dumps({"ok": False, "models": ["opencode-go/gpt-5.6-luna"]}), "opencode-default"),
        )
        connection.commit()
    finally:
        connection.close()
    return path


def _stop_owned_pid(pid: int, port: int) -> None:
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", f"Stop-Process -Id {pid}"],
        check=True,
        capture_output=True,
        text=True,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not production_launcher._listeners(port):
            break
        time.sleep(0.1)


def test_readiness_summary_preserves_legacy_predicates() -> None:
    capabilities = evaluate_capabilities(
        {
            "orchestrator": {"provider_profile_id": "orch", "model": "orch-model"},
            "video": {"provider_profile_id": "video", "model": "video-model"},
        },
        {
            "orch": {
                "id": "orch",
                "display_name": "Orchestrator",
                "enabled": True,
                "last_health": {"ok": True, "models": ["orch-model"]},
            },
            "video": {
                "id": "video",
                "display_name": "Video",
                "enabled": True,
                "last_health": {"ok": True, "models": ["video-model"]},
            },
        },
    )
    summary = readiness_summary(capabilities)
    assert summary["status"] == "ready"
    assert summary["ready"] is True
    assert summary["failing_predicates"] == []


def test_invalid_and_valid_provider_dependencies_control_v5_readiness() -> None:
    for dependency_valid, expected_ready, expected_failing in (
        (False, False, ["orchestrator_capability_ready"]),
        (True, True, []),
    ):
        root = _root("v5-readiness-dependency")
        legacy = _provider_legacy_fixture(
            f"readiness-{dependency_valid}", dependency_valid=dependency_valid
        )
        candidate = root / "candidate.db"
        with open_runtime_store(candidate, initialize=True, candidate=True) as store:
            payload = RuntimePersistence(store, legacy_path=legacy).health_payload()
        assert payload["ready"] is expected_ready
        assert payload["readiness"]["failing_predicates"] == expected_failing
        assert payload["readiness_source"]["available"] is True


@pytest.mark.skipif(
    Path(sys.executable).resolve() != FORMAL_PYTHON.resolve(),
    reason="production-like launcher integration requires the formal project interpreter",
)
def test_production_like_v5_start_and_restart_require_ready() -> None:
    root = _root("v5-production-like")
    legacy = _provider_legacy_fixture("production-like")
    migrated = fresh_candidate_from_production(
        source=legacy,
        work_dir=root / "migration",
        run_id="v5-production-like",
    )
    candidate = Path(migrated["candidate_path"])
    config = root / "runtime-startup.json"
    write_runtime_startup_config(
        RuntimeStartupConfig.build(
            runtime_mode="v5",
            runtime_db=candidate,
            legacy_readonly_db=legacy,
            production=True,
            generated_by="tests.runtime.test_v5_readiness",
            cutover_run_id="v5-production-like",
        ),
        config,
    )
    port = 18889
    if production_launcher._listeners(port):
        pytest.fail(f"test port is occupied: {port}")
    old_simulation = os.environ.get("FRAMEFLOW_V5_PRODUCTION_SIMULATION")
    os.environ["FRAMEFLOW_V5_PRODUCTION_SIMULATION"] = "1"
    fixture_ids: list[str] = []
    try:
        first = production_launcher.start_runtime_for_current_config(
            config, host="127.0.0.1", port=port, timeout=30
        )
        first_gate = run_http_gate(port)
        fixture_ids.append(str(first_gate["fixture_id"]))
        assert first["health"]["runtime_mode"] == "v5"
        assert first["health"]["ready"] is True
        assert first["doctor"]["database"] == str(candidate.resolve())
        assert (first_gate["api_passed"], first_gate["api_failed"]) == (19, 0)
        assert (first_gate["historical_passed"], first_gate["historical_failed"]) == (17, 0)
        _stop_owned_pid(int(first["owner_pid"]), port)

        restarted = production_launcher.start_runtime_for_current_config(
            config, host="127.0.0.1", port=port, timeout=30
        )
        restart_gate = run_http_gate(port, persisted_fixture=fixture_ids[0])
        fixture_ids.append(str(restart_gate["fixture_id"]))
        assert restarted["health"]["runtime_mode"] == "v5"
        assert restarted["health"]["ready"] is True
        assert restarted["doctor"]["database"] == str(candidate.resolve())
        assert (restart_gate["api_passed"], restart_gate["api_failed"]) == (19, 0)
        assert (restart_gate["historical_passed"], restart_gate["historical_failed"]) == (17, 0)
        _stop_owned_pid(int(restarted["owner_pid"]), port)
    finally:
        if production_launcher._listeners(port):
            listener_pid = int(production_launcher._listeners(port)[0]["pid"])
            _stop_owned_pid(listener_pid, port)
        if fixture_ids:
            cleanup_probe_fixtures(candidate, fixture_ids)
        if old_simulation is None:
            os.environ.pop("FRAMEFLOW_V5_PRODUCTION_SIMULATION", None)
        else:
            os.environ["FRAMEFLOW_V5_PRODUCTION_SIMULATION"] = old_simulation
