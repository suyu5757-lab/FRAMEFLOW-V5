"""Shared application readiness predicates for Legacy and V5 runtimes.

The V5 runtime does not own the Legacy provider tables. It can still use the
same readiness contract by receiving a read-only projection of provider
profiles and capability bindings from the preserved Legacy archive.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


CAPABILITIES = (
    "orchestrator",
    "vision",
    "image",
    "image_edit",
    "video",
    "tts",
    "music",
    "sfx",
    "upscale",
    "lip_sync",
    "upload",
)
MEDIA_CAPABILITIES = ("image", "video", "tts", "music", "sfx")


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, Mapping) else {}
    return {}


def evaluate_capabilities(
    bindings: Mapping[str, Any],
    profiles: Mapping[str, Any],
    *,
    capabilities: Sequence[str] = CAPABILITIES,
) -> dict[str, dict[str, Any]]:
    """Evaluate each capability using the established Legacy predicates.

    A capability is ready exactly when it has a binding, the bound profile is
    enabled, its last probe reported ``ok=true``, and the bound model is either
    absent from the probe catalog or present in it. This mirrors the existing
    Legacy ``_effective_capabilities`` implementation.
    """

    result: dict[str, dict[str, Any]] = {}
    for capability in capabilities:
        binding = _mapping(bindings.get(capability))
        profile_id = str(binding.get("provider_profile_id") or "")
        profile = _mapping(profiles.get(profile_id)) if profile_id else {}
        health = _mapping(profile.get("last_health"))
        healthy = bool(profile and profile.get("enabled") and health.get("ok") is True)
        model = str(binding.get("model") or "") if binding else ""
        models = [str(item) for item in health.get("models", []) if item]
        model_ready = not model or not models or model in models
        ready = healthy and model_ready
        result[capability] = {
            "ready": ready,
            "status": "ready" if ready else "not_ready",
            "provider_profile_id": profile.get("id") if profile else None,
            "provider": profile.get("display_name") if profile else None,
            "model": model or None,
            "health": health.get("ok") if health else None,
            "reason": None
            if ready
            else ("unbound" if not binding else "provider_unhealthy_or_model_unavailable"),
        }
    return result


def readiness_summary(capabilities: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Return the application-level status and all predicates affecting it."""

    effective = {key: bool(value.get("ready")) for key, value in capabilities.items()}
    orchestrator_ready = effective.get("orchestrator", False)
    media_ready = any(effective.get(key, False) for key in MEDIA_CAPABILITIES)
    status = (
        "ready"
        if orchestrator_ready and media_ready
        else "degraded"
        if orchestrator_ready or media_ready
        else "not_ready"
    )
    predicates = [
        {
            "name": "orchestrator_capability_ready",
            "passed": orchestrator_ready,
            "required": True,
            "details": capabilities.get("orchestrator", {}),
        },
        {
            "name": "media_capability_available",
            "passed": media_ready,
            "required": True,
            "capabilities": list(MEDIA_CAPABILITIES),
            "ready_capabilities": [
                key for key in MEDIA_CAPABILITIES if effective.get(key, False)
            ],
        },
    ]
    return {
        "status": status,
        "ok": status != "not_ready",
        "ready": status == "ready",
        "degraded": status == "degraded",
        "predicates": predicates,
        "failing_predicates": [item["name"] for item in predicates if not item["passed"]],
    }


__all__ = [
    "CAPABILITIES",
    "MEDIA_CAPABILITIES",
    "evaluate_capabilities",
    "readiness_summary",
]
