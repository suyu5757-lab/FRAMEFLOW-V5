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
import sqlite3
import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from core.runtime.state_store.factory import (
    CANONICAL_DATABASE_PATH,
    inspect_database,
    open_runtime_store,
)
from core.runtime.persistence.startup_config import (
    DEFAULT_RUNTIME_CONFIG_PATH,
    RuntimeStartupConfig,
    RuntimeStartupConfigError,
    write_runtime_startup_config,
)
from core.migration.production_environment import (
    ProductionEnvironmentError,
    verify_formal_launcher_evidence,
    verify_production_interpreter,
)

from .backup import create_backup, write_manifest
from .equivalence import (
    MIGRATION_IMPLEMENTATION_VERSION,
    MIGRATION_REVISION,
    SCHEMA_CONTRACT_VERSION,
    build_candidate_evidence,
    logical_data_fingerprint,
    schema_fingerprint,
    verify_candidate_equivalence,
    verify_final_candidate_gate,
)
from .legacy_compat import account_legacy_shots, inspect_legacy_archive
from .port_ownership import (
    PortOwnershipError,
    assert_exclusive_port_evidence,
    assert_live_port_free,
)
from .v3_to_v5 import migrate_v3_to_v5
from .validation import validate_candidate


REQUIRED_LEGACY_SHOTS = tuple(f"SH{number:03d}" for number in range(4, 21))
PROJECT_ROOT = CANONICAL_DATABASE_PATH.parent.parent
DEFAULT_CUTOVER_STAGING_ROOT = CANONICAL_DATABASE_PATH.parent / ".cutover"
DEFAULT_ARCHIVE_ROOT = PROJECT_ROOT / "archives" / "migrations" / "v5.3.2"
RENAME_PROBE_RETRY_SECONDS = 2.0
RENAME_PROBE_RETRY_INTERVAL_SECONDS = 0.05


class CutoverBlocked(RuntimeError):
    """Raised when a required T03-R gate is not satisfied."""


def volume_key(path: Path | str) -> str:
    """Return a stable volume identity for an existing or planned path."""

    resolved = Path(path).expanduser().resolve(strict=False)
    if resolved.drive:
        return resolved.drive.rstrip("\\/").upper()
    try:
        return f"st_dev:{resolved.stat().st_dev}"
    except FileNotFoundError:
        return f"st_dev:{resolved.parent.stat().st_dev}"


def cutover_path_info(
    candidate: Path | str,
    production: Path | str = CANONICAL_DATABASE_PATH,
    legacy_archive: Path | str | None = None,
) -> dict[str, Any]:
    """Describe the volumes used by a planned atomic replacement."""

    candidate_path = Path(candidate).expanduser().resolve(strict=False)
    production_path = Path(production).expanduser().resolve(strict=False)
    archive_path = (
        Path(legacy_archive).expanduser().resolve(strict=False)
        if legacy_archive is not None
        else None
    )
    candidate_volume = volume_key(candidate_path)
    production_volume = volume_key(production_path)
    archive_volume = volume_key(archive_path) if archive_path is not None else None
    volumes = [candidate_volume, production_volume]
    if archive_volume is not None:
        volumes.append(archive_volume)
    return {
        "candidate": str(candidate_path),
        "production": str(production_path),
        "legacy_archive": str(archive_path) if archive_path is not None else None,
        "candidate_volume": candidate_volume,
        "production_volume": production_volume,
        "archive_volume": archive_volume,
        "same_volume": len(set(volumes)) == 1,
    }


def default_cutover_staging_root() -> Path:
    """Return the explicit same-volume staging root for production cutover."""

    return DEFAULT_CUTOVER_STAGING_ROOT


def handle_free_rename_probe(path: Path | str) -> dict[str, Any]:
    """Rename a closed candidate away and back to prove Windows can release it."""

    resolved = Path(path).expanduser().resolve(strict=False)
    if not resolved.is_file():
        raise CutoverBlocked(f"rename probe target does not exist: {resolved}")
    probe = resolved.with_name(f"{resolved.stem}.rename_probe{resolved.suffix}")
    if probe.exists():
        raise CutoverBlocked(f"rename probe target already exists: {probe}")

    def replace_with_release_wait(source: Path, destination: Path) -> None:
        deadline = time.monotonic() + RENAME_PROBE_RETRY_SECONDS
        while True:
            try:
                os.replace(source, destination)
                return
            except PermissionError as exc:
                # Windows can signal process exit before SQLite's last file
                # handle has become renameable.  Wait only for that specific
                # transient condition; a persistent lock still fails closed.
                if getattr(exc, "winerror", None) != 32 or time.monotonic() >= deadline:
                    raise
                time.sleep(RENAME_PROBE_RETRY_INTERVAL_SECONDS)

    try:
        replace_with_release_wait(resolved, probe)
        replace_with_release_wait(probe, resolved)
    except Exception:
        # Restore the original name if the second rename is the failing side.
        if probe.exists() and not resolved.exists():
            replace_with_release_wait(probe, resolved)
        raise
    return {"path": str(resolved), "probe": str(probe), "passed": True}


def checkpoint_database(path: Path | str) -> dict[str, Any]:
    """Checkpoint a closed-file candidate with an explicit connection close."""

    resolved = Path(path).expanduser().resolve(strict=False)
    if not resolved.is_file():
        raise CutoverBlocked(f"checkpoint target does not exist: {resolved}")
    connection = sqlite3.connect(str(resolved), timeout=5)
    try:
        connection.execute("PRAGMA busy_timeout=5000")
        checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        connection.commit()
        return {"path": str(resolved), "checkpoint": checkpoint, "integrity_check": integrity}
    finally:
        connection.close()


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
    staging_root: Path | str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build a fresh candidate and backup in an explicit staging directory.

    When no ``work_dir`` is supplied, production callers are kept off the
    process TEMP directory and use ``data/.cutover/<run_id>`` on the same
    volume as the canonical database.  Tests and rehearsals may still pass an
    explicit ``work_dir``.
    """

    source_path = Path(source).expanduser().resolve(strict=False)
    token = run_id or f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    if work_dir is not None:
        root = Path(work_dir).expanduser().resolve(strict=False)
    else:
        base = (
            Path(staging_root).expanduser().resolve(strict=False)
            if staging_root is not None
            else DEFAULT_CUTOVER_STAGING_ROOT
        )
        root = base / token
    if source_path == CANONICAL_DATABASE_PATH and work_dir is None:
        path_info = cutover_path_info(root, source_path)
        if not path_info["same_volume"]:
            raise CutoverBlocked(
                "same-volume staging is required for production candidate: "
                f"{path_info}"
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
    manifest["source_legacy_sha"] = source_before["sha256"]
    manifest["migration_revision"] = MIGRATION_REVISION
    manifest["migration_implementation_version"] = MIGRATION_IMPLEMENTATION_VERSION
    manifest["schema_contract_version"] = SCHEMA_CONTRACT_VERSION
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
    candidate: Path | str | None = None,
    *,
    legacy_source: Path | str,
    required_shots: tuple[str, ...] = REQUIRED_LEGACY_SHOTS,
    candidate_a_evidence: dict[str, Any] | None = None,
    candidate_b_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify either the legacy single-candidate gate or the final A/B gate.

    The legacy call shape remains available for existing rehearsal callers.
    Final cutover callers must provide both evidence mappings, which keeps the
    formal launcher proof on Candidate A and the closed-file swap proof on B.
    """

    if candidate_a_evidence is not None or candidate_b_evidence is not None:
        if candidate_a_evidence is None or candidate_b_evidence is None:
            raise CutoverBlocked("Candidate A and Candidate B evidence are both required")
        result = verify_final_candidate_gate(candidate_a_evidence, candidate_b_evidence)
        return {
            "candidate_model": "A_SMOKE+B_SWAP",
            "candidate_a": candidate_a_evidence.get("candidate"),
            "candidate_b": candidate_b_evidence.get("candidate"),
            "equivalence": result,
            "errors": result["errors"],
            "ready": result["ready"],
        }

    if candidate is None:
        raise CutoverBlocked("candidate is required for the legacy candidate gate")

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
    candidate_handle_free: bool = False,
    legacy_archive_verified: bool = False,
    runtime_config_path: Path | str = DEFAULT_RUNTIME_CONFIG_PATH,
    cutover_run_id: str | None = None,
    formal_launcher_evidence: dict[str, Any] | None = None,
    port_ownership_evidence: Mapping[str, Any] | None = None,
    port_ownership_probe: Callable[[], Mapping[str, Any]] | None = None,
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
    path_info = cutover_path_info(candidate_path, source_path, archive_path)
    if not path_info["same_volume"]:
        raise CutoverBlocked(
            "same-volume guard failed before any move or replace: "
            f"{path_info}"
        )
    try:
        verify_production_interpreter()
        launcher_candidate = candidate_path
        launcher_archive = archive_path
        if isinstance(formal_launcher_evidence, dict) and (
            "candidate_a_evidence" in formal_launcher_evidence
            or "candidate_b_evidence" in formal_launcher_evidence
        ):
            candidate_a_evidence = formal_launcher_evidence.get("candidate_a_evidence")
            candidate_b_evidence = formal_launcher_evidence.get("candidate_b_evidence")
            if not isinstance(candidate_a_evidence, dict) or not isinstance(candidate_b_evidence, dict):
                raise CutoverBlocked(
                    "final A/B candidate evidence must include both mapping payloads"
                )
            launcher_candidate = Path(
                str(candidate_a_evidence.get("candidate") or "")
            ).expanduser().resolve(strict=False)
            swap_evidence_candidate = Path(
                str(candidate_b_evidence.get("candidate") or "")
            ).expanduser().resolve(strict=False)
            if swap_evidence_candidate != candidate_path:
                raise CutoverBlocked("Candidate B evidence does not name the swap candidate")
            if candidate_b_evidence.get("backend_opened") is not False:
                raise CutoverBlocked("Candidate B backend-opened must be NO")
            final_gate = verify_final_candidate_gate(
                candidate_a_evidence, candidate_b_evidence
            )
            if not final_gate["ready"]:
                raise CutoverBlocked(
                    "final A/B candidate equivalence gate failed: "
                    + "; ".join(final_gate["errors"])
                )
        verify_formal_launcher_evidence(
            formal_launcher_evidence,
            candidate=launcher_candidate,
            legacy_archive=launcher_archive,
        )
    except ProductionEnvironmentError as exc:
        raise CutoverBlocked(f"formal launcher pre-swap gate failed: {exc}") from exc
    try:
        assert_exclusive_port_evidence(port_ownership_evidence)
        if port_ownership_probe is None:
            raise PortOwnershipError("a live production port probe is required")
        initial_port_observation = dict(port_ownership_probe())
        assert_live_port_free(initial_port_observation)
    except PortOwnershipError as exc:
        raise CutoverBlocked(f"exclusive production port gate failed: {exc}") from exc
    if not candidate_handle_free:
        raise CutoverBlocked("candidate handle-free rename proof is required before production replacement")
    archive_precreated = archive_path.exists()
    if archive_precreated and not legacy_archive_verified:
        raise CutoverBlocked(f"refusing to overwrite rollback archive: {archive_path}")
    if legacy_archive_verified and not archive_precreated:
        raise CutoverBlocked(
            f"verified rollback archive is missing before replacement: {archive_path}"
        )
    try:
        legacy_validation = inspect_legacy_archive(
            archive_path if archive_precreated else source_path
        )
    except Exception as exc:
        raise CutoverBlocked(f"legacy archive validation failed: {exc}") from exc
    if no_active_writer is None or not no_active_writer():
        raise CutoverBlocked("no_active_writer proof is required before production replacement")
    try:
        immediate_port_observation = dict(port_ownership_probe())
        assert_live_port_free(immediate_port_observation)
    except PortOwnershipError as exc:
        raise CutoverBlocked(
            f"production port changed before atomic replacement: {exc}"
        ) from exc
    if not candidate_path.is_file():
        raise CutoverBlocked(f"candidate does not exist: {candidate_path}")
    sidecars = (Path(f"{source_path}-wal"), Path(f"{source_path}-shm"))
    if any(sidecar.exists() for sidecar in sidecars):
        raise CutoverBlocked(
            "legacy WAL/SHM sidecars must be checkpointed and verified absent before replacement"
        )
    # Do not reopen SQLite after the sidecar gate.  The source has already
    # been inspected by the caller; opening a legacy WAL database read-only
    # can recreate ``-shm`` on some SQLite builds between the gate and move.
    before = {
        "path": str(source_path),
        "size": source_path.stat().st_size,
        "mtime_ns": source_path.stat().st_mtime_ns,
        "sha256": _sha256(source_path),
    }
    config_path = Path(runtime_config_path).expanduser().resolve(strict=False)
    prior_config = None
    if config_path.is_file():
        try:
            prior_config = RuntimeStartupConfig.read(config_path)
        except RuntimeStartupConfigError as exc:
            raise CutoverBlocked(
                f"existing runtime startup config is invalid: {config_path}: {exc}"
            ) from exc
    v5_config = RuntimeStartupConfig.build(
        runtime_mode="v5",
        runtime_db=source_path,
        legacy_readonly_db=archive_path,
        production=True,
        generated_by="core.migration.cutover.perform_production_cutover",
        cutover_run_id=cutover_run_id,
    )
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    moved_source = False
    try:
        # Persist the fail-closed startup decision before the database move.
        # A crash in the narrow interval can only make V5 startup reject the
        # still-legacy canonical DB; it cannot reopen it through writable V3.
        write_runtime_startup_config(v5_config, config_path)
        if not archive_precreated:
            shutil.move(str(source_path), str(archive_path))
            moved_source = True
        os.replace(candidate_path, source_path)
    except Exception:
        # Restore only when this operation moved the original source away.
        # A pre-created verified archive remains intact for rollback review.
        if moved_source:
            os.replace(archive_path, source_path)
        if prior_config is not None:
            write_runtime_startup_config(prior_config, config_path)
        elif config_path.is_file():
            config_path.unlink()
        raise
    after = fingerprint_database(source_path)
    return {
        "before": before,
        "after": after,
        "legacy_archive": str(archive_path),
        "path_info": path_info,
        "legacy_archive_precreated": archive_precreated,
        "legacy_archive_validation": legacy_validation,
        "runtime_config": str(config_path),
        "runtime_config_payload": json.loads(v5_config.as_json()),
        "port_ownership": {
            "maintenance_evidence": dict(port_ownership_evidence),
            "initial_live": initial_port_observation,
            "immediate_pre_swap": immediate_port_observation,
        },
    }


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
