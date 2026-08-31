"""Runtime components for FRAMEFLOW."""

from importlib import import_module

from .event_log import EventLog, EventLogError, InvalidEventError
from .continuity import (
    ContinuityChecker,
    ContinuityCheckResult,
    ContinuityConflict,
    ContinuityIssue,
    ContinuityStatus,
    check_continuity,
)
from .shot_state import (
    ProjectionIssue,
    ShotState7D,
    ShotStateProjector,
    StateEvidence,
    derive_summary_state,
    get_shot_state,
    project_shot_state,
)
from .worker import (
    HandlerRegistry,
    TaskExecutionContext,
    TaskHandler,
    TaskTimeoutError,
    Worker,
    WorkerError,
    WorkerOutcome,
    WorkerOwnershipLost,
    WorkerRunResult,
)

_SUPERVISOR_EXPORTS = frozenset(
    {
        "LivenessResult",
        "LivenessState",
        "PROCESS_IDENTITIES",
        "ProcessInspectionError",
        "ProcessInspector",
        "ProcessRecord",
        "Supervisor",
        "SupervisorTarget",
        "UnsupportedTargetError",
        "WindowsProcessInspector",
    }
)


def __getattr__(name: str):
    """Load optional Supervisor exports only when a caller requests them."""

    if name not in _SUPERVISOR_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(".supervisor", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value

__all__ = [
    "EventLog",
    "EventLogError",
    "ContinuityChecker",
    "ContinuityCheckResult",
    "ContinuityConflict",
    "ContinuityIssue",
    "ContinuityStatus",
    "HandlerRegistry",
    "InvalidEventError",
    "ProjectionIssue",
    "ShotState7D",
    "ShotStateProjector",
    "StateEvidence",
    "LivenessResult",
    "LivenessState",
    "PROCESS_IDENTITIES",
    "ProcessInspectionError",
    "ProcessInspector",
    "ProcessRecord",
    "Supervisor",
    "SupervisorTarget",
    "UnsupportedTargetError",
    "WindowsProcessInspector",
    "TaskExecutionContext",
    "TaskHandler",
    "TaskTimeoutError",
    "Worker",
    "WorkerError",
    "WorkerOutcome",
    "WorkerOwnershipLost",
    "WorkerRunResult",
    "derive_summary_state",
    "get_shot_state",
    "project_shot_state",
    "check_continuity",
]
