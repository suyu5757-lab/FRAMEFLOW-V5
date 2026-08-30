"""Canonical hashing and deterministic identity for T09 submissions."""

from __future__ import annotations

import hashlib
from typing import Any

from frameflow.idempotency import canonical_json


IDEMPOTENCY_KEY_FIELDS = (
    "project_id",
    "shot_id",
    "package_version",
    "shot_spec_version",
    "provider",
    "provider_config_hash",
)


def _text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def provider_config_hash(provider_config: Any) -> str:
    """Hash provider behavior configuration using the shared canonical JSON helper."""

    return _sha256(provider_config)


def request_hash(request_payload: Any) -> str:
    """Hash only the canonical Provider Submit request payload."""

    return _sha256(request_payload)


def idempotency_key(
    *,
    project_id: str,
    shot_id: str,
    package_version: str,
    shot_spec_version: str,
    provider: str,
    provider_config_hash: str,
) -> str:
    """Build an auditable, deterministic logical-submit identity.

    The canonical JSON envelope keeps every required identity component
    visible in the persisted key while avoiding delimiter escaping issues.
    """

    identity = {
        "project_id": _text(project_id, field="project_id"),
        "shot_id": _text(shot_id, field="shot_id"),
        "package_version": _text(package_version, field="package_version"),
        "shot_spec_version": _text(shot_spec_version, field="shot_spec_version"),
        "provider": _text(provider, field="provider"),
        "provider_config_hash": _text(
            provider_config_hash,
            field="provider_config_hash",
        ),
    }
    return f"provider-submit:{canonical_json(identity)}"


__all__ = [
    "IDEMPOTENCY_KEY_FIELDS",
    "canonical_json",
    "idempotency_key",
    "provider_config_hash",
    "request_hash",
]
