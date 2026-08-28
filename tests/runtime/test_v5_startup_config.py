from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from core.migration.cutover import fresh_candidate_from_production
from core.migration.legacy_compat import LegacyReadOnlyCompatibility
from core.runtime.persistence import (
    RuntimeModeError,
    RuntimeStartupConfig,
    create_runtime_persistence,
    resolve_runtime_environment,
    write_runtime_startup_config,
)
from tests.conftest import isolated_legacy_v3_path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
@pytest.fixture(scope="module")
def isolated_runtime() -> dict[str, Path]:
    root = Path(os.environ["FRAMEFLOW_TEST_TMP"]) / f"v5-startup-config-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    legacy_source = isolated_legacy_v3_path("v5-startup-source")
    migrated = fresh_candidate_from_production(
        source=legacy_source,
        work_dir=root / "migration",
        run_id="startup-config-test",
    )
    return {
        "root": root,
        "candidate": Path(migrated["candidate_path"]),
        "legacy": Path(migrated["backup_path"]),
    }


def _config(paths: dict[str, Path], **changes: object) -> RuntimeStartupConfig:
    values: dict[str, object] = {
        "runtime_mode": "v5",
        "runtime_db": paths["candidate"],
        "legacy_readonly_db": paths["legacy"],
        "production": False,
        "generated_by": "tests.runtime.test_v5_startup_config",
        "cutover_run_id": "isolated-verification",
    }
    values.update(changes)
    return RuntimeStartupConfig.build(**values)  # type: ignore[arg-type]


def test_valid_persisted_configuration_is_authoritative_and_opens(
    isolated_runtime: dict[str, Path],
) -> None:
    config_path = isolated_runtime["root"] / "runtime-startup.json"
    write_runtime_startup_config(_config(isolated_runtime), config_path)
    environment = resolve_runtime_environment(
        {
            "FRAMEFLOW_RUNTIME_CONFIG": str(config_path),
            "FRAMEFLOW_RUNTIME_MODE": "legacy",
        }
    )
    assert environment["FRAMEFLOW_RUNTIME_MODE"] == "v5"
    assert environment["FRAMEFLOW_V5_DB"] == str(isolated_runtime["candidate"].resolve())
    assert environment["FRAMEFLOW_LEGACY_READONLY_DB"] == str(
        isolated_runtime["legacy"].resolve()
    )
    persistence = create_runtime_persistence(environment=environment)
    try:
        assert persistence.path == isolated_runtime["candidate"].resolve()
        assert persistence.legacy_path == isolated_runtime["legacy"].resolve()
    finally:
        persistence.dispose()
    assert config_path.read_bytes().startswith(b"{")


def test_v5_missing_legacy_configuration_fails_closed(
    isolated_runtime: dict[str, Path],
) -> None:
    with pytest.raises(RuntimeModeError, match="requires FRAMEFLOW_LEGACY_READONLY_DB"):
        create_runtime_persistence(
            environment={
                "FRAMEFLOW_RUNTIME_MODE": "v5",
                "FRAMEFLOW_V5_DB": str(isolated_runtime["candidate"]),
            }
        )


def test_backend_process_exits_during_startup_when_v5_config_is_incomplete(
    isolated_runtime: dict[str, Path],
) -> None:
    config_path = isolated_runtime["root"] / "missing-legacy-runtime-startup.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime_mode": "v5",
                "runtime_db": str(isolated_runtime["candidate"]),
                "legacy_readonly_db": None,
                "production": False,
                "generated_by": "failure-injection",
                "generated_at": "2026-08-27T00:00:00+00:00",
                "cutover_run_id": "missing-legacy",
            }
        ),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["FRAMEFLOW_RUNTIME_CONFIG"] = str(config_path)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from fastapi.testclient import TestClient; import server; "
            "client=TestClient(server.app); client.__enter__()",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "requires legacy_readonly_db" in completed.stderr


@pytest.mark.parametrize(
    ("case", "legacy_kind", "expected"),
    (
        ("invalid-path", "missing", "legacy archive does not exist"),
        ("same-as-v5", "candidate", "must be different files"),
        ("random-sqlite", "random", "missing required tables"),
    ),
)
def test_backend_startup_rejects_invalid_legacy_sources(
    isolated_runtime: dict[str, Path],
    case: str,
    legacy_kind: str,
    expected: str,
) -> None:
    if legacy_kind == "missing":
        legacy = isolated_runtime["root"] / "does-not-exist.db"
    elif legacy_kind == "candidate":
        legacy = isolated_runtime["candidate"]
    else:
        legacy = isolated_runtime["root"] / f"{case}.db"
        connection = sqlite3.connect(legacy)
        try:
            connection.execute("CREATE TABLE arbitrary(value TEXT)")
            connection.commit()
        finally:
            connection.close()
    payload = json.loads(_config(isolated_runtime).as_json())
    payload["legacy_readonly_db"] = str(legacy.resolve(strict=False))
    config_path = isolated_runtime["root"] / f"{case}-runtime-startup.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    environment = os.environ.copy()
    environment["FRAMEFLOW_RUNTIME_CONFIG"] = str(config_path)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from fastapi.testclient import TestClient; import server; "
            "client=TestClient(server.app); client.__enter__()",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert expected in completed.stderr


def test_v5_invalid_legacy_path_fails_closed(isolated_runtime: dict[str, Path]) -> None:
    with pytest.raises(RuntimeModeError, match="does not exist"):
        create_runtime_persistence(
            environment={
                "FRAMEFLOW_RUNTIME_MODE": "v5",
                "FRAMEFLOW_V5_DB": str(isolated_runtime["candidate"]),
                "FRAMEFLOW_LEGACY_READONLY_DB": str(
                    isolated_runtime["root"] / "missing-legacy.db"
                ),
            }
        )


def test_v5_database_cannot_be_its_own_legacy_source(
    isolated_runtime: dict[str, Path],
) -> None:
    with pytest.raises(RuntimeModeError, match="must be different files"):
        create_runtime_persistence(
            environment={
                "FRAMEFLOW_RUNTIME_MODE": "v5",
                "FRAMEFLOW_V5_DB": str(isolated_runtime["candidate"]),
                "FRAMEFLOW_LEGACY_READONLY_DB": str(isolated_runtime["candidate"]),
            }
        )


def test_random_sqlite_database_is_rejected_as_legacy(
    isolated_runtime: dict[str, Path],
) -> None:
    random_db = isolated_runtime["root"] / "random.db"
    connection = sqlite3.connect(random_db)
    try:
        connection.execute("CREATE TABLE arbitrary(value TEXT)")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(RuntimeModeError, match="missing required tables"):
        create_runtime_persistence(
            environment={
                "FRAMEFLOW_RUNTIME_MODE": "v5",
                "FRAMEFLOW_V5_DB": str(isolated_runtime["candidate"]),
                "FRAMEFLOW_LEGACY_READONLY_DB": str(random_db),
            }
        )


def test_legacy_archive_allows_select_and_blocks_sql_writes(
    isolated_runtime: dict[str, Path],
) -> None:
    adapter = LegacyReadOnlyCompatibility(isolated_runtime["legacy"])
    assert adapter.validation["schema"] == "LEGACY_V3"
    with adapter.connection() as connection:
        assert connection.execute("SELECT id FROM projects LIMIT 1").fetchone() is not None
        for statement in (
            "INSERT INTO projects(id) VALUES('INVALID')",
            "UPDATE projects SET id=id",
            "DELETE FROM projects",
        ):
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                connection.execute(statement)


def test_persisted_config_has_complete_audit_metadata(
    isolated_runtime: dict[str, Path],
) -> None:
    config_path = isolated_runtime["root"] / "audit-runtime-startup.json"
    write_runtime_startup_config(_config(isolated_runtime), config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["runtime_mode"] == "v5"
    assert payload["generated_by"] == "tests.runtime.test_v5_startup_config"
    assert payload["generated_at"].endswith("+00:00")
    assert payload["cutover_run_id"] == "isolated-verification"
