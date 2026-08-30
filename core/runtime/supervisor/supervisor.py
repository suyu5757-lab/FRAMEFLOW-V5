"""Typed, read-only Creative App process liveness detection.

T11 observes a point-in-time process snapshot.  It never starts or stops a
process, mutates Runtime state, or turns an observation into Task recovery.
"""

from __future__ import annotations

import csv
import ntpath
import os
import subprocess
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Callable, Protocol

try:
    import psutil
except ImportError:  # pragma: no cover - exercised by the formal minimal venv
    psutil = None  # type: ignore[assignment]


class SupervisorTarget(StrEnum):
    """The only Creative App targets accepted by T11."""

    PHOTOSHOP = "PHOTOSHOP"
    AFTER_EFFECTS = "AFTER_EFFECTS"
    RESOLVE = "RESOLVE"


class LivenessState(StrEnum):
    """Minimal liveness semantics independent of TaskState."""

    RUNNING = "RUNNING"
    NOT_RUNNING = "NOT_RUNNING"
    UNKNOWN = "UNKNOWN"


PROCESS_IDENTITIES: Mapping[SupervisorTarget, tuple[str, ...]] = MappingProxyType(
    {
        SupervisorTarget.PHOTOSHOP: ("Photoshop.exe",),
        SupervisorTarget.AFTER_EFFECTS: ("AfterFX.exe", "aerender.exe"),
        SupervisorTarget.RESOLVE: ("Resolve.exe",),
    }
)
_NORMALIZED_IDENTITIES: Mapping[SupervisorTarget, frozenset[str]] = MappingProxyType(
    {
        target: frozenset(ntpath.basename(name).casefold() for name in names)
        for target, names in PROCESS_IDENTITIES.items()
    }
)
_TRANSIENT_PROCESS_ERRORS = (
    (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess)
    if psutil is not None
    else ()
) + (PermissionError, ProcessLookupError)


class SupervisorError(RuntimeError):
    """Base error for bounded Supervisor contracts."""


class UnsupportedTargetError(SupervisorError, ValueError):
    """Raised when a caller supplies anything other than a typed target."""


class ProcessInspectionError(SupervisorError):
    """Raised when the process backend cannot provide a reliable enumeration."""


@dataclass(frozen=True, slots=True)
class ProcessRecord:
    """Minimal process evidence exposed by the Supervisor."""

    pid: int
    executable_name: str
    executable_path: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.pid, bool) or not isinstance(self.pid, int) or self.pid < 0:
            raise ValueError("pid must be a non-negative integer")
        if not isinstance(self.executable_name, str) or not self.executable_name.strip():
            raise ValueError("executable_name must be a non-empty string")
        if self.executable_path is not None and not isinstance(self.executable_path, str):
            raise ValueError("executable_path must be a string or None")


class ProcessInspector(Protocol):
    """Small backend seam that keeps Supervisor logic independently testable."""

    def list_processes(self) -> Iterable[ProcessRecord]:
        """Return the current point-in-time process observations."""


class WindowsProcessInspector:
    """Read process evidence through psutil or a fixed Windows fallback."""

    def list_processes(self) -> Iterator[ProcessRecord]:
        """Enumerate processes without shell commands or process side effects."""

        if psutil is None:
            yield from self._list_with_tasklist()
            return

        try:
            processes = iter(psutil.process_iter(attrs=("pid", "name", "exe")))
        except Exception as exc:  # pragma: no cover - psutil setup failure is environment-specific
            raise ProcessInspectionError("process enumeration backend unavailable") from exc

        while True:
            try:
                process = next(processes)
            except StopIteration:
                return
            except _TRANSIENT_PROCESS_ERRORS:
                # A process can disappear or deny inspection between the
                # iterator snapshot and this read.  Continue the point-in-time
                # scan; Supervisor will only return UNKNOWN for backend-level
                # failures that make the enumeration unreliable.
                continue
            except Exception as exc:  # pragma: no cover - backend-specific failure
                raise ProcessInspectionError("process enumeration failed") from exc

            try:
                info = process.info
                name = str(info.get("name") or "").strip()
                if not name:
                    continue
                path_value = info.get("exe")
                path = str(path_value) if path_value else None
                yield ProcessRecord(
                    pid=int(info["pid"]),
                    executable_name=ntpath.basename(name),
                    executable_path=path,
                )
            except _TRANSIENT_PROCESS_ERRORS:
                continue
            except (TypeError, ValueError, KeyError) as exc:
                raise ProcessInspectionError("process record was malformed") from exc
            except Exception as exc:  # pragma: no cover - backend-specific failure
                raise ProcessInspectionError("process inspection failed") from exc

    @staticmethod
    def _list_with_tasklist() -> Iterator[ProcessRecord]:
        """Use only fixed trusted arguments when psutil is unavailable."""

        if os.name != "nt":
            raise ProcessInspectionError("Windows process backend unavailable")
        completed = subprocess.run(
            ["tasklist.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            raise ProcessInspectionError("tasklist process enumeration failed")
        for row in csv.reader(completed.stdout.splitlines()):
            if not row or row[0].startswith("INFO:"):
                continue
            if len(row) < 2 or not row[1].strip().isdigit():
                raise ProcessInspectionError("tasklist returned a malformed process record")
            yield ProcessRecord(
                pid=int(row[1].strip()),
                executable_name=ntpath.basename(row[0].strip()),
            )


@dataclass(frozen=True, slots=True)
class LivenessResult:
    """Deterministic typed result for one Supervisor target."""

    target: SupervisorTarget
    state: LivenessState
    observed_at: datetime
    matched_processes: tuple[ProcessRecord, ...]
    error_code: str | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalized_name(value: str) -> str:
    return ntpath.basename(value.strip()).casefold()


class Supervisor:
    """Read-only Supervisor for the frozen Creative App target set."""

    _TARGETS = tuple(SupervisorTarget)

    def __init__(
        self,
        inspector: ProcessInspector | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._inspector = inspector or WindowsProcessInspector()
        self._clock = clock or _utc_now

    def probe(self, target: SupervisorTarget) -> LivenessResult:
        """Observe one typed target without mutating any Runtime state."""

        normalized_target = self._require_target(target)
        observed_at = self._observed_at()
        records, error_code = self._collect_processes()
        return self._build_result(normalized_target, observed_at, records, error_code)

    def snapshot(self) -> dict[SupervisorTarget, LivenessResult]:
        """Observe all frozen targets from one backend enumeration."""

        observed_at = self._observed_at()
        records, error_code = self._collect_processes()
        return {
            target: self._build_result(target, observed_at, records, error_code)
            for target in self._TARGETS
        }

    @staticmethod
    def _require_target(target: SupervisorTarget) -> SupervisorTarget:
        if not isinstance(target, SupervisorTarget):
            raise UnsupportedTargetError(
                "target must be a SupervisorTarget enum value"
            )
        return target

    def _observed_at(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Supervisor clock must return an aware datetime")
        return value.astimezone(UTC)

    def _collect_processes(self) -> tuple[tuple[ProcessRecord, ...], str | None]:
        try:
            source = iter(self._inspector.list_processes())
        except Exception:
            return (), "enumeration_failed"

        records: list[ProcessRecord] = []
        while True:
            try:
                record = next(source)
            except StopIteration:
                return tuple(records), None
            except _TRANSIENT_PROCESS_ERRORS:
                continue
            except Exception:
                return (), "enumeration_failed"
            if not isinstance(record, ProcessRecord):
                return (), "invalid_process_record"
            records.append(record)

    @staticmethod
    def _build_result(
        target: SupervisorTarget,
        observed_at: datetime,
        records: tuple[ProcessRecord, ...],
        error_code: str | None,
    ) -> LivenessResult:
        if error_code is not None:
            return LivenessResult(
                target=target,
                state=LivenessState.UNKNOWN,
                observed_at=observed_at,
                matched_processes=(),
                error_code=error_code,
            )

        accepted = _NORMALIZED_IDENTITIES[target]
        matches = tuple(
            sorted(
                (
                    record
                    for record in records
                    if _normalized_name(record.executable_name) in accepted
                ),
                key=lambda record: (
                    record.pid,
                    _normalized_name(record.executable_name),
                    record.executable_path or "",
                ),
            )
        )
        return LivenessResult(
            target=target,
            state=LivenessState.RUNNING if matches else LivenessState.NOT_RUNNING,
            observed_at=observed_at,
            matched_processes=matches,
        )


__all__ = [
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
]
