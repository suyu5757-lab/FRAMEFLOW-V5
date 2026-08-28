"""Regression contracts for an isolated successful V5 production cutover.

These tests deliberately never use ``data/frameflow.db``.  They model the
three supported production states with real SQLite files below
``FRAMEFLOW_TEST_TMP``: Legacy, V5-with-separate-Legacy, and rollback.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from uuid import uuid4

from core.migration.backup import create_backup
from core.migration.cutover import fresh_candidate_from_production
from core.migration.legacy_compat import LegacyReadOnlyCompatibility, account_legacy_shots
from core.runtime.persistence import RuntimeStartupConfig, create_runtime_persistence, write_runtime_startup_config
from core.runtime.state_store.factory import inspect_database
from tests.conftest import isolated_legacy_v3_path


REQUIRED_LEGACY_SHOTS = tuple(f"SH{number:03d}" for number in range(4, 21))


def _simulated_cutover_root() -> Path:
    root = Path(os.environ["FRAMEFLOW_TEST_TMP"]) / f"post-cutover-contract-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    return root


def test_v5_canonical_is_not_legacy_and_rollback_is_independent() -> None:
    root = _simulated_cutover_root()
    source_legacy = isolated_legacy_v3_path("post-cutover-source")
    canonical = root / "canonical.db"
    legacy_readonly = root / "legacy_readonly.db"
    config_path = root / "runtime-startup.json"

    # State A: an explicit isolated Legacy source, never the live canonical.
    create_backup(source_legacy, canonical)
    create_backup(source_legacy, legacy_readonly)
    legacy_readonly.chmod(stat.S_IREAD)
    assert inspect_database(canonical)["schema"] == "LEGACY_V3"

    # State B: simulated one-way test-only cutover to an independent V5 file.
    migrated = fresh_candidate_from_production(
        source=canonical,
        work_dir=root / "migration",
        run_id="post-cutover-regression-simulation",
    )
    candidate = Path(migrated["candidate_path"])
    os.replace(candidate, canonical)
    config = RuntimeStartupConfig.build(
        runtime_mode="v5",
        runtime_db=canonical,
        legacy_readonly_db=legacy_readonly,
        production=False,
        generated_by="tests.runtime.test_post_cutover_db_contract",
        cutover_run_id="post-cutover-regression-simulation",
    )
    write_runtime_startup_config(config, config_path)

    canonical_info = inspect_database(canonical)
    assert canonical_info["schema"] == "V5_RUNTIME"
    assert len(canonical_info["domain_tables"]) == 11
    assert canonical.resolve() != legacy_readonly.resolve()

    persistence = create_runtime_persistence(environment=config.to_environment())
    try:
        assert persistence.path == canonical.resolve()
        assert persistence.legacy_path == legacy_readonly.resolve()
    finally:
        persistence.dispose()

    accounting = account_legacy_shots(legacy_readonly, REQUIRED_LEGACY_SHOTS)
    assert (accounting["required"], accounting["accounted"], accounting["unaccounted"]) == (17, 17, 0)
    adapter = LegacyReadOnlyCompatibility(legacy_readonly)
    with adapter.connection() as connection:
        assert connection.execute("SELECT id FROM projects LIMIT 1").fetchone() is not None
        try:
            connection.execute("DELETE FROM projects")
        except Exception as exc:
            assert "readonly" in str(exc).lower()
        else:  # pragma: no cover - explicit safety assertion
            raise AssertionError("Legacy fixture unexpectedly accepted a write")

    # State C: test-only rollback restores Legacy and removes V5 startup state.
    rollback = root / "rollback_legacy.db"
    create_backup(legacy_readonly, rollback)
    os.replace(rollback, canonical)
    config_path.unlink()
    assert inspect_database(canonical)["schema"] == "LEGACY_V3"
    assert not config_path.exists()
