from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from core.migration.cutover import fresh_candidate_from_production
from core.runtime import production_launcher
from core.runtime.persistence import RuntimeStartupConfig, write_runtime_startup_config
from tests.conftest import isolated_legacy_v3_path


def _test_root(label: str) -> Path:
    root = Path(os.environ["FRAMEFLOW_TEST_TMP"]) / f"{label}-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    return root


def _paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    legacy_source = isolated_legacy_v3_path("mode-aware-launcher")
    migrated = fresh_candidate_from_production(
        source=legacy_source,
        work_dir=tmp_path / "migration",
        run_id="mode-aware-launcher-test",
    )
    return Path(migrated["candidate_path"]), Path(migrated["backup_path"]), legacy_source


def test_absent_default_config_selects_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = isolated_legacy_v3_path("mode-aware-absent")
    missing = _test_root("mode-aware-absent") / "runtime-startup.json"
    monkeypatch.setattr(production_launcher, "DEFAULT_RUNTIME_CONFIG_PATH", missing)

    target = production_launcher.resolve_runtime_target(canonical_database=legacy)

    assert target.mode == "legacy"
    assert target.runtime_db == legacy.resolve()
    assert target.config_present is False


def test_valid_v5_config_selects_v5_and_injects_only_its_environment() -> None:
    root = _test_root("mode-aware-valid")
    candidate, legacy, _ = _paths(root)
    config_path = root / "runtime-startup.json"
    config = RuntimeStartupConfig.build(
        runtime_mode="v5",
        runtime_db=candidate,
        legacy_readonly_db=legacy,
        production=False,
        generated_by="tests.runtime.test_production_launcher",
        cutover_run_id="mode-aware-v5",
    )
    write_runtime_startup_config(config, config_path)

    target = production_launcher.resolve_runtime_target(config_path)
    environment = target.child_environment(
        base={
            "FRAMEFLOW_RUNTIME_MODE": "legacy",
            "FRAMEFLOW_DB_PATH": "stale.db",
            "FRAMEFLOW_V5_DB": "stale-v5.db",
            "FRAMEFLOW_LEGACY_READONLY_DB": "stale-legacy.db",
        }
    )

    assert target.mode == "v5"
    assert target.runtime_db == candidate.resolve()
    assert target.legacy_readonly_db == legacy.resolve()
    assert environment["FRAMEFLOW_RUNTIME_MODE"] == "v5"
    assert environment["FRAMEFLOW_V5_DB"] == str(candidate.resolve())
    assert environment["FRAMEFLOW_LEGACY_READONLY_DB"] == str(legacy.resolve())
    assert environment["FRAMEFLOW_RUNTIME_CONFIG"] == str(config_path.resolve())


def test_explicit_isolated_config_ignores_ambient_production_simulation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _test_root("mode-aware-explicit-isolated")
    candidate, legacy, _ = _paths(root)
    config_path = root / "runtime-startup.json"
    write_runtime_startup_config(
        RuntimeStartupConfig.build(
            runtime_mode="v5",
            runtime_db=candidate,
            legacy_readonly_db=legacy,
            production=False,
            generated_by="tests.runtime.test_production_launcher",
            cutover_run_id="explicit-isolated-wins",
        ),
        config_path,
    )
    monkeypatch.setenv("FRAMEFLOW_V5_PRODUCTION_SIMULATION", "1")

    target = production_launcher.resolve_runtime_target(config_path)

    assert target.production is False
    assert target.production_simulation is False
    assert target.runtime_db == candidate.resolve()


def test_invalid_v5_config_fails_closed_before_start() -> None:
    root = _test_root("mode-aware-invalid")
    candidate, legacy, _ = _paths(root)
    config_path = root / "invalid-runtime-startup.json"
    payload = json.loads(
        RuntimeStartupConfig.build(
            runtime_mode="v5",
            runtime_db=candidate,
            legacy_readonly_db=legacy,
            production=False,
            generated_by="tests.runtime.test_production_launcher",
        ).as_json()
    )
    payload["legacy_readonly_db"] = str(root / "missing-legacy.db")
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(production_launcher.ProductionLauncherError, match="archive does not exist"):
        production_launcher.resolve_runtime_target(config_path)


def test_v5_runtime_evidence_rejects_http_200_without_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    target = production_launcher.RuntimeTarget(
        mode="v5",
        runtime_db=Path("candidate.db").resolve(),
        legacy_readonly_db=Path("legacy.db").resolve(),
        production=True,
        config_path=Path("runtime-startup.json").resolve(),
        config_present=True,
    )
    monkeypatch.setattr(
        production_launcher,
        "_listeners",
        lambda _port: [{"pid": 12345}],
    )
    monkeypatch.setattr(
        production_launcher,
        "_get_json",
        lambda _url: (
            200,
            {
                "runtime_mode": "v5",
                "status": "not_ready",
                "ready": False,
                "readiness": {"failing_predicates": ["orchestrator_capability_ready"]},
            },
        )
        if "health" in _url
        else (200, {"database": str(target.runtime_db)}),
    )
    with pytest.raises(production_launcher.ProductionLauncherError, match="readiness gate failed"):
        production_launcher._runtime_evidence(target, 8787)


def test_scheduled_task_setup_uses_mode_aware_runtime_launcher() -> None:
    narrow_setup = Path("scripts/update-frameflow-service-task.ps1").read_text(encoding="utf-8")
    startup = Path("scripts/start-frameflow-stack.ps1").read_text(encoding="utf-8")

    assert "Set-ScheduledTask" in narrow_setup
    assert "Register-ScheduledTask" not in narrow_setup
    assert "FRAMEFLOW-V3-Service" in narrow_setup
    assert "-RuntimeOnly" in narrow_setup
    assert "core.runtime.production_launcher" in startup
    assert "runtime_mode" in startup
    assert "Runtime database mismatch" in startup


def test_restore_policy_is_not_a_runtime_start() -> None:
    maintenance = Path("scripts/frameflow-maintenance.ps1").read_text(encoding="utf-8")
    policy_start = maintenance.index("function Restore-AutostartPolicy")
    policy_body_start = maintenance.index("# This is policy restoration only", policy_start)
    policy_end = maintenance.index("return $StateValue", policy_body_start)
    policy_function = maintenance[policy_start:policy_end]
    policy = maintenance[policy_body_start:policy_end]

    assert "TargetRuntimeStarted" in policy_function
    assert "Set-TaskEnabledState" in policy
    assert "Start-ScheduledTask" not in policy
