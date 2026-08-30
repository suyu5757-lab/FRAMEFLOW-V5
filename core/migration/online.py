"""Explicit-candidate Alembic operations for T02-R."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from .candidate_b_lifecycle import assert_candidate_b_database_open_allowed
from .backup import PRODUCTION_DATABASE, BackupError, create_backup, verify_backup


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = PROJECT_ROOT / "core" / "migration" / "alembic.ini"


def _candidate(path: Path | str) -> Path:
    candidate = Path(path).expanduser().resolve(strict=False)
    assert_candidate_b_database_open_allowed(candidate)
    if candidate == PRODUCTION_DATABASE:
        raise BackupError(
            f"T02-R refuses to migrate production: {PRODUCTION_DATABASE}; "
            "cutover is deferred to T03-R"
        )
    if candidate.name in {"", "."} or str(candidate) == ".":
        raise BackupError("an explicit file-backed candidate path is required")
    return candidate


def _config(path: Path | str) -> Config:
    candidate = _candidate(path)
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{candidate.as_posix()}")
    return config


def upgrade_candidate(path: Path | str, revision: str = "head") -> Path:
    """Run a real online Alembic upgrade against a non-production file."""

    candidate = _candidate(path)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    if candidate.exists() and candidate.is_dir():
        raise BackupError(f"candidate path is a directory, not a database file: {candidate}")
    command.upgrade(_config(candidate), revision)
    return candidate


def downgrade_candidate(path: Path | str, revision: str = "base") -> Path:
    """Run a real online Alembic downgrade against a non-production file."""

    candidate = _candidate(path)
    if not candidate.is_file():
        raise BackupError(f"candidate database does not exist: {candidate}")
    command.downgrade(_config(candidate), revision)
    return candidate


def _production_config(path: Path | str) -> Config:
    target = Path(path).expanduser().resolve(strict=False)
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{target.as_posix()}")
    # env.py accepts this only through the reviewed production entry point.
    config.attributes["frameflow_allow_production_migration"] = True
    return config


def upgrade_production(
    path: Path | str = PRODUCTION_DATABASE,
    *,
    backup_path: Path | str,
    revision: str = "head",
) -> dict[str, object]:
    """Back up and upgrade the canonical V5 database through Alembic.

    The backup is mandatory and is created before Alembic opens the writable
    production target. This is separate from candidate migration helpers and
    never creates fixtures or performs a downgrade.
    """

    target = Path(path).expanduser().resolve(strict=False)
    if target != PRODUCTION_DATABASE:
        raise BackupError(
            f"production upgrade requires the canonical database: {PRODUCTION_DATABASE}"
        )
    if not target.is_file():
        raise BackupError(f"production database does not exist: {target}")
    backup = create_backup(target, backup_path)
    verified_backup = verify_backup(backup["backup_path"])
    if verified_backup["integrity_check"] != "ok" or verified_backup["foreign_key_violations"]:
        raise BackupError(f"refusing production upgrade from invalid backup: {verified_backup}")
    command.upgrade(_production_config(target), revision)
    return {"target_path": str(target), "revision": revision, "backup": verified_backup}
