from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from core.runtime import DecisionEngine
from core.runtime.continuity import ContinuityStatus
from core.runtime.providers import (
    CapabilityValidationError,
    CompatibilityStatus,
    CostStatus,
    DuplicateProviderError,
    ExecutionMode,
    ProviderCapabilityProfile,
    ProviderCapabilityRegistry,
    ProviderRequirements,
    evaluate_compatibility,
)
from core.runtime.providers.manual import PROVIDER_IDENTITY as MANUAL_PROVIDER_IDENTITY
from core.runtime.providers.mock import PROVIDER_IDENTITY as MOCK_PROVIDER_IDENTITY
from core.runtime.shot_state import ShotStateProjector
from core.schemas.runtime_mvp import PROVIDER_CAPABILITY_V22_FIELDS


VERIFIED_AT = "2026-08-30T00:00:00Z"


def profile_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "provider": "fixture",
        "supports_first_frame": True,
        "supports_last_frame": True,
        "max_duration": 10,
        "max_images": 5,
        "manual_only": False,
        "estimated_cost_per_submit": None,
        "last_verified_at": VERIFIED_AT,
    }
    payload.update(overrides)
    return payload


def profile(**overrides: object) -> ProviderCapabilityProfile:
    return ProviderCapabilityProfile.from_dict(profile_payload(**overrides))


def requirements(**overrides: object) -> ProviderRequirements:
    values: dict[str, object] = {
        "duration": 5,
        "image_count": 2,
        "requires_first_frame": False,
        "requires_last_frame": False,
        "execution_mode": "automated",
    }
    values.update(overrides)
    return ProviderRequirements(**values)


def test_t24_p1_profile_uses_exact_v22_fields_and_validates() -> None:
    typed = profile()

    assert tuple(typed.to_dict()) == tuple(PROVIDER_CAPABILITY_V22_FIELDS)
    assert typed.provider == "fixture"
    assert typed.max_duration == 10.0
    assert typed.max_images == 5
    assert typed.to_dict()["last_verified_at"] == VERIFIED_AT.replace("Z", "+00:00")


@pytest.mark.parametrize("provider", ["", "   ", None, 1])
def test_t24_p2_provider_must_be_non_empty_text(provider: object) -> None:
    with pytest.raises(CapabilityValidationError):
        ProviderCapabilityProfile(provider, True, True, 10, 5, False)


@pytest.mark.parametrize("field", ["supports_first_frame", "supports_last_frame", "manual_only"])
@pytest.mark.parametrize("value", ["true", 1, "yes", 0])
def test_t24_p3_support_and_manual_flags_are_strict_booleans(field: str, value: object) -> None:
    with pytest.raises(CapabilityValidationError):
        ProviderCapabilityProfile.from_dict(profile_payload(**{field: value}))


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf"), "10"])
def test_t24_p4_duration_must_be_positive_finite_numeric(duration: object) -> None:
    with pytest.raises(CapabilityValidationError):
        ProviderCapabilityProfile.from_dict(profile_payload(max_duration=duration))


def test_t24_p5_zero_and_positive_max_images_are_valid() -> None:
    assert profile(max_images=0).max_images == 0
    assert profile(max_images=3).max_images == 3


@pytest.mark.parametrize("image_count", [-1, 1.5, "2", float("nan"), True])
def test_t24_p5_invalid_max_images_are_rejected(image_count: object) -> None:
    with pytest.raises(CapabilityValidationError):
        ProviderCapabilityProfile.from_dict(profile_payload(max_images=image_count))


def test_t24_p6_null_cost_is_unknown_not_zero() -> None:
    typed = profile(estimated_cost_per_submit=None)

    assert typed.estimated_cost_per_submit is None
    assert typed.cost_status is CostStatus.UNKNOWN


def test_t24_p7_explicit_zero_cost_is_known() -> None:
    typed = profile(estimated_cost_per_submit=0)

    assert typed.estimated_cost_per_submit == 0.0
    assert typed.cost_status is CostStatus.KNOWN


@pytest.mark.parametrize("cost", [-1, float("nan"), float("inf"), "0"])
def test_t24_p8_negative_or_invalid_cost_is_rejected(cost: object) -> None:
    with pytest.raises(CapabilityValidationError):
        ProviderCapabilityProfile.from_dict(profile_payload(estimated_cost_per_submit=cost))


def test_t24_p9_null_verification_is_unverified_and_never_filled_on_read() -> None:
    typed = profile(last_verified_at=None)
    before = typed.to_dict()
    after = typed.to_dict()

    assert typed.verified is False
    assert typed.verification_status == "UNVERIFIED"
    assert before["last_verified_at"] is None
    assert before == after


def test_t24_p10_timestamp_requires_timezone_and_accepts_static_aware_value() -> None:
    typed = profile(last_verified_at=datetime(2026, 8, 30, tzinfo=UTC))

    assert typed.last_verified_at == datetime(2026, 8, 30, tzinfo=UTC)
    assert profile(last_verified_at=VERIFIED_AT).verified is True
    with pytest.raises(CapabilityValidationError):
        profile(last_verified_at=datetime(2026, 8, 30))
    with pytest.raises(CapabilityValidationError):
        profile(last_verified_at="not-a-timestamp")


def test_t24_p11_first_frame_is_compatible_when_supported_and_verified() -> None:
    result = evaluate_compatibility(profile(), requirements(requires_first_frame=True))

    assert result.status is CompatibilityStatus.COMPATIBLE
    assert result.verified is True
    assert result.blockers == ()
    assert "supports_first_frame" in result.satisfied_constraints


def test_t24_p12_first_frame_is_incompatible_when_unsupported() -> None:
    result = evaluate_compatibility(profile(supports_first_frame=False), requirements(requires_first_frame=True))

    assert result.status is CompatibilityStatus.INCOMPATIBLE
    assert result.blockers[0].reason == "required_first_frame_not_supported"


def test_t24_p13_last_frame_is_incompatible_when_unsupported() -> None:
    result = evaluate_compatibility(profile(supports_last_frame=False), requirements(requires_last_frame=True))

    assert result.status is CompatibilityStatus.INCOMPATIBLE
    assert result.blockers[0].reason == "required_last_frame_not_supported"


def test_t24_p14_duration_exact_boundary_is_compatible() -> None:
    result = evaluate_compatibility(profile(max_duration=10), requirements(duration=10))

    assert result.status is CompatibilityStatus.COMPATIBLE
    assert any(item == "duration_within_max" for item in result.satisfied_constraints)


def test_t24_p15_duration_over_limit_is_explained() -> None:
    result = evaluate_compatibility(profile(max_duration=10), requirements(duration=10.001))

    assert result.status is CompatibilityStatus.INCOMPATIBLE
    assert len(result.blockers) == 1
    assert result.blockers[0].to_dict() == {
        "field": "max_duration",
        "required": 10.001,
        "available": 10.0,
        "reason": "duration_exceeds_provider_limit",
    }


@pytest.mark.parametrize("image_count", [0, 5])
def test_t24_p16_image_exact_boundaries_are_compatible(image_count: int) -> None:
    result = evaluate_compatibility(profile(max_images=5), requirements(image_count=image_count))

    assert result.status is CompatibilityStatus.COMPATIBLE
    assert "image_count_within_max" in result.satisfied_constraints


def test_t24_p17_images_over_limit_are_explained() -> None:
    result = evaluate_compatibility(profile(max_images=5), requirements(image_count=6))

    assert result.status is CompatibilityStatus.INCOMPATIBLE
    assert result.blockers[0].reason == "image_count_exceeds_provider_limit"


def test_t24_p18_manual_only_profile_rejects_automated_execution() -> None:
    result = evaluate_compatibility(profile(manual_only=True), requirements(execution_mode="automated"))

    assert result.status is CompatibilityStatus.INCOMPATIBLE
    assert result.blockers[0].to_dict() == {
        "field": "manual_only",
        "required": "automated",
        "available": True,
        "reason": "automated_execution_not_supported",
    }


def test_t24_p19_manual_only_profile_allows_manual_execution() -> None:
    result = evaluate_compatibility(profile(manual_only=True), requirements(execution_mode="manual"))

    assert result.status is CompatibilityStatus.COMPATIBLE
    assert result.blockers == ()


def test_t24_p20_satisfied_unverified_profile_is_not_compatible_verified() -> None:
    result = evaluate_compatibility(profile(last_verified_at=None), requirements())

    assert result.status is CompatibilityStatus.UNVERIFIED
    assert result.verified is False
    assert result.warnings[0].reason == "profile_unverified"


def test_t24_p21_multiple_incompatibilities_are_all_preserved_stably() -> None:
    result = evaluate_compatibility(
        profile(supports_last_frame=False, max_duration=10, max_images=5),
        requirements(duration=12, image_count=6, requires_last_frame=True),
    )

    assert result.status is CompatibilityStatus.INCOMPATIBLE
    assert [item.field for item in result.blockers] == ["supports_last_frame", "max_duration", "max_images"]


def test_t24_p22_unknown_provider_fails_closed_without_fallback() -> None:
    registry = ProviderCapabilityRegistry([profile(provider="mock")])
    result = registry.evaluate("seedance", requirements())

    assert result.status is CompatibilityStatus.UNKNOWN
    assert result.verified is False
    assert result.reason == "profile_not_found"
    assert result.warnings[0].field == "provider"


def test_t24_p23_duplicate_provider_registration_fails_closed() -> None:
    registry = ProviderCapabilityRegistry([profile(provider="manual")])

    with pytest.raises(DuplicateProviderError):
        registry.register(profile(provider="manual"))


def test_t24_p24_registry_and_evaluation_are_deterministic() -> None:
    registry = ProviderCapabilityRegistry([profile(provider="zeta"), profile(provider="alpha")])
    req_a = requirements(duration=10, image_count=5, requires_first_frame=True, requires_last_frame=True)
    req_b = ProviderRequirements.from_dict({**req_a.to_dict(), "execution_mode": "automated"})

    first = registry.evaluate("zeta", req_a)
    second = registry.evaluate("zeta", req_b)

    assert first == second
    assert [item.provider for item in registry.list()] == ["alpha", "zeta"]
    assert [item.field for item in first.blockers] == []


def test_t24_p25_evaluation_does_not_mutate_registry_or_runtime_surface() -> None:
    registry = ProviderCapabilityRegistry([profile(provider="fixture")])
    before = tuple(item.to_dict() for item in registry.list())
    first = registry.evaluate("fixture", requirements())
    second = registry.evaluate("fixture", requirements())
    after = tuple(item.to_dict() for item in registry.list())

    assert first == second
    assert before == after
    assert first.status is CompatibilityStatus.COMPATIBLE


def test_t24_p26_manual_identifier_and_cost_rule_are_preserved() -> None:
    typed = profile(provider=MANUAL_PROVIDER_IDENTITY, manual_only=True, estimated_cost_per_submit=None)

    assert typed.provider == "manual"
    assert typed.manual_only is True
    assert typed.cost_status is CostStatus.UNKNOWN
    assert typed.estimated_cost_per_submit != 0


def test_t24_p27_seedance_example_is_unverified_and_not_registered() -> None:
    seedance_example = profile(provider="seedance", last_verified_at=None)
    registry = ProviderCapabilityRegistry()

    result = evaluate_compatibility(seedance_example, requirements())
    assert result.status is CompatibilityStatus.UNVERIFIED
    assert result.verified is False
    assert registry.list() == ()
    assert registry.evaluate("seedance", requirements()).status is CompatibilityStatus.UNKNOWN


def test_t24_p28_t15_regression_surface_is_unchanged() -> None:
    result = DecisionEngine().decide({"issues": ("identity_drift",)})

    assert result.route.value == "REGENERATE_VIDEO"


def test_t24_p29_t14_regression_surface_is_unchanged() -> None:
    assert {item.value for item in ContinuityStatus} >= {"MATCH", "CONFLICT", "INVALID"}


def test_t24_p30_t13_regression_surface_is_unchanged() -> None:
    assert ShotStateProjector.__name__ == "ShotStateProjector"


def test_t24_p31_t48_mock_provider_surface_is_unchanged() -> None:
    assert MOCK_PROVIDER_IDENTITY == "mock"
    assert MANUAL_PROVIDER_IDENTITY == "manual"


def test_t24_strict_profile_and_requirement_fields_reject_unknown_values() -> None:
    with pytest.raises(CapabilityValidationError):
        ProviderCapabilityProfile.from_dict({**profile_payload(), "supports_audio": True})
    with pytest.raises(CapabilityValidationError):
        ProviderRequirements.from_dict({"duration": 5, "image_count": 1, "max_duration": 10})


@pytest.mark.parametrize(
    "raw",
    [
        {"duration": 5, "image_count": 1, "execution_mode": "manual"},
        {"duration": 5, "image_count": 1, "execution_mode": ExecutionMode.MANUAL},
    ],
)
def test_t24_requirements_execution_mode_is_typed(raw: dict[str, object]) -> None:
    typed = ProviderRequirements.from_dict(raw)

    assert typed.execution_mode is ExecutionMode.MANUAL
    assert typed.to_dict()["execution_mode"] == "manual"


def test_t24_result_is_json_serializable_and_has_required_explanation_fields() -> None:
    result = evaluate_compatibility(profile(), requirements(duration=11, image_count=6, requires_last_frame=True))
    payload = result.to_dict()

    assert set(payload) == {
        "provider",
        "status",
        "verified",
        "profile_last_verified_at",
        "requirements",
        "satisfied_constraints",
        "blockers",
        "warnings",
        "reason",
    }
    assert json.loads(json.dumps(payload, ensure_ascii=False))["status"] == "INCOMPATIBLE"
