"""Formal configuration contract for T04 archive retention."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RETENTION_CONFIG_PATH = PROJECT_ROOT / "config" / "runtime-retention.json"


class RetentionConfigError(RuntimeError):
    """Raised when the formal archive retention configuration is unsafe."""


@dataclass(frozen=True)
class ArchiveRetentionConfig:
    max_archive_size_gb: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ArchiveRetentionConfig":
        if "max_archive_size_gb" not in payload:
            raise RetentionConfigError(
                "RETENTION_CONFIG_MISSING: max_archive_size_gb is required"
            )
        value = payload["max_archive_size_gb"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RetentionConfigError(
                "RETENTION_CONFIG_INVALID: max_archive_size_gb must be numeric"
            )
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise RetentionConfigError(
                "RETENTION_CONFIG_INVALID: max_archive_size_gb must be finite and greater than zero"
            )
        return cls(max_archive_size_gb=value)

    @classmethod
    def read(cls, path: Path | str = DEFAULT_RETENTION_CONFIG_PATH) -> "ArchiveRetentionConfig":
        resolved = Path(path).expanduser().resolve(strict=False)
        if not resolved.is_file():
            raise RetentionConfigError(f"RETENTION_CONFIG_MISSING: {resolved}")
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RetentionConfigError(f"RETENTION_CONFIG_INVALID: {resolved}") from exc
        if not isinstance(payload, dict):
            raise RetentionConfigError("RETENTION_CONFIG_INVALID: root must be a JSON object")
        return cls.from_mapping(payload)


__all__ = [
    "ArchiveRetentionConfig",
    "DEFAULT_RETENTION_CONFIG_PATH",
    "RetentionConfigError",
]
