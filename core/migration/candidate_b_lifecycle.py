"""Fail-closed lifecycle tracking for the terminal Candidate B artifact.

Candidate B is a closed swap artifact, not a runtime candidate.  This module
tracks its evidence boundary and rejects known database-opening helpers after
the final rename probe has sealed the file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping


class CandidateBSealError(RuntimeError):
    """Raised when Candidate B is accessed after its terminal seal boundary."""


class CandidateBState(StrEnum):
    BUILDING = "BUILDING"
    VALIDATING = "VALIDATING"
    EVIDENCE_COMPLETE = "EVIDENCE_COMPLETE"
    HANDLES_CLOSED = "HANDLES_CLOSED"
    FINAL_RENAME_PROBE = "FINAL_RENAME_PROBE"
    SEALED = "SEALED"
    ATOMIC_REPLACEMENT = "ATOMIC_REPLACEMENT"


_LIFECYCLES: dict[str, "CandidateBTerminalSeal"] = {}


def _key(path: Path | str) -> str:
    return str(Path(path).expanduser().resolve(strict=False)).casefold()


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def assert_candidate_b_database_open_allowed(path: Path | str) -> None:
    """Record or reject a known Candidate B database-open operation."""

    lifecycle = _LIFECYCLES.get(_key(path))
    if lifecycle is not None:
        lifecycle.record_database_open()


@dataclass
class CandidateBTerminalSeal:
    """Own Candidate B's evidence-to-sealed lifecycle for one run."""

    path: Path | str
    state: CandidateBState = CandidateBState.BUILDING
    candidate_db_open_count: int = 0
    post_seal_db_open_count: int = 0
    post_seal_db_open_attempts: int = 0
    evidence_complete_at: str | None = None
    handles_closed_at: str | None = None
    rename_at: str | None = None
    sealed_at: str | None = None

    def __post_init__(self) -> None:
        self.path = Path(self.path).expanduser().resolve(strict=False)
        key = _key(self.path)
        if key in _LIFECYCLES:
            raise CandidateBSealError(f"Candidate B lifecycle already exists: {self.path}")
        _LIFECYCLES[key] = self

    def _require(self, expected: CandidateBState) -> None:
        if self.state != expected:
            raise CandidateBSealError(
                f"Candidate B lifecycle state mismatch: expected={expected.value} actual={self.state.value}"
            )

    def begin_validation(self) -> None:
        self._require(CandidateBState.BUILDING)
        self.state = CandidateBState.VALIDATING

    def record_database_open(self) -> None:
        if self.state in {
            CandidateBState.HANDLES_CLOSED,
            CandidateBState.FINAL_RENAME_PROBE,
            CandidateBState.SEALED,
            CandidateBState.ATOMIC_REPLACEMENT,
        }:
            if self.state in {CandidateBState.SEALED, CandidateBState.ATOMIC_REPLACEMENT}:
                self.post_seal_db_open_attempts += 1
            raise CandidateBSealError(
                "Candidate B is sealed; database reopen after final rename is forbidden"
            )
        self.candidate_db_open_count += 1

    def mark_evidence_complete(self, evidence: Mapping[str, Any]) -> None:
        self._require(CandidateBState.VALIDATING)
        required = (
            "candidate",
            "source_legacy_sha",
            "migration_revision",
            "migration_implementation_version",
            "schema_contract_version",
            "schema_fingerprint",
            "logical_fingerprint",
            "row_accounting",
            "validation",
        )
        missing = [name for name in required if not evidence.get(name)]
        if missing:
            raise CandidateBSealError(
                "Candidate B evidence is incomplete before sealing: " + ", ".join(missing)
            )
        if Path(str(evidence.get("candidate"))).resolve(strict=False) != self.path:
            raise CandidateBSealError("Candidate B evidence path does not match lifecycle path")
        if evidence.get("backend_opened") is not False:
            raise CandidateBSealError("Candidate B backend-opened must be NO")
        if evidence.get("validation_passed") is not True:
            raise CandidateBSealError("Candidate B validation must pass before sealing")
        logical = evidence.get("logical_fingerprint")
        schema = evidence.get("schema_fingerprint")
        accounting = evidence.get("row_accounting")
        if not isinstance(logical, Mapping) or len(logical.get("tables") or {}) != 11:
            raise CandidateBSealError("Candidate B logical evidence must contain all 11 domain tables")
        if not isinstance(schema, Mapping) or int(schema.get("domain_table_count") or 0) != 11:
            raise CandidateBSealError("Candidate B schema evidence must contain all 11 domain tables")
        if not isinstance(accounting, Mapping):
            raise CandidateBSealError("Candidate B row accounting evidence is missing")
        for field in ("unknown", "unaccounted", "required_shots", "accounted_shots"):
            if field not in accounting:
                raise CandidateBSealError(f"Candidate B row accounting field is missing: {field}")
        self.state = CandidateBState.EVIDENCE_COMPLETE
        self.evidence_complete_at = _timestamp()

    def mark_handles_closed(self) -> None:
        self._require(CandidateBState.EVIDENCE_COMPLETE)
        self.state = CandidateBState.HANDLES_CLOSED
        self.handles_closed_at = _timestamp()

    def finalize_rename_probe(
        self,
        rename_probe: Callable[[Path], Mapping[str, Any]],
    ) -> dict[str, Any]:
        self._require(CandidateBState.HANDLES_CLOSED)
        self.state = CandidateBState.FINAL_RENAME_PROBE
        result = dict(rename_probe(self.path))
        if result.get("passed") is not True:
            raise CandidateBSealError("Candidate B final rename probe failed")
        self.rename_at = _timestamp()
        self.sealed_at = _timestamp()
        self.state = CandidateBState.SEALED
        result["terminal_seal"] = self.evidence()
        return result

    def evidence(self) -> dict[str, Any]:
        return {
            "candidate": str(self.path),
            "state": self.state.value,
            "candidate_db_open_count": self.candidate_db_open_count,
            "candidate_b_post_seal_db_open_count": self.post_seal_db_open_count,
            "post_seal_db_open_count": self.post_seal_db_open_count,
            "post_seal_db_open_attempts": self.post_seal_db_open_attempts,
            "evidence_complete_at": self.evidence_complete_at,
            "handles_closed_at": self.handles_closed_at,
            "rename_at": self.rename_at,
            "sealed_at": self.sealed_at,
            "candidate_b_reopened_after_rename": self.post_seal_db_open_count > 0,
        }


__all__ = [
    "CandidateBSealError",
    "CandidateBState",
    "CandidateBTerminalSeal",
    "assert_candidate_b_database_open_allowed",
]
