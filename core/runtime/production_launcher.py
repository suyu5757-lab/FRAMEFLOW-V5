"""Mode-aware production runtime target resolution and startup.

The scheduled task is an auto-start policy, not the runtime itself.  This
module is the single formal entrypoint used by the PowerShell launcher to
resolve the persisted runtime ownership decision, fail closed on invalid V5
state, start the project interpreter, and verify the resulting HTTP runtime.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from core.migration.legacy_compat import LegacyReadOnlyError, inspect_legacy_archive
from core.migration.port_ownership import parse_netstat_listeners
from core.runtime.persistence.startup_config import (
    DEFAULT_RUNTIME_CONFIG_PATH,
    RUNTIME_CONFIG_ENV,
    RuntimeStartupConfig,
    RuntimeStartupConfigError,
)
from core.runtime.state_store.factory import CANONICAL_DATABASE_PATH, inspect_database


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FORMAL_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
RUNTIME_ENVIRONMENT_KEYS = (
    "FRAMEFLOW_RUNTIME_MODE",
    "FRAMEFLOW_DB_PATH",
    "FRAMEFLOW_V5_DB",
    "FRAMEFLOW_V5_PRODUCTION",
    "FRAMEFLOW_LEGACY_READONLY_DB",
    RUNTIME_CONFIG_ENV,
)


class ProductionLauncherError(RuntimeError):
    """Raised when the selected runtime cannot be proven safe to start."""


@dataclass(frozen=True)
class RuntimeTarget:
    """Resolved runtime ownership for one launcher invocation."""

    mode: str
    runtime_db: Path
    legacy_readonly_db: Path | None
    production: bool
    config_path: Path
    config_present: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "runtime_db": str(self.runtime_db),
            "legacy_readonly_db": (
                str(self.legacy_readonly_db) if self.legacy_readonly_db else None
            ),
            "production": self.production,
            "config_path": str(self.config_path),
            "config_present": self.config_present,
        }

    def child_environment(
        self,
        *,
        base: Mapping[str, str] | None = None,
        bind_host: str = "127.0.0.1",
    ) -> dict[str, str]:
        """Build a clean child environment from the resolved target.

        In particular, a stale V5 environment inherited by a normal Legacy
        scheduled task can never override an absent Legacy startup config.
        """

        values = dict(os.environ if base is None else base)
        for name in RUNTIME_ENVIRONMENT_KEYS:
            values.pop(name, None)
        if self.config_present:
            config = RuntimeStartupConfig.read(self.config_path)
            values.update(config.to_environment())
            values[RUNTIME_CONFIG_ENV] = str(self.config_path)
        else:
            values["FRAMEFLOW_RUNTIME_MODE"] = "legacy"
            values["FRAMEFLOW_DB_PATH"] = str(self.runtime_db)
        values["FRAMEFLOW_BIND_HOST"] = bind_host
        return values


def _resolve_config_path(config_path: Path | str | None) -> tuple[Path, bool]:
    if config_path is not None:
        return Path(config_path).expanduser().resolve(strict=False), True
    explicit = str(os.environ.get(RUNTIME_CONFIG_ENV) or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve(strict=False), True
    return DEFAULT_RUNTIME_CONFIG_PATH.resolve(strict=False), False


def _require_database(path: Path, expected_schema: str) -> dict[str, Any]:
    if not path.is_file():
        raise ProductionLauncherError(f"runtime database does not exist: {path}")
    try:
        info = inspect_database(path)
    except Exception as exc:  # pragma: no cover - platform/SQLite detail
        raise ProductionLauncherError(f"runtime database cannot be inspected: {path}: {exc}") from exc
    if info.get("schema") != expected_schema:
        raise ProductionLauncherError(
            f"runtime database schema mismatch: expected={expected_schema} actual={info.get('schema')} path={path}"
        )
    return info


def resolve_runtime_target(
    config_path: Path | str | None = None,
    *,
    canonical_database: Path = CANONICAL_DATABASE_PATH,
) -> RuntimeTarget:
    """Resolve the persisted target; absent default config means Legacy.

    An explicitly requested but missing config is an error.  Only the implicit
    default path may be absent and select the current Legacy canonical path.
    """

    resolved_config, explicit = _resolve_config_path(config_path)
    if not resolved_config.is_file():
        if explicit:
            raise ProductionLauncherError(
                f"runtime startup config does not exist: {resolved_config}"
            )
        runtime_db = canonical_database.expanduser().resolve(strict=False)
        _require_database(runtime_db, "LEGACY_V3")
        return RuntimeTarget(
            mode="legacy",
            runtime_db=runtime_db,
            legacy_readonly_db=None,
            production=True,
            config_path=resolved_config,
            config_present=False,
        )

    try:
        config = RuntimeStartupConfig.read(resolved_config)
    except RuntimeStartupConfigError as exc:
        raise ProductionLauncherError(str(exc)) from exc

    runtime_db = Path(config.runtime_db).expanduser().resolve(strict=False)
    if config.runtime_mode == "v5":
        if config.production and runtime_db != canonical_database.resolve(strict=False):
            raise ProductionLauncherError(
                "production V5 runtime must use the canonical database path"
            )
        if not config.production and runtime_db == canonical_database.resolve(strict=False):
            raise ProductionLauncherError(
                "isolated V5 runtime must not use the canonical production database"
            )
        database_info = _require_database(runtime_db, "V5_RUNTIME")
        del database_info
        legacy_path = Path(str(config.legacy_readonly_db)).expanduser().resolve(strict=False)
        if not legacy_path.is_file():
            raise ProductionLauncherError(f"legacy readonly archive does not exist: {legacy_path}")
        try:
            legacy_info = inspect_legacy_archive(legacy_path)
        except (LegacyReadOnlyError, OSError, RuntimeError) as exc:
            raise ProductionLauncherError(
                f"legacy readonly archive is invalid: {legacy_path}: {exc}"
            ) from exc
        if legacy_info.get("schema") != "LEGACY_V3":
            raise ProductionLauncherError(
                f"legacy readonly archive schema mismatch: {legacy_info.get('schema')}"
            )
        return RuntimeTarget(
            mode="v5",
            runtime_db=runtime_db,
            legacy_readonly_db=legacy_path,
            production=bool(config.production),
            config_path=resolved_config,
            config_present=True,
        )

    _require_database(runtime_db, "LEGACY_V3")
    return RuntimeTarget(
        mode="legacy",
        runtime_db=runtime_db,
        legacy_readonly_db=None,
        production=bool(config.production),
        config_path=resolved_config,
        config_present=True,
    )


def _listeners(port: int) -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["netstat.exe", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise ProductionLauncherError(f"netstat failed: {completed.stderr.strip()}")
    return parse_netstat_listeners(completed.stdout, port)


def _get_json(url: str, timeout: float = 2.0) -> tuple[int, dict[str, Any]]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status, payload if isinstance(payload, dict) else {}
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            payload = {}
        return exc.code, payload if isinstance(payload, dict) else {}


def _runtime_evidence(target: RuntimeTarget, port: int) -> dict[str, Any] | None:
    listeners = _listeners(port)
    if not listeners:
        return None
    if len(listeners) != 1:
        raise ProductionLauncherError(f"expected one listener on {port}, found {len(listeners)}")
    health_status, health = _get_json(f"http://127.0.0.1:{port}/api/health")
    doctor_status, doctor = _get_json(f"http://127.0.0.1:{port}/api/system/doctor")
    if health_status != 200 or doctor_status != 200:
        # A just-started Uvicorn process can bind before FastAPI finishes its
        # lifespan.  Keep polling during that narrow readiness window.
        return None
    expected_db = str(target.runtime_db)
    if (
        health.get("runtime_mode") != target.mode
        or str(doctor.get("database") or "") != expected_db
    ):
        raise ProductionLauncherError(
            "port is occupied by a runtime that does not match the selected target: "
            f"expected_mode={target.mode} actual_mode={health.get('runtime_mode')} "
            f"expected_db={expected_db} actual_db={doctor.get('database')}"
        )
    return {
        "port": port,
        "owner_pid": int(listeners[0]["pid"]),
        "listeners": listeners,
        "health_status": health_status,
        "health": health,
        "doctor_status": doctor_status,
        "doctor": doctor,
    }


def validate_target(config_path: Path | str | None = None) -> dict[str, Any]:
    """Return auditable target evidence without starting any process."""

    return resolve_runtime_target(config_path).as_dict()


def start_runtime_for_current_config(
    config_path: Path | str | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    timeout: float = 45.0,
) -> dict[str, Any]:
    """Start and verify the exact runtime selected by the current config."""

    if Path(sys.executable).resolve(strict=False) != FORMAL_PYTHON.resolve(strict=False):
        raise ProductionLauncherError(
            f"formal interpreter required: expected={FORMAL_PYTHON} actual={sys.executable}"
        )
    target = resolve_runtime_target(config_path)
    existing = _runtime_evidence(target, port)
    if existing is not None:
        return {"status": "already_running", "target": target.as_dict(), **existing}

    environment = target.child_environment(bind_host=host)
    command = [
        str(FORMAL_PYTHON),
        "-m",
        "uvicorn",
        "server:app",
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    deadline = time.monotonic() + timeout
    last_error = "no health response"
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise ProductionLauncherError(
                    f"formal runtime exited during startup: returncode={process.returncode}"
                )
            try:
                evidence = _runtime_evidence(target, port)
                if evidence is not None:
                    return {
                        "status": "started",
                        "target": target.as_dict(),
                        "launcher_pid": process.pid,
                        **evidence,
                    }
            except (OSError, ProductionLauncherError) as exc:
                last_error = str(exc)
                if "occupied by a runtime" in last_error or "expected one listener" in last_error:
                    raise
            time.sleep(0.25)
        raise ProductionLauncherError(
            f"runtime did not become healthy within {timeout:g}s: {last_error}"
        )
    except Exception:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive cleanup
                process.kill()
                process.wait(timeout=5)
        raise


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--validate-only", action="store_true")
    action.add_argument("--start", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--timeout", type=float, default=45.0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.validate_only:
        payload = validate_target(args.config)
    else:
        payload = start_runtime_for_current_config(
            args.config,
            host=args.host,
            port=args.port,
            timeout=args.timeout,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by Windows launcher
    raise SystemExit(main())


__all__ = [
    "FORMAL_PYTHON",
    "PROJECT_ROOT",
    "ProductionLauncherError",
    "RuntimeTarget",
    "resolve_runtime_target",
    "start_runtime_for_current_config",
    "validate_target",
]
