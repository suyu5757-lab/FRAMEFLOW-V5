"""Reproducible isolated T03 SOL startup/restart and compatibility gate.

This harness never accepts the canonical production database as its writable
candidate.  It writes one persisted runtime config, starts the same Uvicorn
entrypoint twice, and reuses that config without runtime ownership variables.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import delete

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.migration.legacy_compat import LegacyReadOnlyCompatibility
from core.migration.production_environment import (
    FORMAL_LAUNCHER_EVIDENCE_VERSION,
    FORMAL_PYTHON,
    verify_production_interpreter,
)
from core.migration.cutover import checkpoint_database
from core.migration.equivalence import logical_data_fingerprint, schema_fingerprint
from core.migration.port_ownership import parse_netstat_listeners
from core.schemas.runtime_mvp import metadata
from core.runtime.persistence import RuntimeStartupConfig, write_runtime_startup_config
from core.runtime.state_store import StateStore
from core.runtime.state_store.factory import CANONICAL_DATABASE_PATH, inspect_database


REQUIRED_LEGACY_SHOTS = tuple(f"SH{number:03d}" for number in range(4, 21))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request_json(
    port: int,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8"))
        return exc.code, payload


def wait_for_v5(port: int, process: subprocess.Popen[str], timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise RuntimeError(
                f"backend exited during startup ({process.returncode})\nSTDOUT={stdout}\nSTDERR={stderr}"
            )
        try:
            status, payload = request_json(port, "GET", "/api/health")
            if (
                status == 200
                and payload.get("runtime_mode") == "v5"
                and payload.get("ready") is True
            ):
                return payload
            if status == 200 and payload.get("runtime_mode") == "v5":
                last_error = RuntimeError(
                    "V5 readiness gate is false: "
                    f"status={payload.get('status')} "
                    f"failing_predicates={(payload.get('readiness') or {}).get('failing_predicates')}"
                )
        except Exception as exc:
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"V5 backend did not start on port {port}: {last_error}")


def stop_backend(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    if process.stdout is not None:
        process.stdout.close()
    if process.stderr is not None:
        process.stderr.close()


def listener_pids(port: int) -> list[int]:
    output = subprocess.run(
        ["netstat.exe", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    ).stdout
    return [int(item["pid"]) for item in parse_netstat_listeners(output, port)]


def wait_for_port_free(port: int, timeout: float = 15.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    observations: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        pids = listener_pids(port)
        observations.append(
            {
                "utc": datetime.now(UTC).isoformat(),
                "listener_pids": pids,
                "free": not pids,
            }
        )
        if not pids:
            return {"port": port, "free": True, "observations": observations}
        time.sleep(0.2)
    raise RuntimeError(f"isolated runtime port did not become free: port={port} observations={observations}")


def _candidate_file_state(path: Path) -> dict[str, Any]:
    def one(target: Path) -> dict[str, Any]:
        if not target.exists():
            return {"exists": False, "size": None, "sha256": None}
        return {
            "exists": True,
            "size": target.stat().st_size,
            "sha256": sha256(target),
            "mtime_ns": target.stat().st_mtime_ns,
        }

    return {
        "main": one(path),
        "wal": one(Path(f"{path}-wal")),
        "shm": one(Path(f"{path}-shm")),
    }


def stabilize_candidate_after_probe(candidate: Path, port: int) -> dict[str, Any]:
    """Close the SQLite lifecycle before binding physical evidence.

    Candidate A is allowed to run and write its isolated smoke fixture.  The
    physical file is therefore not authoritative until the backend is gone,
    the port is free, the fixture cleanup connection is closed, and SQLite has
    checkpointed the WAL.  This function makes that boundary explicit and
    records the stable state used by the formal evidence gate.
    """

    port_free = wait_for_port_free(port)
    checkpoint = checkpoint_database(candidate)
    checkpoint_rows = checkpoint.get("checkpoint") or []
    if any(int(row[0]) != 0 for row in checkpoint_rows if row):
        raise RuntimeError(f"candidate WAL checkpoint was busy: {checkpoint}")
    stable_samples: list[dict[str, Any]] = []
    for index in range(4):
        state = _candidate_file_state(candidate)
        state["sample"] = index
        state["utc"] = datetime.now(UTC).isoformat()
        stable_samples.append(state)
        if index < 3:
            time.sleep(0.25)
    def stability_key(sample: Mapping[str, Any]) -> dict[str, Any]:
        return {name: sample.get(name) for name in ("main", "wal", "shm")}

    if any(
        stability_key(sample) != stability_key(stable_samples[0])
        for sample in stable_samples[1:]
    ):
        raise RuntimeError(f"candidate physical state did not stabilize: {stable_samples}")
    final_state = stable_samples[-1]
    if final_state["wal"]["exists"] or final_state["shm"]["exists"]:
        raise RuntimeError(f"candidate sidecars remain after final checkpoint: {final_state}")
    info = inspect_database(candidate)
    logical = logical_data_fingerprint(candidate)
    schema = schema_fingerprint(candidate)
    post_inspect = _candidate_file_state(candidate)
    if stability_key(post_inspect) != stability_key(final_state):
        raise RuntimeError(
            "candidate changed while final evidence was being inspected: "
            f"before={final_state} after={post_inspect}"
        )
    return {
        "backend_stopped": True,
        "port_free": port_free,
        "checkpoint": checkpoint,
        "stable_samples": stable_samples,
        "final_file_state": final_state,
        "candidate_info": info,
        "schema_fingerprint": schema,
        "logical_fingerprint": logical,
        "final_candidate_sha256": final_state["main"]["sha256"],
    }


def runtime_sqlite_gates(candidate: Path) -> dict[str, Any]:
    """Capture SQLite gates from the same StateStore connection contract."""

    with StateStore(candidate, initialize=False) as store:
        with store.connection() as connection:
            journal_mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar()
            foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
            busy_timeout = connection.exec_driver_sql("PRAGMA busy_timeout").scalar()
            integrity = connection.exec_driver_sql("PRAGMA integrity_check").scalar()
            foreign_key_violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    return {
        "journal_mode": str(journal_mode).lower(),
        "foreign_keys": int(foreign_keys),
        "busy_timeout": int(busy_timeout),
        "integrity_check": str(integrity),
        "foreign_key_violations": [tuple(row) for row in foreign_key_violations],
    }


def run_http_gate(port: int, persisted_fixture: str | None = None) -> dict[str, Any]:
    health_status, health = request_json(port, "GET", "/api/health")
    if (
        health_status != 200
        or health.get("runtime_mode") != "v5"
        or health.get("ready") is not True
    ):
        raise AssertionError(f"health gate failed: status={health_status} payload={health}")
    status, projects = request_json(port, "GET", "/api/v2/projects")
    if status != 200 or not projects.get("projects"):
        raise AssertionError(f"project list gate failed: status={status} payload={projects}")
    project_id = str(projects["projects"][0]["document"]["id"])

    checks: list[tuple[str, int, int]] = [("health", health_status, 200)]
    requests = (
        ("doctor", "GET", "/api/system/doctor", None, 200),
        ("projects", "GET", "/api/v2/projects", None, 200),
        ("dashboard", "GET", f"/api/v2/dashboard?project_id={project_id}", None, 200),
        ("settings", "GET", "/api/v2/settings", None, 200),
        ("workflows", "GET", "/api/v2/workflows", None, 200),
        ("data_audit", "GET", "/api/v2/system/data-audit", None, 200),
        ("project", "GET", f"/api/v2/projects/{project_id}", None, 200),
        ("graph", "GET", f"/api/v2/projects/{project_id}/graph", None, 200),
        ("timeline", "GET", f"/api/v2/projects/{project_id}/timeline", None, 200),
        ("timeline_preflight", "GET", f"/api/v2/projects/{project_id}/timeline/preflight", None, 200),
        ("story", "GET", f"/api/v2/projects/{project_id}/story", None, 200),
        ("story_runs", "GET", f"/api/v2/projects/{project_id}/story/runs", None, 200),
        ("assets", "GET", f"/api/v2/projects/{project_id}/assets", None, 200),
        ("asset_board", "GET", f"/api/v2/projects/{project_id}/asset-board", None, 200),
        ("asset_audit", "GET", f"/api/v2/projects/{project_id}/asset-audit", None, 200),
        ("audio_studio", "GET", f"/api/v2/projects/{project_id}/audio-studio", None, 200),
    )
    for name, method, path, body, expected in requests:
        actual, _payload = request_json(port, method, path, body)
        checks.append((name, actual, expected))

    doctor_status, doctor = request_json(port, "GET", "/api/system/doctor")

    fixture_name = f"T03R3_SMOKE_SOL_{uuid4().hex[:8].upper()}"
    created_status, created = request_json(
        port,
        "POST",
        "/api/v2/projects",
        {
            "name": fixture_name,
            "brief": "isolated restart verification",
            "ratio": "16:9",
            "duration": 1,
            "generator": "manual",
        },
    )
    checks.append(("create_project", created_status, 201))
    fixture_id = str(created.get("document", {}).get("id") or "")
    revision = created.get("revision")
    updated_status, updated = request_json(
        port,
        "PATCH",
        f"/api/v2/projects/{fixture_id}",
        {"expected_revision": revision, "name": f"{fixture_name}_UPDATED"},
    )
    checks.append(("update_project", updated_status, 200))

    if persisted_fixture:
        persisted_status, persisted = request_json(
            port, "GET", f"/api/v2/projects/{persisted_fixture}"
        )
        if persisted_status != 200 or not str(
            persisted.get("document", {}).get("name", "")
        ).endswith("_UPDATED"):
            raise AssertionError(
                f"restart persistence failed for {persisted_fixture}: {persisted_status} {persisted}"
            )

    failures = [name for name, actual, expected in checks if actual != expected]
    if len(checks) != 19 or failures:
        raise AssertionError(f"19-API gate failed: count={len(checks)} failures={failures}")

    historical: dict[str, int] = {}
    for shot_id in REQUIRED_LEGACY_SHOTS:
        shot_status, payload = request_json(
            port, "GET", f"/api/v2/legacy/shots/{shot_id}"
        )
        historical[shot_id] = shot_status
        if shot_status != 200 or payload.get("read_only") is not True:
            raise AssertionError(
                f"historical compatibility failed for {shot_id}: {shot_status} {payload}"
            )

    retired_status, _ = request_json(port, "GET", "/api/projects")
    unsupported_status, _ = request_json(
        port, "GET", f"/api/v2/projects/{project_id}/graph/write"
    )
    if retired_status != 410 or unsupported_status != 501:
        raise AssertionError(
            f"V5 gateway boundary failed: retired={retired_status} unsupported={unsupported_status}"
        )
    return {
        "api": {name: actual for name, actual, _expected in checks},
        "api_passed": len(checks),
        "api_failed": len(failures),
        "historical": historical,
        "historical_passed": sum(1 for value in historical.values() if value == 200),
        "historical_failed": sum(1 for value in historical.values() if value != 200),
        "fixture_id": fixture_id,
        "persisted_fixture": persisted_fixture,
        "gateway": {"retired_v3": retired_status, "unsupported_v5_write": unsupported_status},
        "doctor": doctor,
        "doctor_status": doctor_status,
    }


def verify_read_only(legacy: Path) -> dict[str, Any]:
    before = sha256(legacy)
    adapter = LegacyReadOnlyCompatibility(legacy)
    blocked: dict[str, bool] = {}
    with adapter.connection() as connection:
        selected = connection.execute("SELECT id FROM projects LIMIT 1").fetchone() is not None
        for verb, statement in {
            "insert": "INSERT INTO projects(id) VALUES('T03_SOL_FORBIDDEN')",
            "update": "UPDATE projects SET id=id",
            "delete": "DELETE FROM projects",
        }.items():
            try:
                connection.execute(statement)
            except sqlite3.OperationalError:
                blocked[verb] = True
            else:
                blocked[verb] = False
    after = sha256(legacy)
    if not selected or not all(blocked.values()) or before != after:
        raise AssertionError(
            f"legacy read-only gate failed: selected={selected} blocked={blocked} hash_stable={before == after}"
        )
    return {
        "select": "PASS",
        "insert": "BLOCKED",
        "update": "BLOCKED",
        "delete": "BLOCKED",
        "sha256_before": before,
        "sha256_after": after,
        "validation": adapter.validation,
    }


def cleanup_probe_fixtures(candidate: Path, fixture_ids: list[str]) -> dict[str, Any]:
    """Remove only IDs created by this isolated formal-launcher probe."""

    allowed_prefixes = ("T03R2_", "T03R3_SMOKE_SOL_")
    if not fixture_ids or any(not item.startswith(allowed_prefixes) for item in fixture_ids):
        raise AssertionError(f"refusing unsafe probe cleanup IDs: {fixture_ids}")
    last_error: Exception | None = None
    for _attempt in range(20):
        try:
            with StateStore(candidate, initialize=False) as store:
                with store.transaction() as connection:
                    events = metadata.tables["events"]
                    sequences = metadata.tables["sequences"]
                    projects = metadata.tables["projects"]
                    entity_ids = [*fixture_ids, *(f"{item}:SQ001" for item in fixture_ids)]
                    connection.execute(delete(events).where(events.c.entity_id.in_(entity_ids)))
                    connection.execute(delete(sequences).where(sequences.c.project_id.in_(fixture_ids)))
                    connection.execute(delete(projects).where(projects.c.id.in_(fixture_ids)))
                remaining = [item for item in fixture_ids if store.get_project(item) is not None]
            break
        except Exception as exc:
            last_error = exc
            time.sleep(0.25)
    else:
        raise RuntimeError(f"formal launcher probe cleanup could not reopen candidate: {last_error}") from last_error
    if remaining:
        raise AssertionError(f"formal launcher probe fixture cleanup failed: {remaining}")
    return {"removed": fixture_ids, "remaining": remaining, "passed": True}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--production-like",
        action="store_true",
        help="use production=true semantics against an explicitly isolated simulation database",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if Path(sys.executable).resolve() != FORMAL_PYTHON.resolve():
        raise SystemExit(
            f"formal launcher probe requires {FORMAL_PYTHON}; actual={sys.executable}"
        )
    interpreter_gate = verify_production_interpreter()
    candidate = args.candidate.expanduser().resolve(strict=False)
    legacy = args.legacy.expanduser().resolve(strict=False)
    config_path = args.config.expanduser().resolve(strict=False)
    if candidate == CANONICAL_DATABASE_PATH:
        raise SystemExit("refusing to verify against the canonical production database")
    if candidate == legacy:
        raise SystemExit("candidate and legacy archive must be different files")
    candidate_info = inspect_database(candidate)
    if candidate_info["schema"] != "V5_RUNTIME":
        raise SystemExit(f"candidate is not V5_RUNTIME: {candidate_info['schema']}")
    candidate_pre_probe_logical = logical_data_fingerprint(candidate)
    candidate_pre_probe_schema = schema_fingerprint(candidate)

    config = RuntimeStartupConfig.build(
        runtime_mode="v5",
        runtime_db=candidate,
        legacy_readonly_db=legacy,
        production=args.production_like,
        generated_by="scripts.verify_t03_sol_final",
        cutover_run_id=(
            "isolated-production-like-verification"
            if args.production_like
            else "isolated-final-verification"
        ),
    )
    write_runtime_startup_config(config, config_path)
    sqlite_gates = runtime_sqlite_gates(candidate)
    environment = os.environ.copy()
    for name in (
        "FRAMEFLOW_RUNTIME_MODE",
        "FRAMEFLOW_V5_DB",
        "FRAMEFLOW_DB_PATH",
        "FRAMEFLOW_LEGACY_READONLY_DB",
        "FRAMEFLOW_V5_PRODUCTION",
        "FRAMEFLOW_V5_PRODUCTION_SIMULATION",
    ):
        environment.pop(name, None)
    environment["FRAMEFLOW_RUNTIME_CONFIG"] = str(config_path)
    environment["FRAMEFLOW_BIND_HOST"] = "127.0.0.1"
    if args.production_like:
        environment["FRAMEFLOW_V5_PRODUCTION_SIMULATION"] = "1"

    results: list[dict[str, Any]] = []
    persisted_fixture: str | None = None
    for boot in ("first_start", "restart"):
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "server:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
                "--log-level",
                "warning",
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )
        try:
            health = wait_for_v5(args.port, process)
            gate = run_http_gate(args.port, persisted_fixture)
            persisted_fixture = str(gate["fixture_id"])
            results.append({"boot": boot, "health": health, **gate})
        finally:
            stop_backend(process)
            shutdown = wait_for_port_free(args.port)
            if results:
                results[-1]["shutdown"] = shutdown

    fixture_cleanup = cleanup_probe_fixtures(
        candidate, [str(result["fixture_id"]) for result in results]
    )
    final_stabilization = stabilize_candidate_after_probe(candidate, args.port)
    candidate_post_probe = final_stabilization["candidate_info"]
    candidate_sha256_after_probe = final_stabilization["final_candidate_sha256"]

    payload = {
        "formal_launcher_evidence_version": FORMAL_LAUNCHER_EVIDENCE_VERSION,
        "status": "PASS",
        "interpreter_gate": interpreter_gate,
        "formal_launcher_command": [
            str(FORMAL_PYTHON.resolve()),
            "-m",
            "uvicorn",
            "server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
        ],
        "candidate": str(candidate),
        "candidate_info": candidate_info,
        "candidate_pre_probe_logical_fingerprint": candidate_pre_probe_logical,
        "candidate_pre_probe_schema_fingerprint": candidate_pre_probe_schema,
        "runtime_sqlite_gates": sqlite_gates,
        "candidate_post_probe_info": candidate_post_probe,
        "candidate_sha256_after_probe": candidate_sha256_after_probe,
        "final_stabilization": final_stabilization,
        "probe_fixture_cleanup": fixture_cleanup,
        "legacy": str(legacy),
        "runtime_config": str(config_path),
        "runtime_config_payload": json.loads(config_path.read_text(encoding="utf-8")),
        "runtime_environment_fields_injected": [
            "FRAMEFLOW_RUNTIME_CONFIG",
            "FRAMEFLOW_BIND_HOST",
            *( ["FRAMEFLOW_V5_PRODUCTION_SIMULATION"] if args.production_like else [] ),
        ],
        "production_like_simulation": args.production_like,
        "ownership_environment_fields_injected": [],
        "legacy_read_only": verify_read_only(legacy),
        "boots": results,
        "invalid_direct_access": 0,
        "dual_write": False,
        "dual_source_of_truth": False,
        "production_cutover_performed": False,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
