"""Restart-safe, auditable application runtime startup configuration.

The production launcher deliberately does not depend on a user or machine
environment variable.  A successful cutover persists this repository-local
JSON document and every later server process resolves the same configuration
before importing the application runtime.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNTIME_CONFIG_PATH = PROJECT_ROOT / "data" / "runtime-startup.json"
RUNTIME_CONFIG_ENV = "FRAMEFLOW_RUNTIME_CONFIG"
RUNTIME_CONFIG_SCHEMA_VERSION = 1


class RuntimeStartupConfigError(RuntimeError):
    """Raised when a persisted runtime configuration is missing or unsafe."""


@dataclass(frozen=True)
class RuntimeStartupConfig:
    """The complete, persisted ownership decision for one server startup."""

    runtime_mode: str
    runtime_db: str
    legacy_readonly_db: str | None
    production: bool
    generated_by: str
    generated_at: str
    cutover_run_id: str | None = None
    schema_version: int = RUNTIME_CONFIG_SCHEMA_VERSION

    @classmethod
    def build(
        cls,
        *,
        runtime_mode: str,
        runtime_db: Path | str,
        legacy_readonly_db: Path | str | None,
        production: bool,
        generated_by: str,
        cutover_run_id: str | None = None,
    ) -> "RuntimeStartupConfig":
        return cls(
            runtime_mode=str(runtime_mode).strip().lower(),
            runtime_db=str(Path(runtime_db).expanduser().resolve(strict=False)),
            legacy_readonly_db=(
                str(Path(legacy_readonly_db).expanduser().resolve(strict=False))
                if legacy_readonly_db is not None
                else None
            ),
            production=bool(production),
            generated_by=str(generated_by).strip(),
            generated_at=datetime.now(UTC).isoformat(),
            cutover_run_id=str(cutover_run_id).strip() if cutover_run_id else None,
        ).validated()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeStartupConfig":
        try:
            config = cls(
                schema_version=int(payload["schema_version"]),
                runtime_mode=str(payload["runtime_mode"]),
                runtime_db=str(payload["runtime_db"]),
                legacy_readonly_db=(
                    str(payload["legacy_readonly_db"])
                    if payload.get("legacy_readonly_db") is not None
                    else None
                ),
                production=bool(payload["production"]),
                generated_by=str(payload["generated_by"]),
                generated_at=str(payload["generated_at"]),
                cutover_run_id=(
                    str(payload["cutover_run_id"])
                    if payload.get("cutover_run_id") is not None
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeStartupConfigError(
                "runtime startup config is missing a required typed field"
            ) from exc
        return config.validated()

    @classmethod
    def read(cls, path: Path | str) -> "RuntimeStartupConfig":
        resolved = Path(path).expanduser().resolve(strict=False)
        if not resolved.is_file():
            raise RuntimeStartupConfigError(
                f"runtime startup config does not exist: {resolved}"
            )
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeStartupConfigError(
                f"runtime startup config is not readable JSON: {resolved}"
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeStartupConfigError("runtime startup config must be a JSON object")
        return cls.from_dict(payload)

    def validated(self) -> "RuntimeStartupConfig":
        if self.schema_version != RUNTIME_CONFIG_SCHEMA_VERSION:
            raise RuntimeStartupConfigError(
                f"unsupported runtime startup config schema: {self.schema_version}"
            )
        mode = self.runtime_mode.strip().lower()
        if mode not in {"legacy", "v5"}:
            raise RuntimeStartupConfigError("runtime_mode must be 'legacy' or 'v5'")
        runtime_db = Path(self.runtime_db).expanduser()
        if not runtime_db.is_absolute():
            raise RuntimeStartupConfigError("runtime_db must be an absolute path")
        if not self.generated_by.strip() or not self.generated_at.strip():
            raise RuntimeStartupConfigError(
                "generated_by and generated_at are required for auditability"
            )
        if mode == "v5":
            if not self.legacy_readonly_db:
                raise RuntimeStartupConfigError(
                    "V5 runtime startup config requires legacy_readonly_db"
                )
            legacy = Path(self.legacy_readonly_db).expanduser()
            if not legacy.is_absolute():
                raise RuntimeStartupConfigError(
                    "legacy_readonly_db must be an absolute path"
                )
            if runtime_db.resolve(strict=False) == legacy.resolve(strict=False):
                raise RuntimeStartupConfigError(
                    "V5 runtime_db and legacy_readonly_db must be different files"
                )
        elif self.production:
            raise RuntimeStartupConfigError(
                "production=True is reserved for the V5 canonical runtime"
            )
        return self

    def to_environment(self) -> dict[str, str]:
        values = {
            "FRAMEFLOW_RUNTIME_MODE": self.runtime_mode.strip().lower(),
            "FRAMEFLOW_DB_PATH": str(Path(self.runtime_db).resolve(strict=False)),
        }
        if self.runtime_mode.strip().lower() == "v5":
            values["FRAMEFLOW_V5_DB"] = values["FRAMEFLOW_DB_PATH"]
            values["FRAMEFLOW_V5_PRODUCTION"] = "1" if self.production else "0"
            values["FRAMEFLOW_LEGACY_READONLY_DB"] = str(
                Path(self.legacy_readonly_db or "").resolve(strict=False)
            )
        return values

    def as_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n"


def resolve_runtime_config_path(
    environment: Mapping[str, str] | None = None,
) -> tuple[Path, bool]:
    values = os.environ if environment is None else environment
    explicit = str(values.get(RUNTIME_CONFIG_ENV) or "").strip()
    return (
        Path(explicit).expanduser().resolve(strict=False)
        if explicit
        else DEFAULT_RUNTIME_CONFIG_PATH.resolve(strict=False),
        bool(explicit),
    )


def resolve_runtime_environment(
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Resolve persisted configuration, or preserve the legacy env contract.

    A selected config file is authoritative for runtime ownership fields.  If
    no config exists, the pre-cutover environment behavior remains intact.
    Explicit mappings used by unit tests do not implicitly load the production
    default file.
    """

    values = dict(os.environ if environment is None else environment)
    config_path, explicit = resolve_runtime_config_path(values)
    should_load_default = environment is None and config_path.is_file()
    if explicit or should_load_default:
        config = RuntimeStartupConfig.read(config_path)
        values.update(config.to_environment())
        values[RUNTIME_CONFIG_ENV] = str(config_path)
    return values


def write_runtime_startup_config(
    config: RuntimeStartupConfig,
    path: Path | str = DEFAULT_RUNTIME_CONFIG_PATH,
) -> Path:
    """Atomically persist a validated UTF-8 runtime ownership document."""

    config.validated()
    resolved = Path(path).expanduser().resolve(strict=False)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_name(f".{resolved.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(config.as_json(), encoding="utf-8", newline="\n")
        os.replace(temporary, resolved)
    finally:
        if temporary.is_file():
            temporary.unlink()
    return resolved


__all__ = [
    "DEFAULT_RUNTIME_CONFIG_PATH",
    "RUNTIME_CONFIG_ENV",
    "RuntimeStartupConfig",
    "RuntimeStartupConfigError",
    "resolve_runtime_config_path",
    "resolve_runtime_environment",
    "write_runtime_startup_config",
]
