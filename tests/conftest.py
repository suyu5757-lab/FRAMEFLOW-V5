"""Windows-safe test environment for FRAMEFLOW runtime tests.

The host's user TEMP directory can contain inherited ACLs that prevent a
SQLite database from being opened inside a newly-created TemporaryDirectory.
Keep test-only temporary state inside the repository's writable workspace and
make the setting visible to subprocesses as well.
"""

from __future__ import annotations

import os
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from tests.support.runtime_isolation import forbid_real_production_network


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_TMP = PROJECT_ROOT / ".tmp" / "tests"
TEST_TMP = Path(os.environ.get("FRAMEFLOW_TEST_TMP") or DEFAULT_TEST_TMP).expanduser().resolve(
    strict=False
)
TEST_TMP.mkdir(parents=True, exist_ok=True)

# tempfile caches the resolved directory after the first gettempdir() call;
# set both the cache and the environment before test modules are imported.
os.environ["FRAMEFLOW_TEST_TMP"] = str(TEST_TMP)
os.environ["TEMP"] = str(TEST_TMP)
os.environ["TMP"] = str(TEST_TMP)
tempfile.tempdir = str(TEST_TMP)


@pytest.fixture(autouse=True)
def guard_legacy_regression_boundaries(request: pytest.FixtureRequest):
    """Keep Legacy regression tests off real config, DB, and port 8787."""

    filename = Path(str(request.node.fspath)).name
    guarded = {
        "test_v3.py",
        "test_recovery_v3.py",
        "test_v3_function_matrix.py",
    }
    if filename in guarded:
        with forbid_real_production_network():
            yield
    else:
        yield


def pytest_configure(config: object) -> None:
    """Inject an isolated canonical path for post-cutover suite simulation.

    This hook is test-only and opt-in.  It never changes production path
    resolution outside pytest; the environment value must name an existing
    SQLite fixture created by the invoking test harness.
    """

    del config
    override = os.environ.get("FRAMEFLOW_TEST_CANONICAL_DB")
    if not override:
        return
    canonical = Path(override).expanduser().resolve(strict=False)
    if not canonical.is_file():
        raise RuntimeError(f"FRAMEFLOW_TEST_CANONICAL_DB does not exist: {canonical}")

    from core.migration import backup, online, v3_to_v5
    from core.runtime.persistence import factory as persistence_factory
    from core.runtime.state_store import factory as state_store_factory
    from core.runtime.state_store import store as state_store

    state_store_factory.CANONICAL_DATABASE_PATH = canonical
    state_store.DEFAULT_DATABASE_PATH = canonical
    persistence_factory.CANONICAL_DATABASE_PATH = canonical
    backup.PRODUCTION_DATABASE = canonical
    online.PRODUCTION_DATABASE = canonical
    v3_to_v5.PRODUCTION_DATABASE = canonical


def create_legacy_v3_fixture(path: Path) -> Path:
    """Create an isolated read-only-compatible Legacy V3 SQLite source.

    Runtime tests must never use the live canonical database as a legacy
    fixture.  This intentionally small but real Legacy database supplies the
    schema-16 project document and SH004--SH020 records required by the
    migration and compatibility contracts.
    """

    path = path.expanduser().resolve(strict=False)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite test legacy fixture: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    shots = [
        {
            "id": f"SH{number:03d}",
            "sequenceId": "SQ001",
            "status": "DRAFT",
            "duration": 0,
            # Deliberately incomplete v1 records: they remain on the explicit
            # read-only compatibility path rather than silently becoming V5.
            "purpose": "historical compatibility fixture",
        }
        for number in range(4, 21)
    ]
    document = {
        "id": "TEST_LEGACY_PROJECT",
        "name": "Isolated Legacy Fixture",
        "ratio": "16:9",
        "fps": 24,
        "duration": 1,
        "shots": shots,
        "assets": [],
    }
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                document_json TEXT NOT NULL,
                revision INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                lifecycle_status TEXT NOT NULL
            );
            """
        )
        # The offline migrator intentionally reads these legacy tables even
        # when they have no rows.  Keep their shape minimal: no test is
        # permitted to source them from the real canonical database.
        for table_name in (
            "agent_candidate_versions_v5",
            "agent_plan_events_v5",
            "agent_plans_v5",
            "approval_gates_v3",
            "approvals",
            "artifact_lineage_v3",
            "artifacts",
            "asset_boards_v7",
            "asset_comparisons_v4",
            "asset_dependencies_v4",
            "asset_events",
            "asset_qa_runs",
            "asset_reference_roles_v4",
            "asset_versions",
            "audit_events_v16",
            "backup_records_v11",
            "capability_bindings",
            "conversations",
            "generation_snapshots_v9",
            "media_proxies_v6",
            "messages",
            "node_runs_v3",
            "prompt_versions",
            "provider_profiles",
            "recovery_plans_v11",
            "render_jobs_v6",
            "story_versions",
            "story_workflow_chains",
            "task_events",
            "tasks",
            "timeline_events_v6",
            "timelines_v3",
            "workflow_graph_events",
            "workflow_graphs",
            "workflow_run_events_v3",
            "workflow_runs",
            "workflow_runs_v3",
            "workflow_templates_v3",
        ):
            connection.execute(f'CREATE TABLE "{table_name}" (id TEXT PRIMARY KEY)')
        connection.executescript(
            """
            ALTER TABLE provider_profiles ADD COLUMN provider_type TEXT;
            ALTER TABLE provider_profiles ADD COLUMN display_name TEXT;
            ALTER TABLE provider_profiles ADD COLUMN enabled INTEGER;
            ALTER TABLE provider_profiles ADD COLUMN last_health_json TEXT;
            ALTER TABLE capability_bindings ADD COLUMN capability TEXT;
            ALTER TABLE capability_bindings ADD COLUMN provider_profile_id TEXT;
            ALTER TABLE capability_bindings ADD COLUMN model TEXT;
            """
        )
        connection.executemany(
            "INSERT INTO provider_profiles(id,provider_type,display_name,enabled,last_health_json) VALUES(?,?,?,?,?)",
            (
                (
                    "opencode-default",
                    "opencode",
                    "OpenCode Agent",
                    1,
                    json.dumps({"ok": True, "models": ["opencode-go/gpt-5.6-luna"]}),
                ),
                (
                    "jimeng-default",
                    "jimeng_cli",
                    "即梦 CLI",
                    1,
                    json.dumps({"ok": True, "models": ["seedance2.0fast"]}),
                ),
            ),
        )
        connection.executemany(
            "INSERT INTO capability_bindings(id,capability,provider_profile_id,model) VALUES(?,?,?,?)",
            (
                ("binding-orchestrator", "orchestrator", "opencode-default", "opencode-go/gpt-5.6-luna"),
                ("binding-video", "video", "jimeng-default", "seedance2.0fast"),
            ),
        )
        now = "2026-08-28T00:00:00+00:00"
        connection.execute("INSERT INTO schema_migrations VALUES(16, ?)", (now,))
        connection.execute(
            "INSERT INTO projects VALUES(?,?,?,?,?,?,?)",
            (
                "TEST_LEGACY_PROJECT",
                "Isolated Legacy Fixture",
                json.dumps(document, ensure_ascii=False),
                1,
                now,
                now,
                "active",
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return path


def isolated_legacy_v3_path(label: str) -> Path:
    """Return a fresh Legacy fixture below the configured test-only root."""

    from uuid import uuid4

    return create_legacy_v3_fixture(TEST_TMP / f"{label}-{uuid4().hex}" / "legacy_v3.db")
