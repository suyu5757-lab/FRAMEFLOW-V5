from __future__ import annotations

import sqlite3
import tempfile
import unittest
from uuid import uuid4
from pathlib import Path

from core.migration.cutover import (
    REQUIRED_LEGACY_SHOTS,
    CutoverBlocked,
    fresh_candidate_from_production,
    perform_production_cutover,
)
from core.migration.legacy_compat import (
    LEGACY_READ_ONLY_COMPAT,
    LegacyReadOnlyCompatibility,
    LegacyReadOnlyError,
    account_legacy_shots,
)
from core.runtime.state_store.factory import (
    RuntimeOwnershipError,
    inspect_database,
    open_runtime_store,
)
from tests.conftest import isolated_legacy_v3_path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
class T03RuntimeOwnershipTests(unittest.TestCase):
    def test_factory_initializes_only_an_explicit_candidate_and_enforces_pragmas(self) -> None:
        path = Path(tempfile.gettempdir()) / "frameflow-t03-factory-candidate.db"
        if path.exists():
            path.unlink()
        with open_runtime_store(path, initialize=True, candidate=True) as store:
            self.assertEqual(
                {"journal_mode": "wal", "foreign_keys": 1, "busy_timeout": 5000},
                store.pragmas(),
            )
            self.assertEqual("V5_RUNTIME", inspect_database(path)["schema"])

    def test_factory_rejects_a_legacy_database_before_writable_open(self) -> None:
        path = Path(tempfile.gettempdir()) / "frameflow-t03-legacy-guard.db"
        if path.exists():
            path.unlink()
        connection = sqlite3.connect(path)
        try:
            connection.executescript(
                "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT);"
                "CREATE TABLE projects(id TEXT PRIMARY KEY, name TEXT);"
            )
        finally:
            connection.close()
        self.assertEqual("LEGACY_V3", inspect_database(path)["schema"])
        with self.assertRaises(RuntimeOwnershipError):
            open_runtime_store(path, candidate=True)

    def test_legacy_compatibility_is_read_only(self) -> None:
        adapter = LegacyReadOnlyCompatibility(isolated_legacy_v3_path("ownership-readonly"))
        self.assertIsNotNone(adapter.get_shot("SH004"))
        with self.assertRaises(LegacyReadOnlyError):
            adapter.write_shot("SH004", {"status": "DRAFT"})

    def test_all_required_legacy_shots_are_accounted_before_cutover(self) -> None:
        accounting = account_legacy_shots(isolated_legacy_v3_path("ownership-accounting"), list(REQUIRED_LEGACY_SHOTS))
        self.assertEqual(17, accounting["required"])
        self.assertEqual(17, accounting["accounted"])
        self.assertEqual(0, accounting["unaccounted"])
        self.assertEqual(17, accounting["counts"][LEGACY_READ_ONLY_COMPAT])

    def test_fresh_candidate_is_verified_without_touching_production(self) -> None:
        legacy_source = isolated_legacy_v3_path("ownership-candidate-source")
        before = legacy_source.stat().st_mtime_ns
        root = Path(tempfile.gettempdir()) / f"frameflow-t03-fresh-candidate-{uuid4().hex}"
        result = fresh_candidate_from_production(source=legacy_source, work_dir=root)
        self.assertTrue(Path(result["backup_path"]).is_file())
        self.assertTrue(Path(result["candidate_path"]).is_file())
        self.assertTrue(Path(result["manifest_path"]).is_file())
        self.assertEqual(0, result["legacy_shots"]["unaccounted"])
        self.assertTrue(result["manifest"]["t03_cutover_gate"]["ready"])
        self.assertEqual(before, legacy_source.stat().st_mtime_ns)

    def test_state_store_commit_rollback_close_reopen_smoke(self) -> None:
        path = Path(tempfile.gettempdir()) / f"frameflow-t03-state-smoke-{uuid4().hex}.db"
        with open_runtime_store(path, initialize=True, candidate=True) as store:
            store.create_project("T03_SMOKE", "Smoke", "16:9", 24, 1)
            with self.assertRaisesRegex(RuntimeError, "injected rollback"):
                with store.transaction() as connection:
                    connection.exec_driver_sql(
                        "INSERT INTO projects(id,title,aspect_ratio,fps,target_duration) VALUES(?,?,?,?,?)",
                        ("T03_ROLLBACK", "Rollback", "16:9", 24, 1),
                    )
                    raise RuntimeError("injected rollback")
            self.assertIsNone(store.get_project("T03_ROLLBACK"))
        with open_runtime_store(path, candidate=True) as reopened:
            self.assertEqual("Smoke", reopened.get_project("T03_SMOKE")["title"])
            with reopened.transaction() as connection:
                connection.exec_driver_sql("DELETE FROM projects WHERE id=?", ("T03_SMOKE",))

    def test_production_replacement_is_not_the_default(self) -> None:
        with self.assertRaises(CutoverBlocked):
            perform_production_cutover(
                Path(tempfile.gettempdir()) / "candidate.db",
                legacy_archive=Path(tempfile.gettempdir()) / "archive.db",
            )


if __name__ == "__main__":
    unittest.main()
