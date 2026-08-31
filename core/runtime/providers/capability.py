"""T24 provider capability contract and read-only compatibility surface.

This module defines the smallest provider-neutral capability vocabulary needed
by V5. It owns no database table, does not discover providers, and performs no
network verification. Profiles may be registered during configuration setup;
normal reads and compatibility evaluation are pure operations.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from numbers import Real
from typing import Any

from core.schemas.runtime_mvp import PROVIDER_CAPABILITY_V22_FIELDS


PROFILE_FIELDS = tuple(PROVIDER_CAPABILITY_V22_FIELDS)
_REQUIRED_PROFILE_FIELDS = frozenset(
    {
        "provider",
        "supports_first_frame",
        "supports_last_frame",
        "max_duration",
        "max_images",
        "manual_only",
    }
)
_OPTIONAL_PROFILE_FIELDS = frozenset(PROFILE_FIELDS) - _REQUIRED_PROFILE_FIELDS
_REQUIREMENT_FIELDS = (
    "duration",
    "image_count",
    "requires_first_frame",
    "requires_last_frame",
    "execution_mode",
)
_EXECUTION_MODES = frozenset({"manual", "automated"})


class CapabilityValidationError(ValueError):
    """Typed rejection of malformed capability or requirement input."""

    def __init__(self, message: str, *, code: str = "INVALID_CAPABILITY_INPUT") -> None:
        self.code = code
        super().__init__(message)


class DuplicateProviderError(CapabilityValidationError):
    """A registry refuses an ambiguous second definition for one provider."""

    def __init__(self, provider: str) -> None:
        super().__init__(
            f"provider capability profile is already registered: {provider}",
            code="DUPLICATE_PROVIDER_PROFILE",
        )


class ProfileNotFoundError(LookupError):
    """No capability profile is registered for the requested provider."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(f"provider capability profile not found: {provider}")


class CompatibilityStatus(StrEnum):
    """Typed result statuses for one provider/requirements evaluation."""

    COMPATIBLE = "COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNVERIFIED = "UNVERIFIED"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"


class CostStatus(StrEnum):
    """The only derived cost states in T24."""

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


class ExecutionMode(StrEnum):
    MANUAL = "manual"
    AUTOMATED = "automated"


def _require_mapping(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CapabilityValidationError(f"{field_name} must be an object")
    return value


def _strict_bool(value: Any, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise CapabilityValidationError(f"{field_name} must be a boolean")
    return value


def _finite_real(value: Any, *, field_name: str, minimum: float, strict_minimum: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise CapabilityValidationError(f"{field_name} must be numeric")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise CapabilityValidationError(f"{field_name} must be finite numeric") from exc
    if not math.isfinite(number):
        raise CapabilityValidationError(f"{field_name} must be finite")
    if number < minimum or (strict_minimum and number == minimum):
        operator = ">" if strict_minimum else ">="
        raise CapabilityValidationError(f"{field_name} must be {operator} {minimum}")
    return number


def _non_negative_int(value: Any, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise CapabilityValidationError(f"{field_name} must be an integer >= 0")
    return value


def _provider_id(value: Any, *, field_name: str = "provider") -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityValidationError(f"{field_name} must be a non-empty string")
    # Existing V5 provider IDs are exact lower-case identifiers, but the
    # contract does not silently merge case variants such as Manual/manual.
    return value.strip()


def _timestamp(value: Any, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        if not value.strip():
            raise CapabilityValidationError(f"{field_name} must be an ISO timestamp or None")
        try:
            value = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise CapabilityValidationError(f"{field_name} must be an ISO timestamp or None") from exc
    if not isinstance(value, datetime):
        raise CapabilityValidationError(f"{field_name} must be a datetime, ISO timestamp, or None")
    if value.tzinfo is None or value.utcoffset() is None:
        raise CapabilityValidationError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _timestamp_json(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True, slots=True)
class ProviderCapabilityProfile:
    """The exact eight-field v2.2 declared capability profile."""

    provider: str
    supports_first_frame: bool
    supports_last_frame: bool
    max_duration: float
    max_images: int
    manual_only: bool
    estimated_cost_per_submit: float | None = None
    last_verified_at: datetime | str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _provider_id(self.provider))
        object.__setattr__(self, "supports_first_frame", _strict_bool(self.supports_first_frame, field_name="supports_first_frame"))
        object.__setattr__(self, "supports_last_frame", _strict_bool(self.supports_last_frame, field_name="supports_last_frame"))
        object.__setattr__(self, "max_duration", _finite_real(self.max_duration, field_name="max_duration", minimum=0.0, strict_minimum=True))
        object.__setattr__(self, "max_images", _non_negative_int(self.max_images, field_name="max_images"))
        object.__setattr__(self, "manual_only", _strict_bool(self.manual_only, field_name="manual_only"))
        if self.estimated_cost_per_submit is not None:
            object.__setattr__(
                self,
                "estimated_cost_per_submit",
                _finite_real(self.estimated_cost_per_submit, field_name="estimated_cost_per_submit", minimum=0.0),
            )
        object.__setattr__(self, "last_verified_at", _timestamp(self.last_verified_at, field_name="last_verified_at"))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderCapabilityProfile":
        payload = _require_mapping(value, field_name="capability profile")
        unknown = sorted(set(payload) - set(PROFILE_FIELDS), key=str)
        if unknown:
            raise CapabilityValidationError(
                f"capability profile contains unknown fields: {unknown}",
                code="UNKNOWN_PROFILE_FIELDS",
            )
        missing = sorted(_REQUIRED_PROFILE_FIELDS - set(payload), key=str)
        if missing:
            raise CapabilityValidationError(
                f"capability profile is missing fields: {missing}",
                code="MISSING_PROFILE_FIELDS",
            )
        try:
            return cls(**{field_name: payload[field_name] for field_name in PROFILE_FIELDS if field_name in payload})
        except TypeError as exc:
            raise CapabilityValidationError("capability profile field shape is invalid") from exc

    @property
    def verified(self) -> bool:
        return self.last_verified_at is not None

    @property
    def verification_status(self) -> str:
        return "VERIFIED" if self.verified else "UNVERIFIED"

    @property
    def cost_status(self) -> CostStatus:
        return CostStatus.KNOWN if self.estimated_cost_per_submit is not None else CostStatus.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "supports_first_frame": self.supports_first_frame,
            "supports_last_frame": self.supports_last_frame,
            "max_duration": self.max_duration,
            "max_images": self.max_images,
            "manual_only": self.manual_only,
            "estimated_cost_per_submit": self.estimated_cost_per_submit,
            "last_verified_at": _timestamp_json(self.last_verified_at),
        }


@dataclass(frozen=True, slots=True)
class ProviderRequirements:
    """Minimal explicit provider-consumable requirements for T24."""

    duration: float
    image_count: int
    requires_first_frame: bool = False
    requires_last_frame: bool = False
    execution_mode: ExecutionMode | str = ExecutionMode.AUTOMATED

    def __post_init__(self) -> None:
        object.__setattr__(self, "duration", _finite_real(self.duration, field_name="duration", minimum=0.0, strict_minimum=True))
        object.__setattr__(self, "image_count", _non_negative_int(self.image_count, field_name="image_count"))
        object.__setattr__(self, "requires_first_frame", _strict_bool(self.requires_first_frame, field_name="requires_first_frame"))
        object.__setattr__(self, "requires_last_frame", _strict_bool(self.requires_last_frame, field_name="requires_last_frame"))
        mode = self.execution_mode.value if isinstance(self.execution_mode, ExecutionMode) else self.execution_mode
        if not isinstance(mode, str) or mode not in _EXECUTION_MODES:
            raise CapabilityValidationError("execution_mode must be 'manual' or 'automated'")
        object.__setattr__(self, "execution_mode", ExecutionMode(mode))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProviderRequirements":
        payload = _require_mapping(value, field_name="provider requirements")
        unknown = sorted(set(payload) - set(_REQUIREMENT_FIELDS), key=str)
        if unknown:
            raise CapabilityValidationError(
                f"provider requirements contain unknown fields: {unknown}",
                code="UNKNOWN_REQUIREMENT_FIELDS",
            )
        missing = sorted({"duration", "image_count"} - set(payload), key=str)
        if missing:
            raise CapabilityValidationError(
                f"provider requirements are missing fields: {missing}",
                code="MISSING_REQUIREMENT_FIELDS",
            )
        return cls(**dict(payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration": self.duration,
            "image_count": self.image_count,
            "requires_first_frame": self.requires_first_frame,
            "requires_last_frame": self.requires_last_frame,
            "execution_mode": self.execution_mode.value,
        }


@dataclass(frozen=True, slots=True)
class CompatibilityFinding:
    """One stable, explainable blocker or warning."""

    field: str
    required: Any
    available: Any
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "required": _json_value(self.required),
            "available": _json_value(self.available),
            "reason": self.reason,
        }


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    """Typed, explainable compatibility evaluation output."""

    provider: str
    status: CompatibilityStatus
    verified: bool
    profile_last_verified_at: datetime | None
    requirements: ProviderRequirements | None
    satisfied_constraints: tuple[str, ...] = ()
    blockers: tuple[CompatibilityFinding, ...] = ()
    warnings: tuple[CompatibilityFinding, ...] = ()
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status.value,
            "verified": self.verified,
            "profile_last_verified_at": _timestamp_json(self.profile_last_verified_at),
            "requirements": self.requirements.to_dict() if self.requirements else None,
            "satisfied_constraints": list(self.satisfied_constraints),
            "blockers": [finding.to_dict() for finding in self.blockers],
            "warnings": [finding.to_dict() for finding in self.warnings],
            "reason": self.reason,
        }


def _requirements_or_invalid(value: ProviderRequirements | Mapping[str, Any]) -> ProviderRequirements:
    if isinstance(value, ProviderRequirements):
        return value
    return ProviderRequirements.from_dict(value)


def _invalid_result(provider: Any, reason: str, message: str, requirements: ProviderRequirements | None = None) -> CompatibilityResult:
    return CompatibilityResult(
        provider=str(provider) if provider is not None else "",
        status=CompatibilityStatus.INVALID,
        verified=False,
        profile_last_verified_at=None,
        requirements=requirements,
        blockers=(CompatibilityFinding("input", "valid", message, reason),),
        reason=reason,
    )


def _evaluate_profile(profile: ProviderCapabilityProfile, requirements: ProviderRequirements) -> CompatibilityResult:
    blockers: list[CompatibilityFinding] = []
    satisfied: list[str] = []

    if requirements.execution_mode is ExecutionMode.AUTOMATED and profile.manual_only:
        blockers.append(CompatibilityFinding("manual_only", "automated", True, "automated_execution_not_supported"))
    else:
        satisfied.append("execution_mode")

    if requirements.requires_first_frame:
        if profile.supports_first_frame:
            satisfied.append("supports_first_frame")
        else:
            blockers.append(CompatibilityFinding("supports_first_frame", True, False, "required_first_frame_not_supported"))
    else:
        satisfied.append("first_frame_not_required")

    if requirements.requires_last_frame:
        if profile.supports_last_frame:
            satisfied.append("supports_last_frame")
        else:
            blockers.append(CompatibilityFinding("supports_last_frame", True, False, "required_last_frame_not_supported"))
    else:
        satisfied.append("last_frame_not_required")

    if requirements.duration <= profile.max_duration:
        satisfied.append("duration_within_max")
    else:
        blockers.append(CompatibilityFinding("max_duration", requirements.duration, profile.max_duration, "duration_exceeds_provider_limit"))

    if requirements.image_count <= profile.max_images:
        satisfied.append("image_count_within_max")
    else:
        blockers.append(CompatibilityFinding("max_images", requirements.image_count, profile.max_images, "image_count_exceeds_provider_limit"))

    warnings: list[CompatibilityFinding] = []
    if not profile.verified:
        warnings.append(CompatibilityFinding("last_verified_at", "non-null timestamp", None, "profile_unverified"))

    if blockers:
        status = CompatibilityStatus.INCOMPATIBLE
        reason = "declared_constraints_not_satisfied"
    elif profile.verified:
        status = CompatibilityStatus.COMPATIBLE
        reason = "declared_constraints_satisfied_and_profile_verified"
    else:
        status = CompatibilityStatus.UNVERIFIED
        reason = "declared_constraints_satisfied_but_profile_unverified"

    return CompatibilityResult(
        provider=profile.provider,
        status=status,
        verified=profile.verified,
        profile_last_verified_at=profile.last_verified_at,
        requirements=requirements,
        satisfied_constraints=tuple(satisfied),
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        reason=reason,
    )


class ProviderCapabilityRegistry:
    """Small in-memory registry with fail-closed duplicate handling."""

    def __init__(self, profiles: Iterable[ProviderCapabilityProfile | Mapping[str, Any]] = ()) -> None:
        self._profiles: dict[str, ProviderCapabilityProfile] = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile: ProviderCapabilityProfile | Mapping[str, Any]) -> ProviderCapabilityProfile:
        typed = profile if isinstance(profile, ProviderCapabilityProfile) else ProviderCapabilityProfile.from_dict(profile)
        if typed.provider in self._profiles:
            raise DuplicateProviderError(typed.provider)
        self._profiles[typed.provider] = typed
        return typed

    def get(self, provider: str) -> ProviderCapabilityProfile:
        provider_id = _provider_id(provider)
        try:
            return self._profiles[provider_id]
        except KeyError as exc:
            raise ProfileNotFoundError(provider_id) from exc

    def list(self) -> tuple[ProviderCapabilityProfile, ...]:
        return tuple(self._profiles[key] for key in sorted(self._profiles))

    def evaluate(
        self,
        provider: str,
        requirements: ProviderRequirements | Mapping[str, Any],
    ) -> CompatibilityResult:
        try:
            typed_requirements = _requirements_or_invalid(requirements)
        except CapabilityValidationError as exc:
            return _invalid_result(provider, "invalid_requirements", str(exc))
        try:
            profile = self.get(provider)
        except CapabilityValidationError as exc:
            return _invalid_result(provider, "invalid_provider", str(exc), typed_requirements)
        except ProfileNotFoundError:
            return CompatibilityResult(
                provider=str(provider),
                status=CompatibilityStatus.UNKNOWN,
                verified=False,
                profile_last_verified_at=None,
                requirements=typed_requirements,
                warnings=(CompatibilityFinding("provider", provider, None, "profile_not_found"),),
                reason="profile_not_found",
            )
        return _evaluate_profile(profile, typed_requirements)


def evaluate_compatibility(
    profile: ProviderCapabilityProfile | Mapping[str, Any] | ProviderCapabilityRegistry,
    requirements: ProviderRequirements | Mapping[str, Any],
    *,
    provider: str | None = None,
) -> CompatibilityResult:
    """Evaluate explicit requirements without changing profile or Runtime state."""

    if isinstance(profile, ProviderCapabilityRegistry):
        if provider is None:
            return _invalid_result("", "provider_required_for_registry", "provider is required when evaluating a registry")
        return profile.evaluate(provider, requirements)

    try:
        typed_profile = profile if isinstance(profile, ProviderCapabilityProfile) else ProviderCapabilityProfile.from_dict(profile)
    except (CapabilityValidationError, TypeError) as exc:
        return _invalid_result(provider or "", "invalid_profile", str(exc))
    try:
        typed_requirements = _requirements_or_invalid(requirements)
    except CapabilityValidationError as exc:
        return _invalid_result(typed_profile.provider, "invalid_requirements", str(exc))
    if provider is not None and provider != typed_profile.provider:
        return _invalid_result(provider, "provider_profile_mismatch", "requested provider does not match profile provider", typed_requirements)
    return _evaluate_profile(typed_profile, typed_requirements)


def provider_capability_profile_from_dict(value: Mapping[str, Any]) -> ProviderCapabilityProfile:
    """Named factory for callers loading a static, already-authorized config."""

    return ProviderCapabilityProfile.from_dict(value)


__all__ = [
    "CapabilityValidationError",
    "CompatibilityFinding",
    "CompatibilityResult",
    "CompatibilityStatus",
    "CostStatus",
    "DuplicateProviderError",
    "ExecutionMode",
    "PROFILE_FIELDS",
    "ProfileNotFoundError",
    "ProviderCapabilityProfile",
    "ProviderCapabilityRegistry",
    "ProviderRequirements",
    "evaluate_compatibility",
    "provider_capability_profile_from_dict",
]
