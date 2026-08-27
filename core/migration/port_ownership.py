"""Fail-closed Windows port ownership evidence for T03 production maintenance."""

from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_DATABASE = PROJECT_ROOT / "data" / "frameflow.db"
FORMAL_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
PORT = 8787
MAINTENANCE_TASKS = ("FRAMEFLOW Runtime Startup", "FRAMEFLOW-V3-Service")
PAUSED_TASK_STATES = {
    "FRAMEFLOW Runtime Startup": {"Disabled", "PausedByToken"},
    "FRAMEFLOW-V3-Service": {"Disabled", "OnDemandNoTriggers"},
}

FREE = "FREE"
FRAMEFLOW_EXPECTED = "FRAMEFLOW_EXPECTED"
FRAMEFLOW_STALE = "FRAMEFLOW_STALE"
FRAMEFLOW_SUPERVISED = "FRAMEFLOW_SUPERVISED"
FOREIGN_PROCESS = "FOREIGN_PROCESS"
UNKNOWN = "UNKNOWN"


class PortOwnershipError(RuntimeError):
    """Raised when exclusive production-port ownership cannot be proven."""


def parse_netstat_listeners(output: str, port: int = PORT) -> list[dict[str, Any]]:
    """Parse Windows netstat output without relying on privileged TCP cmdlets."""

    listeners: list[dict[str, Any]] = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0].upper() != "TCP":
            continue
        local, state, pid_text = fields[1], fields[3].upper(), fields[4]
        if state != "LISTENING" or not pid_text.isdigit():
            continue
        match = re.match(r"^(.*):(\d+)$", local)
        if match is None or int(match.group(2)) != port:
            continue
        listeners.append(
            {
                "local_address": match.group(1).strip("[]"),
                "local_port": port,
                "state": state,
                "pid": int(pid_text),
            }
        )
    return listeners


def _netstat(port: int) -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["netstat.exe", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise PortOwnershipError(f"netstat failed: {completed.stderr.strip()}")
    return parse_netstat_listeners(completed.stdout, port)


def _powershell_json(script: str) -> Any:
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return None
    rendered = completed.stdout.strip()
    return json.loads(rendered) if rendered else None


def inspect_process(pid: int) -> dict[str, Any]:
    script = (
        f"$p=Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\" "
        "-ErrorAction SilentlyContinue; if($p){$p | Select-Object "
        "ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine,CreationDate,SessionId "
        "| ConvertTo-Json -Compress}"
    )
    value = _powershell_json(script)
    return dict(value) if isinstance(value, Mapping) else {"ProcessId": pid}


def inspect_doctor(port: int, timeout: float = 2.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/system/doctor", timeout=timeout
        ) as response:
            value = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return value if isinstance(value, dict) else None


def doctor_matches_frameflow(
    doctor: Mapping[str, Any] | None,
    *,
    project_root: Path = PROJECT_ROOT,
    canonical_database: Path = CANONICAL_DATABASE,
) -> bool:
    if not isinstance(doctor, Mapping):
        return False
    frontend = Path(str(doctor.get("frontend_dist") or "")).resolve(strict=False)
    database = Path(str(doctor.get("database") or "")).resolve(strict=False)
    expected_frontend = (project_root / "web" / "dist").resolve(strict=False)
    return frontend == expected_frontend and database == canonical_database.resolve(strict=False)


def classify_port_owner(snapshot: Mapping[str, Any]) -> str:
    listeners = snapshot.get("listeners")
    if not isinstance(listeners, Sequence) or not listeners:
        return FREE
    if len(listeners) != 1:
        return UNKNOWN
    process = snapshot.get("process")
    process = process if isinstance(process, Mapping) else {}
    name = str(process.get("Name") or process.get("name") or "").lower()
    executable = str(process.get("ExecutablePath") or "").lower()
    command = str(process.get("CommandLine") or "").lower()
    doctor_match = snapshot.get("doctor_matches_frameflow") is True
    task_sources = snapshot.get("task_sources")
    supervised = isinstance(task_sources, Sequence) and bool(task_sources)
    root_text = str(PROJECT_ROOT).lower()
    if doctor_match and supervised and name in {"", "python.exe"}:
        return FRAMEFLOW_SUPERVISED
    if doctor_match and name == "python.exe":
        return FRAMEFLOW_EXPECTED
    if root_text in executable or root_text in command:
        return FRAMEFLOW_STALE
    if executable or command:
        return FOREIGN_PROCESS
    return UNKNOWN


def inspect_port_owner(
    port: int = PORT,
    *,
    netstat_probe: Callable[[int], list[dict[str, Any]]] = _netstat,
    process_probe: Callable[[int], dict[str, Any]] = inspect_process,
    doctor_probe: Callable[[int], dict[str, Any] | None] = inspect_doctor,
    task_sources: Sequence[str] = (),
) -> dict[str, Any]:
    listeners = netstat_probe(port)
    snapshot: dict[str, Any] = {
        "port": port,
        "listeners": listeners,
        "owner_pid": None,
        "process": None,
        "parent": None,
        "doctor": None,
        "doctor_matches_frameflow": False,
        "task_sources": list(task_sources),
    }
    if len(listeners) == 1:
        pid = int(listeners[0]["pid"])
        process = process_probe(pid)
        parent_pid = int(process.get("ParentProcessId") or 0)
        doctor = doctor_probe(port)
        snapshot.update(
            {
                "owner_pid": pid,
                "process": process,
                "parent": process_probe(parent_pid) if parent_pid else None,
                "doctor": doctor,
                "doctor_matches_frameflow": doctor_matches_frameflow(doctor),
            }
        )
    snapshot["classification"] = classify_port_owner(snapshot)
    return snapshot


def build_exclusive_port_evidence(
    observations: Sequence[Mapping[str, Any]],
    *,
    maintenance_tasks: Mapping[str, str],
) -> dict[str, Any]:
    """Validate repeated FREE observations while all respawn sources are paused."""

    errors: list[str] = []
    samples = [dict(value) for value in observations]
    if len(samples) < 3:
        errors.append("at least three live port observations are required")
    classifications = [str(value.get("classification") or UNKNOWN) for value in samples]
    pids = [value.get("owner_pid") for value in samples]
    if any(value != FREE for value in classifications):
        errors.append("port 8787 is not exclusively FREE")
    non_null_pids = [int(value) for value in pids if value is not None]
    if len(set(non_null_pids)) > 1:
        errors.append("port owner PID changed during the gate")
    task_state = {str(name): str(state) for name, state in maintenance_tasks.items()}
    for task_name in MAINTENANCE_TASKS:
        if task_state.get(task_name) not in PAUSED_TASK_STATES[task_name]:
            errors.append(f"maintenance task is not paused: {task_name}")
    return {
        "passed": not errors,
        "errors": errors,
        "port": PORT,
        "observations": samples,
        "owner_pids": pids,
        "maintenance_tasks": task_state,
        "maintenance_paused": not any(
            task_state.get(name) not in PAUSED_TASK_STATES[name]
            for name in MAINTENANCE_TASKS
        ),
    }


def assert_exclusive_port_evidence(evidence: Mapping[str, Any] | None) -> None:
    if not isinstance(evidence, Mapping) or evidence.get("passed") is not True:
        errors = evidence.get("errors") if isinstance(evidence, Mapping) else None
        raise PortOwnershipError(f"exclusive port evidence failed: {errors}")
    samples = evidence.get("observations")
    if not isinstance(samples, Sequence) or len(samples) < 3:
        raise PortOwnershipError("exclusive port evidence has insufficient samples")
    if any(value.get("classification") != FREE for value in samples if isinstance(value, Mapping)):
        raise PortOwnershipError("exclusive port evidence is not FREE")
    if evidence.get("maintenance_paused") is not True:
        raise PortOwnershipError("FRAMEFLOW respawn sources are not maintenance-paused")


def assert_live_port_free(snapshot: Mapping[str, Any]) -> None:
    if snapshot.get("classification") != FREE or snapshot.get("owner_pid") is not None:
        raise PortOwnershipError(
            f"live production port is occupied: classification={snapshot.get('classification')} "
            f"pid={snapshot.get('owner_pid')}"
        )


def verify_lifecycle_restoration(
    original_tasks: Mapping[str, Mapping[str, Any]],
    restored_tasks: Mapping[str, Mapping[str, Any]],
    *,
    runtime_was_listening: bool,
    restored_owner_pid: int | None,
) -> dict[str, Any]:
    errors: list[str] = []
    for task_name in MAINTENANCE_TASKS:
        original = original_tasks.get(task_name)
        restored = restored_tasks.get(task_name)
        if not isinstance(original, Mapping) or not isinstance(restored, Mapping):
            errors.append(f"task lifecycle evidence missing: {task_name}")
            continue
        if bool(original.get("Enabled")) != bool(restored.get("Enabled")):
            errors.append(f"task enabled state was not restored: {task_name}")
    if runtime_was_listening and restored_owner_pid is None:
        errors.append("runtime listener was not restored")
    return {"passed": not errors, "errors": errors}


__all__ = [
    "FOREIGN_PROCESS",
    "FRAMEFLOW_EXPECTED",
    "FRAMEFLOW_STALE",
    "FRAMEFLOW_SUPERVISED",
    "FREE",
    "MAINTENANCE_TASKS",
    "PORT",
    "PortOwnershipError",
    "UNKNOWN",
    "assert_exclusive_port_evidence",
    "assert_live_port_free",
    "build_exclusive_port_evidence",
    "classify_port_owner",
    "doctor_matches_frameflow",
    "inspect_port_owner",
    "parse_netstat_listeners",
    "verify_lifecycle_restoration",
]
