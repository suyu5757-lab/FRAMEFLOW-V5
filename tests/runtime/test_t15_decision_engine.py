from __future__ import annotations

import json

import pytest

from core.runtime import (
    DecisionEngine,
    DecisionInput,
    DecisionRoute,
    DecisionStatus,
    ProductionDecisionEngine,
    decide_production_route,
)


ENGINE = DecisionEngine()


@pytest.mark.parametrize(
    ("issue", "route"),
    [
        ("identity_drift", DecisionRoute.REGENERATE_VIDEO),
        ("character_count_error", DecisionRoute.REGENERATE_VIDEO),
        ("minor_artifact", DecisionRoute.PHOTOSHOP_REPAIR),
        ("color_mismatch", DecisionRoute.PHOTOSHOP_REPAIR),
        ("timing_issue", DecisionRoute.AE_REPAIR),
        ("caption_issue", DecisionRoute.AE_REPAIR),
    ],
)
def test_t15_d1_to_d6_frozen_issue_routes(issue: str, route: DecisionRoute) -> None:
    result = ENGINE.decide(DecisionInput(issues=(issue,)))

    assert result.status is DecisionStatus.DECIDED
    assert result.route is route
    assert result.reason == f"matched_{route.value.lower()}"
    assert result.evidence["route_families"] == {route.value: [issue]}


@pytest.mark.parametrize("score", [39.0, 39.999, 0.0])
def test_t15_d7_score_below_40_has_guard_precedence(score: float) -> None:
    result = ENGINE.decide(DecisionInput(issues=("minor_artifact",), score=score))

    assert result.status is DecisionStatus.DECIDED
    assert result.route is DecisionRoute.HUMAN_REVIEW
    assert result.reason == "score_below_human_review_threshold"
    assert result.matched_rules == ("guard:score_lt_40",)


def test_t15_d8_score_exactly_40_does_not_trigger_guard() -> None:
    result = ENGINE.decide(DecisionInput(issues=("minor_artifact",), score=40))

    assert result.route is DecisionRoute.PHOTOSHOP_REPAIR
    assert result.evidence["score_guard"]["applied"] is False


@pytest.mark.parametrize("count", [0, 1])
def test_t15_d9_failure_count_below_2_keeps_route(count: int) -> None:
    result = ENGINE.decide(
        DecisionInput(issues=("identity_drift",), same_issue_failure_counts={"identity_drift": count})
    )

    assert result.route is DecisionRoute.REGENERATE_VIDEO


@pytest.mark.parametrize("count", [2, 3])
def test_t15_d10_failure_count_at_least_2_routes_human_review(count: int) -> None:
    result = ENGINE.decide(
        DecisionInput(issues=("identity_drift",), same_issue_failure_counts={"identity_drift": count})
    )

    assert result.route is DecisionRoute.HUMAN_REVIEW
    assert result.reason == "same_issue_failure_threshold_reached"
    assert result.same_issue_failure_evidence == {"identity_drift": count}
    assert result.evidence["repeated_failure_guard"]["issues"] == ["identity_drift"]


def test_t15_d11_same_route_multiple_issues_is_one_route() -> None:
    result = ENGINE.decide(DecisionInput(issues=("color_mismatch", "minor_artifact")))

    assert result.route is DecisionRoute.PHOTOSHOP_REPAIR
    assert result.issues == ("color_mismatch", "minor_artifact")
    assert result.matched_rules == (
        "issue:color_mismatch->PHOTOSHOP_REPAIR",
        "issue:minor_artifact->PHOTOSHOP_REPAIR",
    )


def test_t15_d12_cross_route_issues_are_ambiguous_and_fail_closed() -> None:
    result = ENGINE.decide(DecisionInput(issues=("timing_issue", "identity_drift")))

    assert result.route is DecisionRoute.HUMAN_REVIEW
    assert result.reason == "ambiguous_multiple_route_families"
    assert tuple(result.evidence["route_families"]) == ("AE_REPAIR", "REGENERATE_VIDEO")


def test_t15_d13_duplicate_current_issues_do_not_fake_history() -> None:
    result = ENGINE.decide(
        DecisionInput(issues=("identity_drift", "identity_drift", "identity_drift"))
    )

    assert result.route is DecisionRoute.REGENERATE_VIDEO
    assert result.issues == ("identity_drift",)
    assert "repeated_failure_guard" not in result.evidence


def test_t15_d14_unknown_issue_is_preserved_and_requires_human_review() -> None:
    result = ENGINE.decide(DecisionInput(issues=("new_detector_issue",)))

    assert result.route is DecisionRoute.HUMAN_REVIEW
    assert result.reason == "unknown_issue_requires_human_review"
    assert result.unknown_issues == ("new_detector_issue",)
    assert result.evidence["unknown_issues"] == ["new_detector_issue"]


def test_t15_d15_no_issue_is_not_applicable_and_has_no_route() -> None:
    result = ENGINE.decide(DecisionInput())

    assert result.status is DecisionStatus.NOT_APPLICABLE
    assert result.route is None
    assert result.reason == "no_applicable_decision"


def test_t15_d16_none_score_is_unavailable_not_zero() -> None:
    result = ENGINE.decide(DecisionInput(issues=("minor_artifact",), score=None))

    assert result.route is DecisionRoute.PHOTOSHOP_REPAIR
    assert result.score is None
    assert result.evidence["score"] is None
    assert result.evidence["score_guard"]["applied"] is False


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.01, 100.01, "39"])
def test_t15_d17_invalid_score_returns_invalid_without_route(score: object) -> None:
    result = ENGINE.decide(DecisionInput(issues=("minor_artifact",), score=score))

    assert result.status is DecisionStatus.INVALID
    assert result.route is None
    assert result.reason == "invalid_decision_input"
    assert result.validation_errors


@pytest.mark.parametrize("count", [-1, 1.5, "2", float("nan")])
def test_t15_d18_invalid_failure_count_returns_invalid_without_route(count: object) -> None:
    result = ENGINE.decide(
        DecisionInput(issues=("identity_drift",), same_issue_failure_counts={"identity_drift": count})
    )

    assert result.status is DecisionStatus.INVALID
    assert result.route is None
    assert result.reason == "invalid_decision_input"


def test_t15_d19_issue_order_does_not_change_decision_or_explanation() -> None:
    first = ENGINE.decide(
        DecisionInput(issues=("caption_issue", "minor_artifact", "color_mismatch"), score=40)
    )
    second = ENGINE.decide(
        DecisionInput(issues=("color_mismatch", "caption_issue", "minor_artifact"), score=40)
    )

    assert first == second
    assert first.route is DecisionRoute.HUMAN_REVIEW
    assert first.reason == "ambiguous_multiple_route_families"


def test_t15_d20_t14_conflict_is_separate_evidence_not_a_route_rule() -> None:
    result = ENGINE.decide(
        DecisionInput(continuity_evidence={"status": "CONFLICT", "source": "T14"})
    )

    assert result.status is DecisionStatus.NOT_APPLICABLE
    assert result.route is None
    assert result.evidence["continuity_evidence"] == {"source": "T14", "status": "CONFLICT"}


def test_t15_d21_unknown_failure_evidence_fails_closed() -> None:
    result = ENGINE.decide(
        DecisionInput(same_issue_failure_counts={"future_issue": 2})
    )

    assert result.route is DecisionRoute.HUMAN_REVIEW
    assert result.reason == "unknown_failure_evidence_requires_human_review"


def test_t15_d22_guard_precedence_is_score_then_history_then_unknown() -> None:
    result = ENGINE.decide(
        DecisionInput(
            issues=("new_detector_issue", "minor_artifact"),
            score=39,
            same_issue_failure_counts={"minor_artifact": 2},
        )
    )

    assert result.route is DecisionRoute.HUMAN_REVIEW
    assert result.reason == "score_below_human_review_threshold"
    assert result.matched_rules == ("guard:score_lt_40",)


def test_t15_d23_result_is_typed_and_json_serializable() -> None:
    result = decide_production_route(DecisionInput(issues=("caption_issue",)))
    payload = result.to_dict()

    assert isinstance(result, type(ProductionDecisionEngine().decide(DecisionInput())))
    assert payload["route"] == "AE_REPAIR"
    assert json.loads(json.dumps(payload, ensure_ascii=False))["reason"] == "matched_ae_repair"


def test_t15_d24_engine_is_read_only_and_has_no_runtime_dependencies() -> None:
    module = __import__("core.runtime.decision_engine", fromlist=["DecisionEngine"])
    before = repr(DecisionInput(issues=("identity_drift",)))
    first = ENGINE.decide(DecisionInput(issues=("identity_drift",)))
    second = ENGINE.decide(DecisionInput(issues=("identity_drift",)))

    assert first == second
    assert repr(DecisionInput(issues=("identity_drift",))) == before
    assert not hasattr(module, "StateStore")
    assert not hasattr(module, "Task")
    assert not hasattr(module, "create_task")
