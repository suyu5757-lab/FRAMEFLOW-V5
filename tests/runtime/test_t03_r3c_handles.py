from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

from core.migration.cutover import checkpoint_database, handle_free_rename_probe
from core.runtime.persistence import create_runtime_persistence
from core.runtime.state_store.factory import open_runtime_store


TEST_ROOT = Path(r"D:\11067\CodexWorkspaces\frameflow-v3\data\.cutover\r3c-tests")


def _test_candidate(label: str) -> Path:
    root = TEST_ROOT / f"{label}-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    return root / "candidate.db"


def _wait_for_health(port: int, timeout: float = 20.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return json.loads(response.read())
        except Exception as exc:  # startup race is expected
            last_error = exc
        time.sleep(0.2)
    raise AssertionError(f"V5 backend did not become healthy: {last_error}")


def _init_candidate(path: Path) -> None:
    with open_runtime_store(path, initialize=True, candidate=True):
        pass


def _stop_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is None:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    if proc.stdout is not None:
        proc.stdout.close()
    if proc.stderr is not None:
        proc.stderr.close()


def test_h1_statestore_dispose_then_real_rename_probe() -> None:
    candidate = _test_candidate("h1")
    _init_candidate(candidate)
    result = handle_free_rename_probe(candidate)
    assert result["passed"] is True
    assert candidate.is_file()


def test_h1b_checkpoint_helper_closes_sqlite_connection() -> None:
    candidate = _test_candidate("h1b")
    _init_candidate(candidate)
    result = checkpoint_database(candidate)
    assert result["integrity_check"] == "ok"
    assert handle_free_rename_probe(candidate)["passed"] is True


def test_h2_v5_backend_wait_exit_then_real_rename_probe(free_tcp_port: int) -> None:
    candidate = _test_candidate("h2")
    _init_candidate(candidate)
    environment = os.environ.copy()
    environment.update(
        {
            "FRAMEFLOW_RUNTIME_MODE": "v5",
            "FRAMEFLOW_V5_DB": str(candidate),
            "FRAMEFLOW_V5_PRODUCTION": "0",
        }
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(free_tcp_port), "--log-level", "warning"],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        health = _wait_for_health(free_tcp_port)
        assert health["runtime_mode"] == "v5"
    finally:
        _stop_process(proc)
    assert proc.poll() is not None
    result = handle_free_rename_probe(candidate)
    assert result["passed"] is True


def test_h3_runtime_persistence_dispose_then_real_rename_probe() -> None:
    candidate = _test_candidate("h3")
    _init_candidate(candidate)
    persistence = create_runtime_persistence(
        environment={
            "FRAMEFLOW_RUNTIME_MODE": "v5",
            "FRAMEFLOW_V5_DB": str(candidate),
            "FRAMEFLOW_V5_PRODUCTION": "0",
        }
    )
    persistence.dispose()
    result = handle_free_rename_probe(candidate)
    assert result["passed"] is True


def test_h4_smoke_and_swap_candidates_are_distinct() -> None:
    smoke = TEST_ROOT / "smoke_candidate.db"
    swap = TEST_ROOT / "swap_candidate.db"
    assert smoke != swap
    assert smoke.name != swap.name
