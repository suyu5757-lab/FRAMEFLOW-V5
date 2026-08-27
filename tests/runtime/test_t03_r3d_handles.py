from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from core.migration import validation as candidate_validation
from core.migration.cutover import handle_free_rename_probe
from core.runtime.persistence import create_runtime_persistence, shutdown_runtime_persistence
from core.runtime.state_store import StateStore
from core.runtime.state_store.factory import open_runtime_store


TEST_ROOT = Path(os.environ["FRAMEFLOW_TEST_TMP"]) / "r3d-handles"
PRODUCTION_DATABASE = Path(__file__).resolve().parents[2] / "data" / "frameflow.db"


def _candidate(label: str) -> Path:
    root = TEST_ROOT / f"{label}-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    return root / "candidate.db"


def _initialize_candidate(path: Path) -> None:
    with open_runtime_store(path, initialize=True, candidate=True):
        pass


def test_candidate_b_validation_and_real_d_drive_rename_probe() -> None:
    candidate = _candidate("candidate-b")
    _initialize_candidate(candidate)

    result = candidate_validation.validate_candidate(candidate)

    assert result["errors"] == []
    assert result["pragmas"] == {
        "journal_mode": "wal",
        "foreign_keys": 1,
        "busy_timeout": 5000,
    }
    assert handle_free_rename_probe(candidate)["passed"] is True


def test_candidate_b_validation_exception_still_releases_file_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    candidate = _candidate("candidate-b-exception")
    _initialize_candidate(candidate)

    def fail_snapshot(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("injected validation failure")

    monkeypatch.setattr(candidate_validation, "_table_snapshot", fail_snapshot)
    with pytest.raises(RuntimeError, match="injected validation failure"):
        candidate_validation.validate_candidate(candidate)

    assert handle_free_rename_probe(candidate)["passed"] is True


def test_statestore_shutdown_is_idempotent_and_releases_sqlalchemy_pool() -> None:
    candidate = _candidate("statestore")
    store = StateStore(candidate, initialize=True)
    store.close()
    store.dispose()

    with pytest.raises(RuntimeError, match="StateStore is closed"):
        store.pragmas()
    assert handle_free_rename_probe(candidate)["passed"] is True


def test_persistence_factory_shutdown_is_idempotent_and_releases_pool() -> None:
    candidate = _candidate("factory")
    _initialize_candidate(candidate)
    persistence = create_runtime_persistence(
        environment={
            "FRAMEFLOW_RUNTIME_MODE": "v5",
            "FRAMEFLOW_V5_DB": str(candidate),
            "FRAMEFLOW_V5_PRODUCTION": "0",
            "FRAMEFLOW_LEGACY_READONLY_DB": str(PRODUCTION_DATABASE),
        }
    )

    shutdown_runtime_persistence(persistence)
    shutdown_runtime_persistence(persistence)

    assert handle_free_rename_probe(candidate)["passed"] is True


def test_sqlite_sources_do_not_use_connection_context_manager() -> None:
    project_root = Path(__file__).resolve().parents[2]
    sources = (
        project_root / "core" / "migration",
        project_root / "core" / "runtime",
        project_root / "frameflow",
    )
    forbidden = "with " + "sqlite3.connect"
    for root in sources:
        for source in root.rglob("*.py"):
            assert forbidden not in source.read_text(encoding="utf-8"), source
