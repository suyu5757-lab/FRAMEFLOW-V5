"""Application-facing persistence boundary for the V5 runtime."""

from .factory import RuntimeModeError, create_runtime_persistence, resolve_runtime_mode
from .facade import RuntimePersistence, RuntimePersistenceError

__all__ = [
    "RuntimeModeError",
    "RuntimePersistence",
    "RuntimePersistenceError",
    "create_runtime_persistence",
    "resolve_runtime_mode",
]
