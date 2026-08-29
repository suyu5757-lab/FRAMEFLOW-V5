from __future__ import annotations

import os
from pathlib import Path
from unittest import TestCase, mock
from uuid import uuid4

from fastapi.testclient import TestClient

from core.migration.cutover import fresh_candidate_from_production
from core.runtime.persistence import RuntimePersistence
from tests.conftest import TEST_TMP, isolated_legacy_v3_path
from tests.support.runtime_isolation import (
    REAL_CANONICAL_DB,
    REAL_RUNTIME_CONFIG,
    create_legacy_test_app,
    create_v5_test_app,
    forbid_real_production_network,
)


def _legacy_document(project_id: str = "ISOLATED_V3") -> dict:
    return {
        "id": project_id,
        "name": "isolated Legacy regression",
        "ratio": "16:9",
        "duration": 1,
        "generator": "manual",
        "brief": "runtime isolation",
        "stage": 0,
        "sortOrder": 0,
        "script": "",
        "assets": [],
        "shots": [],
        "audio": {},
        "assetRegulator": {},
        "generations": [],
        "seedancePackages": [],
        "providerOverrides": {},
        "undoStack": [],
        "scriptVersions": [],
        "storyboardVersions": [],
        "storyWorkflowRuns": [],
    }


def _v5_fixture(label: str) -> tuple[Path, Path, Path, Path]:
    root = TEST_TMP / f"runtime-isolation-{label}-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    source = isolated_legacy_v3_path(f"{label}-legacy")
    result = fresh_candidate_from_production(
        source=source,
        work_dir=root / "migration",
        run_id=f"isolation-{label}-{uuid4().hex[:8]}",
    )
    return root, source, Path(result["candidate_path"]), Path(result["backup_path"])


class RuntimeIsolationTests(TestCase):
    def test_ambient_v5_config_cannot_capture_explicit_legacy_fixture(self) -> None:
        root, _source_legacy_db, v5_db, legacy_archive = _v5_fixture("ambient")
        legacy_db = root / f"legacy-app-{uuid4().hex}.db"
        ambient_config = root / "ambient-v5-runtime-startup.json"
        v5 = create_v5_test_app(
            v5_db,
            legacy_archive,
            runtime_config_path=ambient_config,
            production=True,
        )
        legacy = None
        try:
            with mock.patch.dict(
                os.environ,
                {
                    "FRAMEFLOW_RUNTIME_CONFIG": str(ambient_config),
                    "FRAMEFLOW_RUNTIME_MODE": "v5",
                },
                clear=False,
            ), forbid_real_production_network():
                legacy = create_legacy_test_app(legacy_db)
                self.assertNotEqual(legacy.app, v5.app)
                self.assertNotEqual(legacy.module_name, v5.module_name)
                self.assertEqual(legacy.module.RUNTIME_MODE, "legacy")
                self.assertEqual(legacy.module.DB_PATH.resolve(), legacy_db.resolve())
                self.assertNotEqual(legacy.db_path.resolve(), REAL_CANONICAL_DB)
                self.assertNotEqual(legacy.runtime_config_path.resolve(), REAL_RUNTIME_CONFIG)
                self.assertEqual(
                    Path(legacy.module.RUNTIME_ENVIRONMENT["FRAMEFLOW_RUNTIME_CONFIG"]).resolve(),
                    legacy.runtime_config_path.resolve(),
                )
                with TestClient(v5.app) as v5_client:
                    self.assertEqual(v5_client.get("/api/health").json()["runtime_mode"], "v5")
                    v5_persistence = v5.app.state.persistence
                    self.assertIsInstance(v5_persistence, RuntimePersistence)
                    with TestClient(legacy.app) as legacy_client:
                        response = legacy_client.put(
                            "/api/v2/projects/ISOLATED_V3",
                            json={"document": _legacy_document()},
                        )
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual(legacy.app.state.runtime_mode, "legacy")
                        self.assertIsNone(getattr(legacy.app.state, "persistence", None))
        finally:
            if legacy is not None:
                legacy.close()
            v5.close()

    def test_v5_legacy_v5_same_process_keeps_both_route_contracts(self) -> None:
        root, _source_legacy_db, v5_db, legacy_archive = _v5_fixture("sequence")
        legacy_db = root / f"legacy-app-{uuid4().hex}.db"
        first = create_v5_test_app(v5_db, legacy_archive, production=True)
        legacy = create_legacy_test_app(legacy_db)
        second = create_v5_test_app(v5_db, legacy_archive, production=True)
        try:
            with forbid_real_production_network():
                with TestClient(first.app) as first_client:
                    self.assertEqual(
                        first_client.put("/api/v2/projects/ISOLATED_V3/graph", json={}).status_code,
                        501,
                    )
                    first_persistence = first.app.state.persistence
                with TestClient(legacy.app) as legacy_client:
                    response = legacy_client.put(
                        "/api/v2/projects/ISOLATED_V3",
                        json={"document": _legacy_document()},
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(legacy.app.state.runtime_mode, "legacy")
                with TestClient(second.app) as second_client:
                    self.assertEqual(
                        second_client.put("/api/v2/projects/ISOLATED_V3/graph", json={}).status_code,
                        501,
                    )
                    second_persistence = second.app.state.persistence
                self.assertIsInstance(first_persistence, RuntimePersistence)
                self.assertIsInstance(second_persistence, RuntimePersistence)
                self.assertIsNot(first_persistence, second_persistence)
                self.assertIsNot(first.app, second.app)
        finally:
            first.close()
            legacy.close()
            second.close()

    def test_isolated_v5_retired_v3_write_route_remains_501(self) -> None:
        root, _source_legacy_db, v5_db, legacy_archive = _v5_fixture("contract")
        v5 = create_v5_test_app(v5_db, legacy_archive, production=True)
        try:
            with TestClient(v5.app) as client:
                response = client.put("/api/v2/projects/ISOLATED_V3/graph", json={})
                self.assertEqual(response.status_code, 501, response.text)
                self.assertEqual(response.json()["code"], "v5_route_not_implemented")
        finally:
            v5.close()
