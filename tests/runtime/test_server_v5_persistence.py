from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from core.migration.cutover import fresh_candidate_from_production
from core.migration.legacy_compat import LegacyReadOnlyCompatibility
from core.runtime.persistence import RuntimeModeError, create_runtime_persistence
from core.runtime.state_store.factory import inspect_database, open_runtime_store
from tests.conftest import isolated_legacy_v3_path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class V5ServerPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.legacy_source = isolated_legacy_v3_path("server-v5-source")
        cls.production_sha = sha256(cls.legacy_source)
        cls.root = Path(tempfile.gettempdir()) / f"frameflow-t03r2-server-{uuid4().hex}"
        result = fresh_candidate_from_production(
            source=cls.legacy_source,
            work_dir=cls.root,
            run_id=f"t03r2-{uuid4().hex[:8]}",
        )
        cls.candidate = Path(result["candidate_path"])
        cls.legacy = Path(result["backup_path"])

    def _run_server_probe(self) -> dict[str, object]:
        script = r'''
import json
from fastapi.testclient import TestClient
import server

with TestClient(server.app) as client:
    health = client.get('/api/health')
    projects = client.get('/api/v2/projects')
    project_id = projects.json()['projects'][0]['document']['id']
    paths = {
        'project': f'/api/v2/projects/{project_id}',
        'dashboard': f'/api/v2/dashboard?project_id={project_id}',
        'graph': f'/api/v2/projects/{project_id}/graph',
        'timeline': f'/api/v2/projects/{project_id}/timeline',
        'preflight': f'/api/v2/projects/{project_id}/timeline/preflight',
        'story': f'/api/v2/projects/{project_id}/story',
        'story_runs': f'/api/v2/projects/{project_id}/story/runs',
        'assets': f'/api/v2/projects/{project_id}/assets',
        'asset_board': f'/api/v2/projects/{project_id}/asset-board',
        'asset_audit': f'/api/v2/projects/{project_id}/asset-audit',
        'audio': f'/api/v2/projects/{project_id}/audio-studio',
        'settings': '/api/v2/settings',
        'audit': '/api/v2/system/data-audit',
        'runtime_contract': '/api/v2/system/runtime-contract',
        'workflows': '/api/v2/workflows',
        'legacy_api': '/api/projects',
        'unsupported': '/api/v2/projects/' + project_id + '/graph/write',
    }
    responses = {key: client.get(path).status_code for key, path in paths.items() if key not in {'legacy_api', 'unsupported'}}
    responses['legacy_api'] = client.get(paths['legacy_api']).status_code
    responses['unsupported'] = client.get(paths['unsupported']).status_code
    legacy = {shot: client.get('/api/v2/legacy/shots/' + shot) for shot in ('SH004', 'SH010', 'SH020')}
    payload = {
        'health': health.json(),
        'projects': projects.json(),
        'project': client.get(paths['project']).json(),
        'assets': client.get(paths['assets']).json(),
        'runtime_contract': client.get(paths['runtime_contract']).json(),
        'responses': responses,
        'legacy': {shot: {'status': response.status_code, 'read_only': response.json().get('read_only')} for shot, response in legacy.items()},
    }
    created = client.post('/api/v2/projects', json={'name': 'T03R2_FIXTURE_CREATE', 'brief': 'runtime test', 'ratio': '16:9', 'duration': 1, 'generator': 'manual'})
    payload['created'] = {'status': created.status_code, 'body': created.json()}
    fixture_id = created.json()['document']['id']
    revision = created.json()['revision']
    updated = client.patch('/api/v2/projects/' + fixture_id, json={'expected_revision': revision, 'name': 'T03R2_FIXTURE_UPDATED'})
    payload['updated'] = {'status': updated.status_code, 'body': updated.json()}
    payload['invalid_create'] = client.post('/api/v2/projects', json={'name': 42}).status_code
    payload['missing_project'] = client.get('/api/v2/projects/does-not-exist').status_code
with TestClient(server.app) as restarted:
    persisted = restarted.get('/api/v2/projects/' + fixture_id)
    payload['restart'] = {'status': persisted.status_code, 'name': persisted.json().get('document', {}).get('name')}
print(json.dumps(payload, ensure_ascii=False))
'''
        env = os.environ.copy()
        env.update(
            {
                "FRAMEFLOW_RUNTIME_MODE": "v5",
                "FRAMEFLOW_V5_DB": str(self.candidate),
                "FRAMEFLOW_LEGACY_READONLY_DB": str(self.legacy),
                "FRAMEFLOW_BIND_HOST": "127.0.0.1",
            }
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            self.fail(f"V5 server probe failed:\nSTDOUT={completed.stdout}\nSTDERR={completed.stderr}")
        return json.loads(completed.stdout)

    def test_v5_backend_p0_routes_and_legacy_bridge(self) -> None:
        payload = self._run_server_probe()
        self.assertEqual("v5", payload["health"]["runtime_mode"])
        self.assertTrue(all(status == 200 for key, status in payload["responses"].items() if key not in {"legacy_api", "unsupported"}), payload["responses"])
        self.assertEqual(410, payload["responses"]["legacy_api"])
        self.assertEqual(501, payload["responses"]["unsupported"])
        self.assertEqual(
            {"database": str(self.candidate), "journal_mode": "wal", "foreign_keys": 1, "busy_timeout": 5000},
            payload["runtime_contract"],
        )
        self.assertEqual(422, payload["invalid_create"])
        self.assertEqual(404, payload["missing_project"])
        self.assertEqual({"SH004": {"status": 200, "read_only": True}, "SH010": {"status": 200, "read_only": True}, "SH020": {"status": 200, "read_only": True}}, payload["legacy"])
        candidate = inspect_database(self.candidate)
        self.assertEqual("V5_RUNTIME", candidate["schema"])
        self.assertEqual(11, len(candidate["domain_tables"]))
        self.assertNotIn("schema_migrations", candidate["tables"])
        with open_runtime_store(self.candidate, candidate=True) as store:
            self.assertEqual(1, store.pragmas()["foreign_keys"])

    def test_v5_project_metadata_write_reopens_and_production_is_unchanged(self) -> None:
        payload = self._run_server_probe()
        self.assertEqual(201, payload["created"]["status"])
        self.assertEqual(200, payload["updated"]["status"])
        self.assertEqual(2, payload["updated"]["body"]["revision"])
        self.assertEqual({"status": 200, "name": "T03R2_FIXTURE_UPDATED"}, payload["restart"])
        self.assertEqual(self.production_sha, sha256(self.legacy_source))

    def test_legacy_select_and_all_sql_writes_are_blocked(self) -> None:
        adapter = LegacyReadOnlyCompatibility(self.legacy)
        with adapter.connection() as connection:
            self.assertIsNotNone(connection.execute("SELECT id FROM projects LIMIT 1").fetchone())
            for statement in (
                "INSERT INTO projects(id,name,document_json,revision,created_at,updated_at,lifecycle_status) VALUES('T03R2_BAD','bad','{}',1,'x','x','active')",
                "UPDATE projects SET name='bad'",
                "DELETE FROM projects",
            ):
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute(statement)

    def test_facade_transaction_rolls_back_a_failed_project_update(self) -> None:
        path = Path(tempfile.gettempdir()) / f"frameflow-t03r2-rollback-{uuid4().hex}.db"
        with open_runtime_store(path, initialize=True, candidate=True) as store:
            from core.runtime.persistence import RuntimePersistence

            persistence = RuntimePersistence(store)
            persistence.create_project(project_id="T03R2_ROLLBACK", name="before", ratio="16:9", duration=1, generator="manual", brief="")
            original = store._write_event

            def fail_event(*args, **kwargs):
                raise RuntimeError("injected persistence failure")

            store._write_event = fail_event
            try:
                with self.assertRaisesRegex(RuntimeError, "injected persistence failure"):
                    persistence.update_project_metadata("T03R2_ROLLBACK", expected_revision=1, changes={"name": "after"})
            finally:
                store._write_event = original
            self.assertEqual("before", persistence.project_envelope("T03R2_ROLLBACK")["document"]["name"])

    def test_default_legacy_mode_still_starts_in_an_isolated_database(self) -> None:
        database = Path(tempfile.gettempdir()) / f"frameflow-t03r2-legacy-{uuid4().hex}.db"
        script = r'''
from fastapi.testclient import TestClient
import server
with TestClient(server.app) as client:
    response = client.get('/api/health')
    print(response.status_code)
'''
        env = os.environ.copy()
        env.update({"FRAMEFLOW_RUNTIME_MODE": "legacy", "FRAMEFLOW_DB_PATH": str(database), "FRAMEFLOW_BIND_HOST": "127.0.0.1"})
        env.pop("FRAMEFLOW_V5_DB", None)
        env.pop("FRAMEFLOW_LEGACY_READONLY_DB", None)
        completed = subprocess.run([sys.executable, "-c", script], cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("200", completed.stdout.strip())

    def test_v5_mode_requires_an_explicit_non_production_candidate(self) -> None:
        with self.assertRaises(RuntimeModeError):
            create_runtime_persistence(environment={"FRAMEFLOW_RUNTIME_MODE": "v5"})
        with self.assertRaises(RuntimeModeError):
            create_runtime_persistence(environment={"FRAMEFLOW_RUNTIME_MODE": "v5", "FRAMEFLOW_V5_DB": str(self.legacy_source)})


if __name__ == "__main__":
    unittest.main()
