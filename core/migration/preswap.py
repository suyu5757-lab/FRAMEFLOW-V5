"""Fail-closed helpers for the final T03 pre-swap gates.

These helpers deliberately operate on explicit paths and evidence.  They do
not perform a production database replacement and do not infer that a path
being configured means that a file exists or is bound to the current run.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from core.runtime.persistence.startup_config import (
    RuntimeStartupConfig,
    RuntimeStartupConfigError,
    write_runtime_startup_config,
)


ARCHIVE_REQUIRED_ARTIFACTS = (
    "legacy_frameflow_v3.db",
    "migration_manifest.json",
    "legacy_fingerprint.json",
    "v5_candidate_fingerprint.json",
    "rollback_instructions.md",
)
READONLY_ATTRIBUTE = 0x1
MAINTENANCE_TASKS = (
    "FRAMEFLOW Runtime Startup",
    "FRAMEFLOW-V3-Service",
)
PAUSED_TASK_STATES = {
    "Disabled",
    "PausedByToken",
    "OnDemandNoTriggers",
}


class PreSwapGateError(RuntimeError):
    """Raised when a pre-swap evidence object cannot be trusted."""


def _resolve(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _readonly(path: Path) -> bool:
    metadata = path.stat()
    attributes = getattr(metadata, "st_file_attributes", None)
    if attributes is not None:
        return bool(int(attributes) & READONLY_ATTRIBUTE)
    return not bool(metadata.st_mode & stat.S_IWUSR)


def _set_readonly(path: Path) -> None:
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_attributes = kernel32.GetFileAttributesW
        get_attributes.argtypes = [ctypes.c_wchar_p]
        get_attributes.restype = ctypes.c_uint32
        set_attributes = kernel32.SetFileAttributesW
        set_attributes.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
        set_attributes.restype = ctypes.c_int
        attributes = int(get_attributes(str(path)))
        if attributes == 0xFFFFFFFF:
            error = ctypes.get_last_error()
            raise OSError(error, f"GetFileAttributesW failed: {path}")
        if not set_attributes(str(path), attributes | READONLY_ATTRIBUTE):
            error = ctypes.get_last_error()
            raise OSError(error, f"SetFileAttributesW failed: {path}")
        return
    path.chmod(path.stat().st_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)


def archive_file_state(path: Path | str) -> dict[str, Any]:
    resolved = _resolve(path)
    if not resolved.is_file():
        return {
            "path": str(resolved),
            "name": resolved.name,
            "exists": False,
            "readonly": False,
        }
    metadata = resolved.stat()
    return {
        "path": str(resolved),
        "name": resolved.name,
        "exists": True,
        "readonly": _readonly(resolved),
        "attributes": getattr(metadata, "st_file_attributes", None),
        "size": metadata.st_size,
        "mtime_ns": metadata.st_mtime_ns,
        "sha256": _sha256(resolved),
    }


def verify_archive_finalization(
    archive_root: Path | str,
    *,
    required_artifacts: Sequence[str] = ARCHIVE_REQUIRED_ARTIFACTS,
) -> dict[str, Any]:
    """Verify the complete five-file permanent archive contract."""

    root = _resolve(archive_root)
    required = tuple(str(name) for name in required_artifacts)
    states = [archive_file_state(root / name) for name in required]
    existing_files = sorted(
        path.name for path in root.iterdir() if path.is_file()
    ) if root.is_dir() else []
    extra_files = sorted(set(existing_files) - set(required))
    errors: list[str] = []
    missing = [state["name"] for state in states if not state["exists"]]
    if missing:
        errors.append("missing archive artifacts: " + ", ".join(missing))
    writable = [state["name"] for state in states if state["exists"] and not state["readonly"]]
    if writable:
        errors.append("writable archive artifacts: " + ", ".join(writable))
    if extra_files:
        errors.append("unexpected archive artifacts: " + ", ".join(extra_files))
    return {
        "archive_root": str(root),
        "required_files": list(required),
        "files": states,
        "count": sum(1 for state in states if state["exists"]),
        "required_count": len(required),
        "readonly_count": sum(
            1 for state in states if state["exists"] and state["readonly"]
        ),
        "extra_files": extra_files,
        "passed": not errors and len(states) == len(required),
        "errors": errors,
    }


def finalize_archive_readonly(
    archive_root: Path | str,
    *,
    required_artifacts: Sequence[str] = ARCHIVE_REQUIRED_ARTIFACTS,
) -> dict[str, Any]:
    """Apply read-only attributes only after all archive files are written."""

    root = _resolve(archive_root)
    required = tuple(str(name) for name in required_artifacts)
    before = verify_archive_finalization(root, required_artifacts=required)
    missing = [state["name"] for state in before["files"] if not state["exists"]]
    if missing:
        raise PreSwapGateError(
            "cannot finalize archive before all artifacts exist: " + ", ".join(missing)
        )
    if before["extra_files"]:
        raise PreSwapGateError(
            "cannot finalize archive with unexpected artifacts: "
            + ", ".join(before["extra_files"])
        )
    for name in required:
        _set_readonly(root / name)
    result = verify_archive_finalization(root, required_artifacts=required)
    if not result["passed"]:
        raise PreSwapGateError(
            "archive finalization failed: " + "; ".join(result["errors"])
        )
    return result


def verify_runtime_config_binding(
    config_path: Path | str,
    *,
    expected_run_id: str,
    expected_runtime_db: Path | str,
    expected_legacy_archive: Path | str,
) -> dict[str, Any]:
    """Verify existence and exact current-run binding of a V5 config."""

    resolved = _resolve(config_path)
    expected_run = str(expected_run_id).strip()
    expected_db = _resolve(expected_runtime_db)
    expected_archive = _resolve(expected_legacy_archive)
    errors: list[str] = []
    config: RuntimeStartupConfig | None = None
    if not resolved.is_file():
        errors.append("runtime startup config does not exist")
    else:
        try:
            config = RuntimeStartupConfig.read(resolved)
        except RuntimeStartupConfigError as exc:
            errors.append(str(exc))
    if not expected_run:
        errors.append("expected cutover run id is empty")
    if config is not None:
        if config.runtime_mode != "v5":
            errors.append(f"runtime_mode is not v5: {config.runtime_mode}")
        if _resolve(config.runtime_db) != expected_db:
            errors.append("runtime_db is not the expected canonical path")
        if _resolve(config.legacy_readonly_db or "") != expected_archive:
            errors.append("legacy_readonly_db is not this run archive")
        if config.production is not True:
            errors.append("production flag is not true")
        if config.cutover_run_id != expected_run:
            errors.append("cutover_run_id is not this run")
    payload = None
    if config is not None:
        payload = json.loads(config.as_json())
    return {
        "config_path": str(resolved),
        "runtime_config_target_path": str(resolved),
        "runtime_config_exists": resolved.is_file(),
        "runtime_config_run_id": config.cutover_run_id if config else None,
        "runtime_config_archive_path": config.legacy_readonly_db if config else None,
        "runtime_config_payload": payload,
        "passed": not errors,
        "errors": errors,
    }


def prepare_v5_runtime_config(
    *,
    config_path: Path | str,
    runtime_db: Path | str,
    legacy_archive: Path | str,
    cutover_run_id: str,
    generated_by: str = "core.migration.preswap.prepare_v5_runtime_config",
) -> dict[str, Any]:
    """Persist and immediately verify a validated, current-run V5 config."""

    archive = _resolve(legacy_archive)
    if not archive.is_file():
        raise PreSwapGateError(f"legacy archive does not exist: {archive}")
    if not str(cutover_run_id).strip():
        raise PreSwapGateError("cutover_run_id is required for V5 config binding")
    config = RuntimeStartupConfig.build(
        runtime_mode="v5",
        runtime_db=runtime_db,
        legacy_readonly_db=archive,
        production=True,
        generated_by=generated_by,
        cutover_run_id=cutover_run_id,
    )
    path = write_runtime_startup_config(config, config_path)
    result = verify_runtime_config_binding(
        path,
        expected_run_id=cutover_run_id,
        expected_runtime_db=runtime_db,
        expected_legacy_archive=archive,
    )
    if not result["passed"]:
        raise PreSwapGateError(
            "runtime config binding failed: " + "; ".join(result["errors"])
        )
    return result


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise PreSwapGateError(f"maintenance timestamp missing: {field}")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PreSwapGateError(f"maintenance timestamp invalid: {field}") from exc
    return parsed.astimezone(UTC)


def verify_maintenance_freshness(
    state_path: Path | str,
    *,
    now: datetime | None = None,
    port_probe: Callable[[], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify a live, unexpired, paused maintenance state at the gate."""

    resolved = _resolve(state_path)
    errors: list[str] = []
    state: Mapping[str, Any] = {}
    if not resolved.is_file():
        errors.append("maintenance state does not exist")
    else:
        try:
            loaded = json.loads(resolved.read_text(encoding="utf-8"))
            if isinstance(loaded, Mapping):
                state = loaded
            else:
                errors.append("maintenance state is not a JSON object")
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"maintenance state is unreadable: {exc}")

    current = (now or datetime.now(UTC)).astimezone(UTC)
    entered_at = None
    created_at = None
    expires_at = None
    elapsed = None
    remaining = None
    token = state.get("MaintenanceToken")
    if not isinstance(token, Mapping):
        errors.append("maintenance token evidence is missing")
    else:
        try:
            entered_at = _parse_timestamp(state.get("EnteredAt"), field="EnteredAt")
            created_at = _parse_timestamp(token.get("created_at_utc"), field="created_at_utc")
            expires_at = _parse_timestamp(token.get("expires_at_utc"), field="expires_at_utc")
            elapsed = current - entered_at
            remaining = expires_at - current
            if expires_at <= created_at:
                errors.append("maintenance token expiry is not after creation")
            if current < created_at:
                errors.append("maintenance token is not active yet")
            if current >= expires_at:
                errors.append("maintenance token is expired")
        except PreSwapGateError as exc:
            errors.append(str(exc))

    if state.get("ControllerElevated") is not True:
        errors.append("maintenance controller is not elevated")
    if state.get("MaintenancePaused") is not True:
        errors.append("maintenance state does not prove paused startup sources")
    if state.get("Restored") is True:
        errors.append("maintenance state has already been restored")
    if state.get("RespawnDetected") is True:
        errors.append("maintenance state records a respawn")
    task_states = state.get("MaintenanceTaskStates")
    if not isinstance(task_states, Mapping):
        errors.append("maintenance task state evidence is missing")
        task_states = {}
    for task_name in MAINTENANCE_TASKS:
        if str(task_states.get(task_name) or "") not in PAUSED_TASK_STATES:
            errors.append(f"maintenance task is not paused: {task_name}")

    live_port = None
    if state.get("PortFree") is not True:
        errors.append("maintenance state does not prove 8787 was free")
    if port_probe is not None:
        live_port = dict(port_probe())
        if live_port.get("classification") != "FREE" or live_port.get("owner_pid") is not None:
            errors.append("8787 is not currently FREE")

    return {
        "state_path": str(resolved),
        "entered_at": entered_at.isoformat() if entered_at else None,
        "token_created_at": created_at.isoformat() if created_at else None,
        "token_expires_at": expires_at.isoformat() if expires_at else None,
        "evaluated_at": current.isoformat(),
        "token_ttl_seconds": (expires_at - created_at).total_seconds()
        if expires_at and created_at
        else None,
        "elapsed_since_enter_seconds": elapsed.total_seconds() if elapsed else None,
        "ttl_remaining_seconds": remaining.total_seconds() if remaining else None,
        "task_states": dict(task_states),
        "live_port": live_port,
        "passed": not errors,
        "errors": errors,
    }


__all__ = [
    "ARCHIVE_REQUIRED_ARTIFACTS",
    "MAINTENANCE_TASKS",
    "PAUSED_TASK_STATES",
    "PreSwapGateError",
    "archive_file_state",
    "finalize_archive_readonly",
    "prepare_v5_runtime_config",
    "verify_archive_finalization",
    "verify_maintenance_freshness",
    "verify_runtime_config_binding",
]
