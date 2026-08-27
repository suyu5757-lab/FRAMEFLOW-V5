"""Resolve explicit application runtime modes and persistence ownership."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from core.runtime.state_store.factory import CANONICAL_DATABASE_PATH, open_runtime_store

from .facade import RuntimePersistence


class RuntimeModeError(RuntimeError):
    """Raised when runtime mode configuration is missing or unsafe."""


def resolve_runtime_mode(environment: Mapping[str, str] | None = None) -> str:
    values = os.environ if environment is None else environment
    mode = str(values.get("FRAMEFLOW_RUNTIME_MODE") or "legacy").strip().lower()
    if mode not in {"legacy", "v5"}:
        raise RuntimeModeError("FRAMEFLOW_RUNTIME_MODE must be 'legacy' or 'v5'")
    return mode


def resolve_v5_database_path(environment: Mapping[str, str] | None = None) -> Path:
    values = os.environ if environment is None else environment
    raw = str(values.get("FRAMEFLOW_V5_DB") or values.get("FRAMEFLOW_DB_PATH") or "").strip()
    if not raw:
        raise RuntimeModeError(
            "V5 mode requires an explicit FRAMEFLOW_V5_DB candidate path; "
            "it never defaults to data/frameflow.db"
        )
    path = Path(raw).expanduser().resolve(strict=False)
    production_enabled = str(values.get("FRAMEFLOW_V5_PRODUCTION") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if path == CANONICAL_DATABASE_PATH and not production_enabled:
        raise RuntimeModeError(
            "pre-cutover V5 mode refuses the canonical production database path"
        )
    return path


def create_runtime_persistence(
    *,
    environment: Mapping[str, str] | None = None,
) -> RuntimePersistence:
    values = os.environ if environment is None else environment
    if resolve_runtime_mode(values) != "v5":
        raise RuntimeModeError("RuntimePersistence is only created for FRAMEFLOW_RUNTIME_MODE=v5")
    database_path = resolve_v5_database_path(values)
    legacy_path = str(values.get("FRAMEFLOW_LEGACY_READONLY_DB") or "").strip()
    production_enabled = str(values.get("FRAMEFLOW_V5_PRODUCTION") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    store = open_runtime_store(database_path, candidate=not production_enabled)
    try:
        return RuntimePersistence(store, legacy_path=Path(legacy_path) if legacy_path else None)
    except Exception:
        # A failed facade construction must not strand the factory-owned pool.
        store.dispose()
        raise


def shutdown_runtime_persistence(persistence: RuntimePersistence | None) -> None:
    """Explicitly release an application persistence instance, if present."""

    if persistence is not None:
        persistence.dispose()


__all__ = [
    "RuntimeModeError",
    "create_runtime_persistence",
    "resolve_runtime_mode",
    "resolve_v5_database_path",
    "shutdown_runtime_persistence",
]
