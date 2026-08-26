"""Fail-safe T03-R StateStore cutover controls.

The default operation is preflight/rehearsal only.  A production replacement
requires the explicit ``production_cutover=True`` argument and a complete
candidate gate.  This module never deletes a database and never overwrites an
existing candidate or archive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from core.runtime.state_store.factory import (
    CANONICAL_DATABASE_PATH,
    inspect_database,
    open_runtime_store,
)

from .backup import create_backup, write_manifest
from .legacy_compat import account_legacy_shots
from .v3_to_v5 import migrate_v3_to_v5
from .validation import validate_candidate


REQUIRED_LEGACY_SHOTS = tuple(f"SH{number:03d}" for number in range(4, 21))


class CutoverBlocked(RuntimeError):
    """Raised when a required T03-R gate is not satisfied."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_database(path: Path | str) -> dict[str, Any]:
    """Return a stable, read-only fingerprint and SQLite health snapshot."""

    resolved = Path(path).expanduser().resolve(strict=False)
    if not resolved.is_file():
        raise CutoverBlocked(f"database does not exist: {resolved}")
    info = inspect_database(resolved)
    stat = resolved.stat()
    return {
        "path": str(resolved),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": _sha256(resolved),
        **info,
    }


def fresh_candidate_from_production(
    *,
    source: Path | str = CANONICAL_DATABASE_PATH,
    work_dir: Path | str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build a fresh candidate and fresh backup from the current source."""

    source_path = Path(source).expanduser().resolve(strict=False)
    token = run_id or f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    root = (
        Path(work_dir).expanduser().resolve(strict=False)
        if work_dir is not None
        else Path(tempfile.gettempdir()) / f"frameflow-t03-{token}"
    )
    root.mkdir(parents=True, exist_ok=True)
    backup_path = root / "legacy-snapshot.db"
    candidate_path = root / "v5-candidate.db"
    manifest_path = root / "migration-manifest.json"
    source_before = fingerprint_database(source_path)
    manifest = migrate_v3_to_v5(
        source_path,
        candidate_path,
        backup_path=backup_path,
        run_id=f"t03-{token}",
        manifest_path=manifest_path,
    )
    accounting = account_legacy_shots(backup_path, list(REQUIRED_LEGACY_SHOTS))
    manifest["t03_legacy_shot_accounting"] = accounting
    manifest["t03_source_fingerprint"] = source_before
    manifest["t03_candidate_fingerprint"] = fingerprint_database(candidate_path)
    manifest["t03_cutover_gate"] = {
        "unaccounted": accounting["unaccounted"],
        "ready": accounting["unaccounted"] == 0 and not validate_candidate(candidate_path)["errors"],
    }
    write_manifest(manifest_path, manifest)
    return {
        "root": str(root),
        "backup_path": str(backup_path),
        "candidate_path": str(candidate_path),
        "manifest_path": str(manifest_path),
        "source_fingerprint": source_before,
        "candidate_fingerprint": manifest["t03_candidate_fingerprint"],
        "legacy_shots": accounting,
        "manifest": manifest,
    }


def create_rollback_snapshot(
    source: Path | str = CANONICAL_DATABASE_PATH,
    archive_root: Path | str | None = None,
) -> dict[str, Any]:
    """Create the permanent pre-cutover evidence set without replacing source."""

    source_path = Path(source).expanduser().resolve(strict=False)
    root = (
        Path(archive_root).expanduser().resolve(strict=False)
        if archive_root is not None
        else Path(tempfile.gettempdir()) / f"frameflow-t03-rollback-{uuid4().hex}"
    )
    root.mkdir(parents=True, exist_ok=True)
    legacy_path = root / "legacy_frameflow_v3.db"
    backup = create_backup(source_path, legacy_path)
    legacy_fingerprint = fingerprint_database(legacy_path)
    candidate_fingerprint = fingerprint_database(source_path)
    (root / "legacy_fingerprint.json").write_text(
        json.dumps(legacy_fingerprint, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (root / "candidate_fingerprint.json").write_text(
        json.dumps(candidate_fingerprint, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    instructions = (
        "T03-R rollback instructions\n"
        "1. Stop only the identified FRAMEFLOW backend.\n"
        "2. Verify the active V5 database is closed and preserve it for review.\n"
        f"3. Restore {legacy_path} to the canonical path with the approved rollback tool.\n"
        "4. Start the legacy application in its documented V3 mode and run the V3 regression.\n"
        "5. Do not write through this archive; LegacyReadOnlyCompatibility is read-only.\n"
    )
    (root / "rollback_instructions.md").write_text(instructions, encoding="utf-8")
    return {
        "archive_root": str(root),
        "legacy_path": str(legacy_path),
        "backup": backup,
        "legacy_fingerprint": legacy_fingerprint,
        "candidate_fingerprint": candidate_fingerprint,
    }


def verify_candidate_gate(
    candidate: Path | str,
    *,
    legacy_source: Path | str,
    required_shots: tuple[str, ...] = REQUIRED_LEGACY_SHOTS,
) -> dict[str, Any]:
    """Verify schema, SQLite health, StateStore ownership and shot accounting."""

    candidate_path = Path(candidate).expanduser().resolve(strict=False)
    if candidate_path == CANONICAL_DATABASE_PATH:
        raise CutoverBlocked("candidate must not be the production path")
    validation = validate_candidate(candidate_path)
    accounting = account_legacy_shots(legacy_source, list(required_shots))
    errors = list(validation.get("errors", []))
    if accounting["unaccounted"]:
        errors.append(f"unaccounted legacy shots: {accounting['unaccounted']}")
    state_store_ok = False
    state_store_pragmas: dict[str, Any] | None = None
    if not errors:
        try:
            with open_runtime_store(candidate_path, candidate=True) as store:
                state_store_pragmas = store.pragmas()
                state_store_ok = True
        except (RuntimeError, OSError) as exc:
            errors.append(f"StateStore open failed: {exc}")
    return {
        "candidate": str(candidate_path),
        "validation": validation,
        "legacy_shots": accounting,
        "state_store_ok": state_store_ok,
        "state_store_pragmas": state_store_pragmas,
        "errors": errors,
        "ready": not errors,
    }


def perform_production_cutover(
    candidate: Path | str,
    *,
    legacy_archive: Path | str,
    legacy_source: Path | str = CANONICAL_DATABASE_PATH,
    production_cutover: bool = False,
    no_active_writer: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Atomically place a verified candidate, only with explicit authorization.

    T03-R currently leaves this function unused because application backend
    integration and restart/rollback rehearsals are not yet proven.  The
    guards remain here so a later operator cannot accidentally run a default
    cutover.
    """

    if not production_cutover:
        raise CutoverBlocked("production replacement requires production_cutover=True")
    candidate_path = Path(candidate).expanduser().resolve(strict=False)
    source_path = Path(legacy_source).expanduser().resolve(strict=False)
    archive_path = Path(legacy_archive).expanduser().resolve(strict=False)
    if source_path != CANONICAL_DATABASE_PATH:
        raise CutoverBlocked("legacy_source must be the canonical production path")
    if candidate_path == CANONICAL_DATABASE_PATH:
        raise CutoverBlocked("candidate path must differ from canonical production path")
    if archive_path.exists():
        raise CutoverBlocked(f"refusing to overwrite rollback archive: {archive_path}")
    if no_active_writer is None or not no_active_writer():
        raise CutoverBlocked("no_active_writer proof is required before production replacement")
    if not candidate_path.is_file():
        raise CutoverBlocked(f"candidate does not exist: {candidate_path}")
    sidecars = (Path(f"{source_path}-wal"), Path(f"{source_path}-shm"))
    if any(sidecar.exists() for sidecar in sidecars):
        raise CutoverBlocked(
            "legacy WAL/SHM sidecars must be checkpointed and verified absent before replacement"
        )
    before = fingerprint_database(source_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source_path), str(archive_path))
    try:
        os.replace(candidate_path, source_path)
    except Exception:
        # Restore the original path on the same-volume replacement failure.
        os.replace(archive_path, source_path)
        raise
    after = fingerprint_database(source_path)
    return {"before": before, "after": after, "legacy_archive": str(archive_path)}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--production-cutover", action="store_true")
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--legacy-source", type=Path, default=CANONICAL_DATABASE_PATH)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.production_cutover:
        raise SystemExit(
            "T03-R production replacement requires an application-controlled writer proof; "
            "invoke perform_production_cutover from a reviewed operator harness."
        )
    if not args.preflight:
        print("SAFE DEFAULT: no cutover performed; pass --preflight for inspection.")
        return 0
    if args.candidate is None:
        raise SystemExit("--preflight requires --candidate")
    result = verify_candidate_gate(args.candidate, legacy_source=args.legacy_source)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
