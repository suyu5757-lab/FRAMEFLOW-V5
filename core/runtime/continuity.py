"""T14 structured, read-only continuity comparison.

The checker compares an explicitly supplied upstream Shot to an explicitly
supplied downstream Shot.  It only compares structured declarations already
present in the Runtime contract; it does not infer adjacency or perform any
visual, semantic, or AI continuity analysis.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from sqlalchemy import select

from core.runtime.state_store import StateStore
from core.schemas.runtime_mvp import metadata
from frameflow.idempotency import canonical_json


class ContinuityStatus(StrEnum):
    MATCH = "MATCH"
    CONFLICT = "CONFLICT"
    INCOMPLETE = "INCOMPLETE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"


CONTINUITY_STATUSES = tuple(item.value for item in ContinuityStatus)
DEFAULT_SHOT_SPEC_SCHEMA = Path(__file__).resolve().parents[2] / "core" / "schemas" / "shot_spec_v2.2.schema.json"


@dataclass(frozen=True, slots=True)
class ContinuityIssue:
    code: str
    message: str
    blocking: bool = True
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "blocking": self.blocking,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class ContinuityConflict:
    path: str
    upstream_value: Any
    downstream_value: Any
    reason: str = "explicit_value_mismatch"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "upstream_value": self.upstream_value,
            "downstream_value": self.downstream_value,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ContinuityCheckResult:
    """Typed result for one explicit upstream OUT -> downstream IN pair."""

    upstream_shot_id: str
    downstream_shot_id: str
    status: str
    compared_keys: tuple[str, ...] = ()
    conflicts: tuple[ContinuityConflict, ...] = ()
    missing_in: tuple[str, ...] = ()
    missing_out: tuple[str, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)
    issues: tuple[ContinuityIssue, ...] = ()

    @property
    def has_conflict(self) -> bool:
        return bool(self.conflicts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "upstream_shot_id": self.upstream_shot_id,
            "downstream_shot_id": self.downstream_shot_id,
            "status": self.status,
            "compared_keys": list(self.compared_keys),
            "conflicts": [item.to_dict() for item in self.conflicts],
            "missing_in": list(self.missing_in),
            "missing_out": list(self.missing_out),
            "evidence": dict(self.evidence),
            "issues": [item.to_dict() for item in self.issues],
        }


@dataclass(frozen=True, slots=True)
class _Declaration:
    value: Mapping[str, Any] | None
    present: bool
    valid: bool
    source: str
    raw_present: bool = False


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _row_dict(row: Any) -> dict[str, Any] | None:
    return dict(row._mapping) if row is not None else None


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value == {} or value == []


def _decode_json(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str):
        try:
            return json.loads(value), True
        except json.JSONDecodeError:
            return None, False
    return value, True


def _json_equal(left: Any, right: Any) -> bool:
    """Canonical exact equality; list order and scalar types are preserved."""

    return canonical_json(left) == canonical_json(right)


def _leaf_paths(value: Any, path: str) -> list[str]:
    if isinstance(value, Mapping) and value:
        result: list[str] = []
        key_map = {str(item): item for item in value}
        for key in sorted(key_map, key=str):
            child = f"{path}.{key}" if path else key
            result.extend(_leaf_paths(value[key_map[key]], child))
        return result
    return [path or "$"]


def _parse_declaration(value: Any, source: str) -> _Declaration:
    raw_present = not _is_empty(value)
    if not raw_present:
        return _Declaration(None, False, True, source, False)
    decoded, valid_json = _decode_json(value)
    if not valid_json:
        return _Declaration(None, True, False, source, True)
    if _is_empty(decoded):
        return _Declaration(None, False, True, source, False)
    if not isinstance(decoded, Mapping):
        return _Declaration(None, True, False, source, True)
    return _Declaration(dict(decoded), True, True, source, True)


def _resolve_authority(
    runtime_value: Any,
    spec_value: Any,
    *,
    side: str,
    shot_id: str,
) -> tuple[_Declaration, ContinuityIssue | None, dict[str, Any]]:
    runtime = _parse_declaration(runtime_value, f"shots.continuity_{side}")
    spec = _parse_declaration(spec_value, f"shot_spec.continuity_state_{side}")
    evidence = {
        "runtime_field": runtime.source,
        "shot_spec_field": spec.source,
        "runtime_present": runtime.present,
        "shot_spec_present": spec.present,
        "selected_source": None,
    }
    if not runtime.valid:
        return runtime, ContinuityIssue(
            "MALFORMED_RUNTIME_CONTINUITY",
            f"{runtime.source} is not valid structured JSON.",
            details={"shot_id": shot_id, "side": side},
        ), evidence
    if not spec.valid:
        return spec, ContinuityIssue(
            "INVALID_SHOT_SPEC_CONTINUITY",
            f"{spec.source} is not a valid object declaration.",
            details={"shot_id": shot_id, "side": side},
        ), evidence
    if runtime.present and spec.present:
        if not _json_equal(runtime.value, spec.value):
            return runtime, ContinuityIssue(
                "INCONSISTENT_CONTINUITY_SOURCES",
                "Runtime continuity and ShotSpec continuity declarations disagree.",
                details={
                    "shot_id": shot_id,
                    "side": side,
                    "runtime_value": runtime.value,
                    "shot_spec_value": spec.value,
                },
            ), evidence
        evidence["selected_source"] = runtime.source
        evidence["corroborated_by"] = spec.source
        return runtime, None, evidence
    selected = runtime if runtime.present else spec
    evidence["selected_source"] = selected.source if selected.present else None
    return selected, None, evidence


def _compare_structured(
    upstream: Mapping[str, Any],
    downstream: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[ContinuityConflict, ...], tuple[str, ...], tuple[str, ...]]:
    compared: list[str] = []
    conflicts: list[ContinuityConflict] = []
    missing_in: list[str] = []
    missing_out: list[str] = []

    def visit(left: Any, right: Any, path: str) -> None:
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            left_keys = {str(key): key for key in left}
            right_keys = {str(key): key for key in right}
            for key in sorted(left_keys.keys() | right_keys.keys()):
                child = f"{path}.{key}" if path else key
                if key not in right_keys:
                    missing_in.extend(_leaf_paths(left[left_keys[key]], child))
                elif key not in left_keys:
                    missing_out.extend(_leaf_paths(right[right_keys[key]], child))
                else:
                    visit(left[left_keys[key]], right[right_keys[key]], child)
            return
        current_path = path or "$"
        compared.append(current_path)
        if not _json_equal(left, right):
            conflicts.append(ContinuityConflict(current_path, left, right))

    visit(upstream, downstream, "")
    return tuple(compared), tuple(conflicts), tuple(missing_in), tuple(missing_out)


class ContinuityChecker:
    """Read-only checker for an explicitly directed Shot pair."""

    def __init__(self, store: StateStore, *, schema_path: Path | str = DEFAULT_SHOT_SPEC_SCHEMA) -> None:
        if not isinstance(store, StateStore):
            raise TypeError("ContinuityChecker requires a StateStore")
        self.store = store
        self.schema_path = Path(schema_path).resolve(strict=False)
        schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self.validator = Draft202012Validator(schema)

    def _invalid(
        self,
        upstream_id: str,
        downstream_id: str,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> ContinuityCheckResult:
        issue = ContinuityIssue(code, message, details=details or {})
        return ContinuityCheckResult(
            upstream_id,
            downstream_id,
            ContinuityStatus.INVALID.value,
            evidence={"direction": "upstream.OUT -> downstream.IN"},
            issues=(issue,),
        )

    def _unknown(
        self,
        upstream_id: str,
        downstream_id: str,
        issue: ContinuityIssue,
        *,
        evidence: Mapping[str, Any] | None = None,
    ) -> ContinuityCheckResult:
        return ContinuityCheckResult(
            upstream_id,
            downstream_id,
            ContinuityStatus.UNKNOWN.value,
            evidence=evidence or {"direction": "upstream.OUT -> downstream.IN"},
            issues=(issue,),
        )

    def _load_pair(
        self,
        upstream_id: str,
        downstream_id: str,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, dict[str, Any]]]:
        shots = metadata.tables["shots"]
        sequences = metadata.tables["sequences"]
        with self.store.connection() as connection:
            rows = connection.execute(select(shots).where(shots.c.id.in_((upstream_id, downstream_id)))).mappings().all()
        by_id = {_text(row["id"]): dict(row) for row in rows}
        sequence_ids = {_text(row.get("sequence_id")) for row in by_id.values() if _text(row.get("sequence_id"))}
        if not sequence_ids:
            return by_id.get(upstream_id), by_id.get(downstream_id), {}
        with self.store.connection() as connection:
            sequence_rows = connection.execute(select(sequences).where(sequences.c.id.in_(sequence_ids))).mappings().all()
        return (
            by_id.get(upstream_id),
            by_id.get(downstream_id),
            {_text(row["id"]): dict(row) for row in sequence_rows},
        )

    def _shot_spec(self, row: Mapping[str, Any], shot_id: str) -> tuple[dict[str, Any] | None, ContinuityIssue | None]:
        raw = row.get("shot_spec_json")
        decoded, valid_json = _decode_json(raw)
        if not valid_json or not isinstance(decoded, dict):
            return None, ContinuityIssue(
                "INVALID_SHOT_SPEC",
                "shot_spec_json is not a valid JSON object.",
                details={"shot_id": shot_id},
            )
        errors = sorted(self.validator.iter_errors(decoded), key=lambda item: (tuple(str(part) for part in item.path), item.message))
        if errors:
            return None, ContinuityIssue(
                "INVALID_SHOT_SPEC",
                "ShotSpec does not satisfy ShotSpec v2.2.",
                details={"shot_id": shot_id, "path": [str(part) for part in errors[0].path], "message": errors[0].message},
            )
        if decoded.get("shot_id") != shot_id:
            return None, ContinuityIssue(
                "SHOT_SPEC_ID_MISMATCH",
                "ShotSpec.shot_id does not match the requested Shot ID.",
                details={"shot_id": shot_id, "actual": decoded.get("shot_id")},
            )
        if decoded.get("sequence_id") != _text(row.get("sequence_id")):
            return None, ContinuityIssue(
                "SHOT_SPEC_SEQUENCE_MISMATCH",
                "ShotSpec.sequence_id does not match the Runtime Shot sequence.",
                details={"shot_id": shot_id, "actual": decoded.get("sequence_id")},
            )
        return decoded, None

    def check_pair(self, upstream_shot_id: str, downstream_shot_id: str) -> ContinuityCheckResult:
        upstream_id = _text(upstream_shot_id)
        downstream_id = _text(downstream_shot_id)
        if not upstream_id or not downstream_id:
            return self._invalid(upstream_id, downstream_id, "SHOT_ID_REQUIRED", "Both explicit Shot IDs are required.")
        if upstream_id == downstream_id:
            return self._invalid(upstream_id, downstream_id, "SAME_SHOT_PAIR", "Upstream and downstream Shot IDs must differ.")
        upstream, downstream, sequence_rows = self._load_pair(upstream_id, downstream_id)
        if upstream is None or downstream is None:
            missing = upstream_id if upstream is None else downstream_id
            return self._invalid(upstream_id, downstream_id, "SHOT_NOT_FOUND", "An explicit pair member does not exist.", details={"missing_shot_id": missing})
        if _text(upstream.get("project_id")) != _text(downstream.get("project_id")):
            return self._invalid(upstream_id, downstream_id, "CROSS_PROJECT_PAIR", "Continuity pairs must belong to the same Project.")
        if _text(upstream.get("sequence_id")) != _text(downstream.get("sequence_id")):
            return self._invalid(upstream_id, downstream_id, "CROSS_SEQUENCE_PAIR", "T14 MVP only compares Shots in the same Sequence.")
        project_id = _text(upstream.get("project_id"))
        sequence_id = _text(upstream.get("sequence_id"))
        sequence = sequence_rows.get(sequence_id)
        if sequence is None or _text(sequence.get("project_id")) != project_id:
            return self._invalid(upstream_id, downstream_id, "SEQUENCE_NOT_FOUND", "The explicit pair sequence is missing or belongs to another Project.")

        upstream_spec, upstream_spec_issue = self._shot_spec(upstream, upstream_id)
        downstream_spec, downstream_spec_issue = self._shot_spec(downstream, downstream_id)
        if upstream_spec_issue is not None:
            return self._unknown(upstream_id, downstream_id, upstream_spec_issue)
        if downstream_spec_issue is not None:
            return self._unknown(upstream_id, downstream_id, downstream_spec_issue)
        assert upstream_spec is not None and downstream_spec is not None

        upstream_decl, upstream_issue, upstream_evidence = _resolve_authority(
            upstream.get("continuity_out"), upstream_spec.get("continuity_state_out"), side="out", shot_id=upstream_id
        )
        downstream_decl, downstream_issue, downstream_evidence = _resolve_authority(
            downstream.get("continuity_in"), downstream_spec.get("continuity_state_in"), side="in", shot_id=downstream_id
        )
        authority_evidence = {
            "direction": "upstream.OUT -> downstream.IN",
            "upstream": upstream_evidence,
            "downstream": downstream_evidence,
            "ignored_fields": ["ShotSpec.start_state", "ShotSpec.end_state"],
        }
        if upstream_issue is not None:
            return self._unknown(upstream_id, downstream_id, upstream_issue, evidence=authority_evidence)
        if downstream_issue is not None:
            return self._unknown(upstream_id, downstream_id, downstream_issue, evidence=authority_evidence)

        if not upstream_decl.present and not downstream_decl.present:
            return ContinuityCheckResult(
                upstream_id,
                downstream_id,
                ContinuityStatus.NOT_APPLICABLE.value,
                evidence=authority_evidence,
            )
        if not upstream_decl.present or not downstream_decl.present:
            missing_in = _leaf_paths(upstream_decl.value or {}, "") if upstream_decl.present else ()
            missing_out = _leaf_paths(downstream_decl.value or {}, "") if downstream_decl.present else ()
            return ContinuityCheckResult(
                upstream_id,
                downstream_id,
                ContinuityStatus.INCOMPLETE.value,
                missing_in=tuple(sorted(missing_in)),
                missing_out=tuple(sorted(missing_out)),
                evidence=authority_evidence,
            )

        assert upstream_decl.value is not None and downstream_decl.value is not None
        compared, conflicts, missing_in, missing_out = _compare_structured(upstream_decl.value, downstream_decl.value)
        status = ContinuityStatus.CONFLICT if conflicts else ContinuityStatus.INCOMPLETE if missing_in or missing_out else ContinuityStatus.MATCH
        return ContinuityCheckResult(
            upstream_id,
            downstream_id,
            status.value,
            compared_keys=compared,
            conflicts=conflicts,
            missing_in=missing_in,
            missing_out=missing_out,
            evidence=authority_evidence,
        )


def check_continuity(
    store: StateStore,
    upstream_shot_id: str,
    downstream_shot_id: str,
    *,
    schema_path: Path | str = DEFAULT_SHOT_SPEC_SCHEMA,
) -> ContinuityCheckResult:
    """Convenience wrapper for one explicit directed pair."""

    return ContinuityChecker(store, schema_path=schema_path).check_pair(upstream_shot_id, downstream_shot_id)


__all__ = [
    "CONTINUITY_STATUSES",
    "ContinuityChecker",
    "ContinuityCheckResult",
    "ContinuityConflict",
    "ContinuityIssue",
    "ContinuityStatus",
    "check_continuity",
]
