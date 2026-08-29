"""Explicit, ambient-config-independent application factories for tests."""

from __future__ import annotations

import importlib.util
import os
import socket
import sys
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Iterator
from uuid import uuid4

from core.runtime.persistence.startup_config import (
    RuntimeStartupConfig,
    write_runtime_startup_config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER_PATH = PROJECT_ROOT / "server.py"
REAL_CANONICAL_DB = (PROJECT_ROOT / "data" / "frameflow.db").resolve()
REAL_RUNTIME_CONFIG = (PROJECT_ROOT / "data" / "runtime-startup.json").resolve()

_RUNTIME_ENVIRONMENT_KEYS = (
    "FRAMEFLOW_RUNTIME_CONFIG",
    "FRAMEFLOW_RUNTIME_MODE",
    "FRAMEFLOW_DB_PATH",
    "FRAMEFLOW_V5_DB",
    "FRAMEFLOW_V5_PRODUCTION",
    "FRAMEFLOW_V5_PRODUCTION_SIMULATION",
    "FRAMEFLOW_LEGACY_READONLY_DB",
    "FRAMEFLOW_BIND_HOST",
    "JIMENG_CLI_HOME",
)


def _set_environment(overrides: dict[str, str | None]) -> dict[str, str | None]:
    previous = {key: os.environ.get(key) for key in _RUNTIME_ENVIRONMENT_KEYS}
    for key in _RUNTIME_ENVIRONMENT_KEYS:
        value = overrides.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    return previous


def _restore_environment(previous: dict[str, str | None]) -> None:
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _load_fresh_server_module(
    *,
    runtime_config_path: Path,
    runtime_mode: str,
    db_path: Path,
    legacy_readonly_db: Path | None,
    production: bool,
) -> tuple[ModuleType, str]:
    overrides: dict[str, str | None] = {
        "FRAMEFLOW_RUNTIME_CONFIG": str(runtime_config_path),
        "FRAMEFLOW_RUNTIME_MODE": runtime_mode,
        "FRAMEFLOW_DB_PATH": str(db_path),
        "FRAMEFLOW_BIND_HOST": "127.0.0.1",
        "JIMENG_CLI_HOME": str(runtime_config_path.with_suffix(".dreamina-home")),
        "FRAMEFLOW_V5_DB": None,
        "FRAMEFLOW_V5_PRODUCTION": None,
        "FRAMEFLOW_V5_PRODUCTION_SIMULATION": None,
        "FRAMEFLOW_LEGACY_READONLY_DB": None,
    }
    if runtime_mode == "v5":
        overrides.update(
            {
                "FRAMEFLOW_V5_DB": str(db_path),
                "FRAMEFLOW_V5_PRODUCTION": "1" if production else "0",
                "FRAMEFLOW_V5_PRODUCTION_SIMULATION": "1" if production else "0",
                "FRAMEFLOW_LEGACY_READONLY_DB": str(legacy_readonly_db or ""),
            }
        )
    previous = _set_environment(overrides)
    module_name = f"_frameflow_test_server_{uuid4().hex}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, SERVER_PATH)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"could not create isolated server spec: {SERVER_PATH}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    finally:
        _restore_environment(previous)
    return module, module_name


@dataclass
class IsolatedServerRuntime:
    """Fresh server module plus the explicit files it owns for one test."""

    module: ModuleType
    module_name: str
    db_path: Path
    runtime_config_path: Path
    runtime_mode: str

    @property
    def app(self):
        return self.module.app

    def assert_isolated(self) -> None:
        resolved_db = self.db_path.resolve(strict=False)
        resolved_config = self.runtime_config_path.resolve(strict=False)
        if resolved_db == REAL_CANONICAL_DB:
            raise AssertionError("isolated test runtime resolved the real canonical DB")
        if resolved_config == REAL_RUNTIME_CONFIG:
            raise AssertionError("isolated test runtime resolved real runtime-startup.json")
        if self.module.DB_PATH.resolve(strict=False) != resolved_db:
            raise AssertionError(f"server DB_PATH escaped explicit test DB: {self.module.DB_PATH}")
        if self.module.RUNTIME_MODE != self.runtime_mode:
            raise AssertionError(f"server runtime mode escaped explicit test mode: {self.module.RUNTIME_MODE}")
        configured = Path(self.module.RUNTIME_ENVIRONMENT["FRAMEFLOW_RUNTIME_CONFIG"]).resolve(strict=False)
        if configured != resolved_config:
            raise AssertionError(f"server runtime config escaped explicit test config: {configured}")

    def close(self) -> None:
        persistence = getattr(self.app.state, "persistence", None)
        if persistence is not None:
            persistence.dispose()
        sys.modules.pop(self.module_name, None)
        for path in (
            self.runtime_config_path,
            self.db_path,
            Path(f"{self.db_path}-wal"),
            Path(f"{self.db_path}-shm"),
        ):
            if path.is_file():
                path.unlink()


def _config_path_for(db_path: Path, suffix: str) -> Path:
    return db_path.with_name(f".{db_path.stem}.{suffix}-{uuid4().hex}.json")


def create_legacy_test_app(
    db_path: Path | str,
    *,
    runtime_config_path: Path | str | None = None,
) -> IsolatedServerRuntime:
    """Create a fresh Legacy app that cannot consult production config."""

    resolved_db = Path(db_path).expanduser().resolve(strict=False)
    resolved_config = (
        Path(runtime_config_path).expanduser().resolve(strict=False)
        if runtime_config_path
        else _config_path_for(resolved_db, "legacy-runtime")
    )
    config = RuntimeStartupConfig.build(
        runtime_mode="legacy",
        runtime_db=resolved_db,
        legacy_readonly_db=None,
        production=False,
        generated_by="tests.support.runtime_isolation.create_legacy_test_app",
    )
    write_runtime_startup_config(config, resolved_config)
    module, module_name = _load_fresh_server_module(
        runtime_config_path=resolved_config,
        runtime_mode="legacy",
        db_path=resolved_db,
        legacy_readonly_db=None,
        production=False,
    )
    runtime = IsolatedServerRuntime(module, module_name, resolved_db, resolved_config, "legacy")
    runtime.assert_isolated()
    return runtime


def create_v5_test_app(
    db_path: Path | str,
    legacy_readonly_db: Path | str,
    *,
    runtime_config_path: Path | str | None = None,
    production: bool = True,
) -> IsolatedServerRuntime:
    """Create a fresh isolated V5 app for contract and leak tests."""

    resolved_db = Path(db_path).expanduser().resolve(strict=False)
    resolved_legacy = Path(legacy_readonly_db).expanduser().resolve(strict=False)
    resolved_config = (
        Path(runtime_config_path).expanduser().resolve(strict=False)
        if runtime_config_path
        else _config_path_for(resolved_db, "v5-runtime")
    )
    config = RuntimeStartupConfig.build(
        runtime_mode="v5",
        runtime_db=resolved_db,
        legacy_readonly_db=resolved_legacy,
        production=production,
        generated_by="tests.support.runtime_isolation.create_v5_test_app",
        cutover_run_id="isolated-v5-runtime-test",
    )
    write_runtime_startup_config(config, resolved_config)
    module, module_name = _load_fresh_server_module(
        runtime_config_path=resolved_config,
        runtime_mode="v5",
        db_path=resolved_db,
        legacy_readonly_db=resolved_legacy,
        production=production,
    )
    runtime = IsolatedServerRuntime(module, module_name, resolved_db, resolved_config, "v5")
    runtime.assert_isolated()
    return runtime


@contextmanager
def forbid_real_production_network() -> Iterator[None]:
    """Fail if a test attempts to contact the real production HTTP port."""

    original_urlopen = urllib.request.urlopen
    original_create_connection = socket.create_connection

    def guarded_urlopen(url, *args, **kwargs):
        rendered = str(getattr(url, "full_url", url))
        if "127.0.0.1:8787" in rendered or "localhost:8787" in rendered:
            raise AssertionError(f"isolated test contacted real Production 8787: {rendered}")
        return original_urlopen(url, *args, **kwargs)

    def guarded_create_connection(address, *args, **kwargs):
        host, port = address[0], address[1]
        if str(host).lower() in {"127.0.0.1", "localhost"} and int(port) == 8787:
            raise AssertionError(
                f"isolated test contacted real Production 8787: {host}:{port}"
            )
        return original_create_connection(address, *args, **kwargs)

    urllib.request.urlopen = guarded_urlopen
    socket.create_connection = guarded_create_connection
    try:
        yield
    finally:
        urllib.request.urlopen = original_urlopen
        socket.create_connection = original_create_connection


__all__ = [
    "REAL_CANONICAL_DB",
    "REAL_RUNTIME_CONFIG",
    "IsolatedServerRuntime",
    "create_legacy_test_app",
    "create_v5_test_app",
    "forbid_real_production_network",
]
