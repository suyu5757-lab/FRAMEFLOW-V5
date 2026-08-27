"""Application-facing persistence boundary for the V5 runtime."""

from .factory import (
    RuntimeModeError,
    create_runtime_persistence,
    resolve_runtime_mode,
    shutdown_runtime_persistence,
)
from .facade import RuntimePersistence, RuntimePersistenceError
from .startup_config import (
    DEFAULT_RUNTIME_CONFIG_PATH,
    RuntimeStartupConfig,
    RuntimeStartupConfigError,
    resolve_runtime_environment,
    write_runtime_startup_config,
)

__all__ = [
    "RuntimeModeError",
    "RuntimePersistence",
    "RuntimePersistenceError",
    "RuntimeStartupConfig",
    "RuntimeStartupConfigError",
    "DEFAULT_RUNTIME_CONFIG_PATH",
    "create_runtime_persistence",
    "resolve_runtime_mode",
    "resolve_runtime_environment",
    "shutdown_runtime_persistence",
    "write_runtime_startup_config",
]
