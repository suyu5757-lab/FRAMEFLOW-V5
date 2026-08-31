"""T15 pure production decision engine.

The engine converts explicit QA evidence into one of the four frozen
production routes. It is deliberately independent of StateStore, Task,
provider, filesystem, and network APIs: a caller may use the result to
explain a decision, but T15 does not execute the selected route.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from numbers import Real
from typing import Any


class DecisionRoute(StrEnum):
    """The only four production routes permitted by the V5 contract."""

    REGENERATE_VIDEO = "REGENERATE_VIDEO"
    PHOTOSHOP_REPAIR = "PHOTOSHOP_REPAIR"
    AE_REPAIR = "AE_REPAIR"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class DecisionStatus(StrEnum):
    """Outcome class, separate from the selected route."""

    DECIDED = "DECIDED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INVALID = "INVALID"


class DecisionIssue(StrEnum):
    """The six issue identifiers with an automatic route mapping."""

    IDENTITY_DRIFT = "identity_drift"
    CHARACTER_COUNT_ERROR = "character_count_error"
    MINOR_ARTIFACT = "minor_artifact"
    COLOR_MISMATCH = "color_mismatch"
    TIMING_ISSUE = "timing_issue"
    CAPTION_ISSUE = "caption_issue"


ISSUE_TO_ROUTE: Mapping[str, DecisionRoute] = {
    DecisionIssue.IDENTITY_DRIFT.value: DecisionRoute.REGENERATE_VIDEO,
    DecisionIssue.CHARACTER_COUNT_ERROR.value: DecisionRoute.REGENERATE_VIDEO,
    DecisionIssue.MINOR_ARTIFACT.value: DecisionRoute.PHOTOSHOP_REPAIR,
    DecisionIssue.COLOR_MISMATCH.value: DecisionRoute.PHOTOSHOP_REPAIR,
    DecisionIssue.TIMING_ISSUE.value: DecisionRoute.AE_REPAIR,
    DecisionIssue.CAPTION_ISSUE.value: DecisionRoute.AE_REPAIR,
}

HUMAN_REVIEW_SCORE_THRESHOLD = 40.0
SAME_ISSUE_FAILURE_THRESHOLD = 2


@dataclass(frozen=True, slots=True)
class DecisionInput:
    """Explicit evidence supplied to :class:`DecisionEngine`.

    Runtime callers should pass issue identifiers from the current QA result;
    repeated current identifiers are intentionally not historical failures.
    ``continuity_evidence`` is kept separate so T14 ``CONFLICT`` can be
    carried alongside this decision without becoming a T15 route rule.
    """

    issues: Sequence[Any] = ()
    score: Any = None
    same_issue_failure_counts: Mapping[Any, Any] = field(default_factory=dict)
    continuity_evidence: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class DecisionResult:
    """Stable, explainable result returned by the read-only engine."""

    status: DecisionStatus
    route: DecisionRoute | None
    reason: str
    score: float | None = None
    same_issue_failure_evidence: Mapping[str, int] = field(default_factory=dict)
    issues: tuple[str, ...] = ()
    unknown_issues: tuple[str, ...] = ()
    matched_rules: tuple[str, ...] = ()
    validation_errors: tuple[str, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Expose the normalized evidence at the stable top-level contract."""

        if self.score is None and "score" in self.evidence:
            object.__setattr__(self, "score", self.evidence["score"])
        if not self.same_issue_failure_evidence:
            raw_counts = self.evidence.get("same_issue_failure_counts", ())
            counts = {
                str(item["issue"]): int(item["count"])
                for item in raw_counts
                if isinstance(item, Mapping) and "issue" in item and "count" in item
            }
            object.__setattr__(self, "same_issue_failure_evidence", counts)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation for logs and UI output."""

        return {
            "status": self.status.value,
            "route": self.route.value if self.route is not None else None,
            "reason": self.reason,
            "score": self.score,
            "same_issue_failure_evidence": dict(self.same_issue_failure_evidence),
            "issues": list(self.issues),
            "unknown_issues": list(self.unknown_issues),
            "matched_rules": list(self.matched_rules),
            "validation_errors": list(self.validation_errors),
            "evidence": _json_safe(dict(self.evidence)),
        }


@dataclass(frozen=True, slots=True)
class _ValidatedInput:
    issues: tuple[str, ...]
    unknown_issues: tuple[str, ...]
    score: float | None
    failure_counts: tuple[tuple[str, int], ...]
    unknown_failure_counts: tuple[tuple[str, int], ...]
    errors: tuple[str, ...]
    continuity_evidence: Mapping[str, Any] | None


def _json_safe(value: Any) -> Any:
    """Convert result evidence to JSON-compatible primitives deterministically."""

    if isinstance(value, Mapping):
        return {str(key): _json_safe(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _normalize_issue_values(raw_issues: Any) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    errors: list[str] = []
    if isinstance(raw_issues, (str, bytes)) or not isinstance(raw_issues, Sequence):
        return (), (), ("issues_must_be_a_sequence_of_strings",)

    normalized: set[str] = set()
    for index, raw_issue in enumerate(raw_issues):
        if not isinstance(raw_issue, str) or not raw_issue.strip():
            errors.append(f"issues[{index}]_must_be_a_non_empty_string")
            continue
        normalized.add(raw_issue.strip())
    ordered = tuple(sorted(normalized))
    unknown = tuple(issue for issue in ordered if issue not in ISSUE_TO_ROUTE)
    return ordered, unknown, tuple(sorted(errors))


def _normalize_score(raw_score: Any) -> tuple[float | None, tuple[str, ...]]:
    if raw_score is None:
        return None, ()
    if isinstance(raw_score, bool) or not isinstance(raw_score, Real):
        return None, ("score_must_be_numeric_or_none",)
    score = float(raw_score)
    if not math.isfinite(score):
        return None, ("score_must_be_finite",)
    if not 0.0 <= score <= 100.0:
        return None, ("score_must_be_between_0_and_100",)
    return score, ()


def _normalize_failure_counts(raw_counts: Any) -> tuple[tuple[tuple[str, int], ...], tuple[str, ...]]:
    if not isinstance(raw_counts, Mapping):
        return (), ("same_issue_failure_counts_must_be_a_mapping",)

    errors: list[str] = []
    normalized: dict[str, int] = {}
    for raw_issue, raw_count in raw_counts.items():
        if not isinstance(raw_issue, str) or not raw_issue.strip():
            errors.append("failure_count_issue_keys_must_be_non_empty_strings")
            continue
        issue = raw_issue.strip()
        if issue in normalized:
            errors.append(f"duplicate_failure_count_issue:{issue}")
            continue
        if isinstance(raw_count, bool) or not isinstance(raw_count, int):
            errors.append(f"failure_count_must_be_non_negative_integer:{issue}")
            continue
        if raw_count < 0:
            errors.append(f"failure_count_must_be_non_negative_integer:{issue}")
            continue
        normalized[issue] = raw_count

    ordered = tuple(sorted(normalized.items(), key=lambda item: item[0]))
    return ordered, tuple(sorted(errors))


def _validate_input(value: DecisionInput) -> _ValidatedInput:
    issues, unknown_issues, issue_errors = _normalize_issue_values(value.issues)
    score, score_errors = _normalize_score(value.score)
    failure_counts, count_errors = _normalize_failure_counts(value.same_issue_failure_counts)
    known_counts = tuple(item for item in failure_counts if item[0] in ISSUE_TO_ROUTE)
    unknown_counts = tuple(item for item in failure_counts if item[0] not in ISSUE_TO_ROUTE)
    return _ValidatedInput(
        issues=issues,
        unknown_issues=unknown_issues,
        score=score,
        failure_counts=known_counts,
        unknown_failure_counts=unknown_counts,
        errors=tuple(sorted((*issue_errors, *score_errors, *count_errors))),
        continuity_evidence=value.continuity_evidence,
    )


def _base_evidence(data: _ValidatedInput) -> dict[str, Any]:
    route_families: dict[str, list[str]] = {}
    for issue in data.issues:
        route = ISSUE_TO_ROUTE.get(issue)
        if route is not None:
            route_families.setdefault(route.value, []).append(issue)
    return {
        "current_issues": list(data.issues),
        "unknown_issues": list(data.unknown_issues),
        "route_families": {key: values for key, values in sorted(route_families.items())},
        "score": data.score,
        "score_guard": {
            "threshold": HUMAN_REVIEW_SCORE_THRESHOLD,
            "applied": data.score is not None and data.score < HUMAN_REVIEW_SCORE_THRESHOLD,
        },
        "same_issue_failure_counts": [
            {"issue": issue, "count": count, "threshold": SAME_ISSUE_FAILURE_THRESHOLD}
            for issue, count in data.failure_counts
        ],
        "unknown_failure_counts": [
            {"issue": issue, "count": count, "threshold": SAME_ISSUE_FAILURE_THRESHOLD}
            for issue, count in data.unknown_failure_counts
        ],
    }


class DecisionEngine:
    """Pure T15 four-route decision engine.

    ``decide`` performs no I/O and has no access to Runtime persistence. It
    returns a HUMAN_REVIEW route for evidence that is unsafe to auto-route,
    while reserving ``route=None`` for invalid or non-applicable decisions.
    """

    def decide(self, decision_input: DecisionInput | Mapping[str, Any]) -> DecisionResult:
        if isinstance(decision_input, Mapping):
            try:
                decision_input = DecisionInput(**dict(decision_input))
            except (TypeError, ValueError) as exc:
                return DecisionResult(
                    DecisionStatus.INVALID,
                    None,
                    "invalid_decision_input",
                    validation_errors=(f"decision_input_mapping_invalid:{exc}",),
                )
        if not isinstance(decision_input, DecisionInput):
            return DecisionResult(
                DecisionStatus.INVALID,
                None,
                "invalid_decision_input",
                validation_errors=("decision_input_must_be_DecisionInput_or_mapping",),
            )

        data = _validate_input(decision_input)
        evidence = _base_evidence(data)
        if data.continuity_evidence is not None:
            evidence["continuity_evidence"] = _json_safe(data.continuity_evidence)

        if data.errors:
            evidence["validation_errors"] = list(data.errors)
            return DecisionResult(
                DecisionStatus.INVALID,
                None,
                "invalid_decision_input",
                issues=data.issues,
                unknown_issues=data.unknown_issues,
                validation_errors=data.errors,
                evidence=evidence,
            )

        if data.score is not None and data.score < HUMAN_REVIEW_SCORE_THRESHOLD:
            evidence["score_guard"]["applied"] = True
            return DecisionResult(
                DecisionStatus.DECIDED,
                DecisionRoute.HUMAN_REVIEW,
                "score_below_human_review_threshold",
                issues=data.issues,
                unknown_issues=data.unknown_issues,
                matched_rules=("guard:score_lt_40",),
                evidence=evidence,
            )

        repeated = tuple(
            issue for issue, count in data.failure_counts if count >= SAME_ISSUE_FAILURE_THRESHOLD
        )
        if repeated:
            evidence["repeated_failure_guard"] = {
                "applied": True,
                "issues": list(repeated),
            }
            return DecisionResult(
                DecisionStatus.DECIDED,
                DecisionRoute.HUMAN_REVIEW,
                "same_issue_failure_threshold_reached",
                issues=data.issues,
                unknown_issues=data.unknown_issues,
                matched_rules=tuple(f"guard:failure_count_ge_2:{issue}" for issue in repeated),
                evidence=evidence,
            )

        if data.unknown_failure_counts:
            evidence["unknown_failure_guard"] = {
                "applied": True,
                "issues": [issue for issue, _ in data.unknown_failure_counts],
            }
            return DecisionResult(
                DecisionStatus.DECIDED,
                DecisionRoute.HUMAN_REVIEW,
                "unknown_failure_evidence_requires_human_review",
                issues=data.issues,
                unknown_issues=data.unknown_issues,
                matched_rules=("guard:unknown_failure_evidence",),
                evidence=evidence,
            )

        if data.unknown_issues:
            evidence["unknown_issue_guard"] = {"applied": True}
            return DecisionResult(
                DecisionStatus.DECIDED,
                DecisionRoute.HUMAN_REVIEW,
                "unknown_issue_requires_human_review",
                issues=data.issues,
                unknown_issues=data.unknown_issues,
                matched_rules=tuple(f"guard:unknown_issue:{issue}" for issue in data.unknown_issues),
                evidence=evidence,
            )

        route_families = tuple(sorted({ISSUE_TO_ROUTE[issue] for issue in data.issues}, key=lambda route: route.value))
        if len(route_families) > 1:
            return DecisionResult(
                DecisionStatus.DECIDED,
                DecisionRoute.HUMAN_REVIEW,
                "ambiguous_multiple_route_families",
                issues=data.issues,
                matched_rules=("guard:multiple_route_families",),
                evidence=evidence,
            )

        if len(route_families) == 1:
            route = route_families[0]
            matched_rules = tuple(f"issue:{issue}->{route.value}" for issue in data.issues)
            return DecisionResult(
                DecisionStatus.DECIDED,
                route,
                f"matched_{route.value.lower()}",
                issues=data.issues,
                matched_rules=matched_rules,
                evidence=evidence,
            )

        return DecisionResult(
            DecisionStatus.NOT_APPLICABLE,
            None,
            "no_applicable_decision",
            issues=data.issues,
            evidence=evidence,
        )


ProductionDecisionEngine = DecisionEngine


def decide_production_route(decision_input: DecisionInput | Mapping[str, Any]) -> DecisionResult:
    """Convenience wrapper for one pure T15 decision."""

    return DecisionEngine().decide(decision_input)


__all__ = [
    "DecisionEngine",
    "DecisionInput",
    "DecisionIssue",
    "DecisionResult",
    "DecisionRoute",
    "DecisionStatus",
    "HUMAN_REVIEW_SCORE_THRESHOLD",
    "ISSUE_TO_ROUTE",
    "ProductionDecisionEngine",
    "SAME_ISSUE_FAILURE_THRESHOLD",
    "decide_production_route",
]
