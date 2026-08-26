"""Explicit-candidate Alembic operations for T02-R."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from .backup import PRODUCTION_DATABASE, BackupError


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = PROJECT_ROOT / "core" / "migration" / "alembic.ini"


def _candidate(path: Path | str) -> Path:
    candidate = Path(path).expanduser().resolve(strict=False)
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
