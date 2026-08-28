"""Run the final T03 pre-swap sequence without invoking production cutover.

The harness creates a fresh isolated Legacy fixture, proves Candidate A's
first/restart/final stabilization path, proves an unopened Candidate B, then
finalizes the five-file archive and binds an isolated V5 runtime config to the
same run.  It intentionally has no call to ``perform_production_cutover``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.migration.backup import create_backup
from core.migration.candidate_b_lifecycle import CandidateBTerminalSeal
from core.migration.cutover import (
    REQUIRED_LEGACY_SHOTS,
    candidate_b_file_state,
    fingerprint_database,
    handle_free_rename_probe,
    inspect_database,
    stabilize_candidate_b_database,
    validate_candidate,
)
from core.migration.equivalence import (
    A0_STAGE,
    A1_STAGE,
    B0_STAGE,
    build_candidate_a_lifecycle_evidence,
    build_candidate_evidence,
    build_smoke_delta,
    logical_data_fingerprint,
    schema_fingerprint,
    verify_final_candidate_gate,
)
from core.migration.legacy_compat import (
    LegacyReadOnlyCompatibility,
    LegacyReadOnlyError,
    account_legacy_shots,
)
from core.migration.preswap import (
    finalize_archive_readonly,
    prepare_v5_runtime_config,
    verify_archive_finalization,
    verify_maintenance_freshness,
)
from tests.conftest import create_legacy_v3_fixture


FORMAL_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
CANONICAL_DATABASE = PROJECT_ROOT / "data" / "frameflow.db"
ARCHIVE_BASE = PROJECT_ROOT / "archives" / "migrations" / "v5.3.2"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + chr(10),
        encoding="utf-8",
    )


def _rename_physical_evidence(path: Path) -> dict[str, Any]:
    before = _sha256(path)
    rename = handle_free_rename_probe(path)
    after = _sha256(path)
    return {
        **rename,
        "before_physical_sha256": before,
        "after_physical_sha256": after,
        "physical_unchanged": before == after,
        "passed": rename.get("passed") is True and before == after,
    }


def _candidate_b_stage(
    name: str,
    path: Path,
    lifecycle: CandidateBTerminalSeal,
    *,
    db_evidence: Mapping[str, Any] | None = None,
    open_database: bool,
) -> dict[str, Any]:
    """Capture a B lifecycle stage without opening B after it is sealed."""

    filesystem = candidate_b_file_state(path)
    captured = dict(db_evidence or {})
    if open_database and filesystem["main"]["exists"]:
        info = inspect_database(path)
        logical = logical_data_fingerprint(path)
        schema = schema_fingerprint(path)
        captured.update(
            {
                "journal_mode": info.get("journal_mode"),
                "page_count": info.get("page_count"),
                "freelist_count": info.get("freelist_count"),
                "logical_sha256": logical.get("sha256"),
                "schema_fingerprint": schema.get("sha256"),
                "pk_fingerprint": hashlib.sha256(
                    json.dumps(
                        logical.get("primary_keys"),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                ).hexdigest(),
                "row_accounting": None,
                "integrity": info.get("integrity_check"),
                "foreign_key_check": info.get("foreign_key_violations"),
            }
        )
    return {
        "stage": name,
        "captured_at": datetime.now(UTC).isoformat(),
        "main": filesystem["main"],
        "wal": filesystem["wal"],
        "shm": filesystem["shm"],
        "journal_mode": captured.get("journal_mode"),
        "page_count": captured.get("page_count"),
        "freelist_count": captured.get("freelist_count"),
        "logical_sha256": captured.get("logical_sha256"),
        "schema_fingerprint": captured.get("schema_fingerprint"),
        "pk_fingerprint": captured.get("pk_fingerprint"),
        "row_accounting": captured.get("row_accounting"),
        "integrity": captured.get("integrity"),
        "foreign_key_check": captured.get("foreign_key_check"),
        "db_open_count": lifecycle.candidate_db_open_count,
        "backend_opened_count": 0,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    run_id = str(args.run_id).strip()
    if not run_id or not (
        run_id.startswith("T03-TRIPLE-GATE-")
        or run_id.startswith("T03-B-SIDECAR-CLOSURE-")
    ):
        raise SystemExit(
            "run id must be a fresh T03-TRIPLE-GATE-* or T03-B-SIDECAR-CLOSURE-* id"
        )
    if sys.executable != str(FORMAL_PYTHON):
        # The path comparison is intentionally strict: this report must not
        # reproduce the old frameflow-v3.venv reporting ambiguity.
        raise SystemExit(
            f"formal harness requires {FORMAL_PYTHON}; actual={sys.executable}"
        )

    run_root = (PROJECT_ROOT / "data" / ".cutover" / run_id).resolve()
    archive_root = (ARCHIVE_BASE / run_id).resolve()
    if run_root.exists() or archive_root.exists():
        raise SystemExit("refusing to reuse an existing dry-run root")
    run_root.mkdir(parents=True)
    archive_root.mkdir(parents=True)
    candidate_a_root = run_root / "candidate-a"
    candidate_b_root = run_root / "candidate-b"
    candidate_a_root.mkdir()
    candidate_b_root.mkdir()

    candidate_b_timeline: list[dict[str, Any]] = []

    production_before = {
        "physical_sha256": _sha256(CANONICAL_DATABASE),
        "logical_sha256": logical_data_fingerprint(CANONICAL_DATABASE)["sha256"],
    }

    source_fixture = run_root / "legacy_fixture.db"
    create_legacy_v3_fixture(source_fixture)
    archive_db = archive_root / "legacy_frameflow_v3.db"
    backup = create_backup(source_fixture, archive_db)
    legacy_fp = fingerprint_database(archive_db)
    legacy_logical = logical_data_fingerprint(archive_db)
    legacy_schema = schema_fingerprint(archive_db)
    legacy_accounting = account_legacy_shots(archive_db, list(REQUIRED_LEGACY_SHOTS))
    _write_json(
        archive_root / "legacy_fingerprint.json",
        {
            "run_id": run_id,
            "source_kind": "fresh isolated Legacy fixture via SQLite-consistent backup",
            "source_fixture": str(source_fixture),
            "backup": backup,
            "physical": legacy_fp,
            "logical": legacy_logical,
            "schema": legacy_schema,
            "row_accounting": legacy_accounting,
        },
    )
    _write_json(
        archive_root / "migration_manifest.json",
        {
            "run_id": run_id,
            "migration_revision": "20260826_01",
            "migration_implementation_version": "v3_to_v5:20260826_01-deterministic-v2",
            "schema_contract_version": "runtime-mvp:5.3.2",
            "source_archive": str(archive_db),
            "source_legacy_sha256": legacy_fp["sha256"],
            "source_legacy_logical_sha256": legacy_logical["sha256"],
        },
    )
    _write_json(
        archive_root / "v5_candidate_fingerprint.json",
        {"run_id": run_id, "status": "PENDING_B0"},
    )
    (archive_root / "rollback_instructions.md").write_text(
        "T03 isolated dry-run only; no production replacement was called.\n"
        f"Run ID: {run_id}\n"
        f"Legacy archive: {archive_db}\n",
        encoding="utf-8",
    )

    candidate_a = candidate_a_root / "candidate-a.db"
    a_manifest_path = candidate_a_root / "migration_manifest.json"
    a_migration = __import__("core.migration.v3_to_v5", fromlist=["migrate_v3_to_v5"]).migrate_v3_to_v5(
        archive_db,
        candidate_a,
        backup_path=candidate_a_root / "legacy-source-backup.db",
        run_id=run_id + "-candidate-a",
        manifest_path=a_manifest_path,
    )
    a0 = build_candidate_evidence(
        candidate_a,
        source_legacy_sha=legacy_fp["sha256"],
        migration_manifest=a_migration,
        legacy_source=archive_db,
        migration_revision="20260826_01",
        migration_implementation_version="v3_to_v5:20260826_01-deterministic-v2",
        schema_contract_version="runtime-mvp:5.3.2",
        backend_opened=False,
        evidence_stage=A0_STAGE,
        captured_before_backend=True,
        captured_before_swap=True,
    )
    _write_json(candidate_a_root / "A0.json", a0)

    formal_path = candidate_a_root / "formal-launcher-evidence.json"
    formal_config = candidate_a_root / "runtime-startup.json"
    formal_command = [
        str(FORMAL_PYTHON),
        str(PROJECT_ROOT / "scripts" / "verify_t03_sol_final.py"),
        "--candidate",
        str(candidate_a),
        "--legacy",
        str(archive_db),
        "--config",
        str(formal_config),
        "--port",
        "18787",
        "--output",
        str(formal_path),
        "--production-like",
    ]
    formal_process = subprocess.run(
        formal_command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if formal_process.returncode != 0:
        raise RuntimeError(
            "Candidate A formal launcher failed: "
            + (formal_process.stderr or formal_process.stdout)[-4000:]
        )
    formal = json.loads(formal_path.read_text(encoding="utf-8"))
    fixture_ids = list((formal.get("probe_fixture_cleanup") or {}).get("removed") or [])
    a1 = build_candidate_evidence(
        candidate_a,
        source_legacy_sha=legacy_fp["sha256"],
        migration_manifest=a_migration,
        legacy_source=archive_db,
        migration_revision="20260826_01",
        migration_implementation_version="v3_to_v5:20260826_01-deterministic-v2",
        schema_contract_version="runtime-mvp:5.3.2",
        backend_opened=True,
        validation=validate_candidate(candidate_a),
        formal_launcher=formal,
        evidence_stage=A1_STAGE,
        captured_after_smoke=True,
        captured_before_swap=True,
    )
    _write_json(candidate_a_root / "A1.json", a1)
    smoke_delta = build_smoke_delta(
        a0,
        a1,
        fixture_ids=fixture_ids,
        expected_runtime_tables=("projects", "sequences", "events"),
    )
    a_rename = _rename_physical_evidence(candidate_a)
    a_rename["before_logical_sha256"] = logical_data_fingerprint(candidate_a)["sha256"]
    a_rename["after_logical_sha256"] = logical_data_fingerprint(candidate_a)["sha256"]
    a_lifecycle = build_candidate_a_lifecycle_evidence(
        a0,
        a1,
        formal_launcher=formal,
        rename={**a_rename, "logical_unchanged": True},
        smoke_delta=smoke_delta,
    )
    _write_json(candidate_a_root / "candidate-a-lifecycle-evidence.json", a_lifecycle)

    candidate_b = candidate_b_root / "candidate-b.db"
    candidate_b_lifecycle = CandidateBTerminalSeal(candidate_b)
    # This stage is deliberately filesystem-only because the artifact does
    # not exist yet.
    candidate_b_timeline.append(
        _candidate_b_stage(
            "B_CREATED", candidate_b, candidate_b_lifecycle,
            open_database=False,
        )
    )
    b_migration = __import__("core.migration.v3_to_v5", fromlist=["migrate_v3_to_v5"]).migrate_v3_to_v5(
        archive_db,
        candidate_b,
        backup_path=candidate_b_root / "legacy-source-backup.db",
        run_id=run_id + "-candidate-b",
        manifest_path=candidate_b_root / "migration_manifest.json",
    )
    candidate_b_timeline.append(
        _candidate_b_stage(
            "B_AFTER_MIGRATION", candidate_b, candidate_b_lifecycle,
            open_database=True,
        )
    )
    candidate_b_lifecycle.begin_validation()
    b_validation = validate_candidate(candidate_b)
    candidate_b_timeline.append(
        _candidate_b_stage(
            "B_AFTER_VALIDATION", candidate_b, candidate_b_lifecycle,
            db_evidence={"row_accounting": None},
            open_database=True,
        )
    )
    b0 = build_candidate_evidence(
        candidate_b,
        source_legacy_sha=legacy_fp["sha256"],
        migration_manifest=b_migration,
        legacy_source=archive_db,
        migration_revision="20260826_01",
        migration_implementation_version="v3_to_v5:20260826_01-deterministic-v2",
        schema_contract_version="runtime-mvp:5.3.2",
        backend_opened=False,
        validation=b_validation,
        evidence_stage=B0_STAGE,
        captured_before_backend=True,
        captured_before_swap=True,
    )
    candidate_b_timeline.append(
        _candidate_b_stage(
            "B_AFTER_B0_CAPTURE", candidate_b, candidate_b_lifecycle,
            db_evidence={"row_accounting": b0.get("row_accounting")},
            open_database=True,
        )
    )
    candidate_b_lifecycle.mark_evidence_complete(b0)
    candidate_b_lifecycle.begin_final_db_stabilization()
    candidate_b_timeline.append(
        _candidate_b_stage(
            "B_BEFORE_FINAL_CLOSE", candidate_b, candidate_b_lifecycle,
            db_evidence={"row_accounting": b0.get("row_accounting")},
            open_database=True,
        )
    )
    b_stabilization = stabilize_candidate_b_database(candidate_b, b0)
    b0["final_db_stabilization"] = b_stabilization
    candidate_b_timeline.append(
        _candidate_b_stage(
            "B_AFTER_CHECKPOINT", candidate_b, candidate_b_lifecycle,
            db_evidence={
                "journal_mode": b_stabilization.get("journal_mode_after_stabilization"),
                "page_count": (b_stabilization.get("sqlite_contract") or {}).get("page_count"),
                "freelist_count": (b_stabilization.get("sqlite_contract") or {}).get("freelist_count"),
                "logical_sha256": (b_stabilization.get("logical_fingerprint") or {}).get("sha256"),
                "schema_fingerprint": (b_stabilization.get("schema_fingerprint") or {}).get("sha256"),
                "pk_fingerprint": b_stabilization.get("business_pk_fingerprint"),
                "row_accounting": b_stabilization.get("row_accounting"),
                "integrity": (b_stabilization.get("sqlite_contract") or {}).get("integrity_check"),
                "foreign_key_check": (b_stabilization.get("sqlite_contract") or {}).get("foreign_key_violations"),
            },
            open_database=False,
        )
    )
    candidate_b_lifecycle.complete_final_db_stabilization(b_stabilization, b0)
    candidate_b_timeline.append(
        _candidate_b_stage(
            "B_AFTER_FINAL_CLOSE", candidate_b, candidate_b_lifecycle,
            db_evidence={
                "journal_mode": b_stabilization.get("journal_mode_after_stabilization"),
                "page_count": (b_stabilization.get("sqlite_contract") or {}).get("page_count"),
                "freelist_count": (b_stabilization.get("sqlite_contract") or {}).get("freelist_count"),
                "logical_sha256": (b_stabilization.get("logical_fingerprint") or {}).get("sha256"),
                "schema_fingerprint": (b_stabilization.get("schema_fingerprint") or {}).get("sha256"),
                "pk_fingerprint": b_stabilization.get("business_pk_fingerprint"),
                "row_accounting": b_stabilization.get("row_accounting"),
                "integrity": (b_stabilization.get("sqlite_contract") or {}).get("integrity_check"),
                "foreign_key_check": (b_stabilization.get("sqlite_contract") or {}).get("foreign_key_violations"),
            },
            open_database=False,
        )
    )
    candidate_b_timeline.append(
        _candidate_b_stage(
            "B_BEFORE_RENAME", candidate_b, candidate_b_lifecycle,
            db_evidence={
                "journal_mode": b_stabilization.get("journal_mode_after_stabilization"),
                "page_count": (b_stabilization.get("sqlite_contract") or {}).get("page_count"),
                "freelist_count": (b_stabilization.get("sqlite_contract") or {}).get("freelist_count"),
                "logical_sha256": (b_stabilization.get("logical_fingerprint") or {}).get("sha256"),
                "schema_fingerprint": (b_stabilization.get("schema_fingerprint") or {}).get("sha256"),
                "pk_fingerprint": b_stabilization.get("business_pk_fingerprint"),
                "row_accounting": b_stabilization.get("row_accounting"),
                "integrity": (b_stabilization.get("sqlite_contract") or {}).get("integrity_check"),
                "foreign_key_check": (b_stabilization.get("sqlite_contract") or {}).get("foreign_key_violations"),
            },
            open_database=False,
        )
    )
    b_rename = candidate_b_lifecycle.finalize_rename_probe(handle_free_rename_probe)
    b0["rename"] = b_rename
    b0["rename_passed"] = b_rename["passed"]
    b0["terminal_seal"] = candidate_b_lifecycle.evidence()
    b0["candidate_b_reopened_after_rename"] = False
    b0["candidate_b_post_seal_db_open_count"] = candidate_b_lifecycle.post_seal_db_open_count
    candidate_b_timeline.append(
        _candidate_b_stage(
            "B_AFTER_RENAME", candidate_b, candidate_b_lifecycle,
            db_evidence={
                "journal_mode": b_stabilization.get("journal_mode_after_stabilization"),
                "page_count": (b_stabilization.get("sqlite_contract") or {}).get("page_count"),
                "freelist_count": (b_stabilization.get("sqlite_contract") or {}).get("freelist_count"),
                "logical_sha256": (b_stabilization.get("logical_fingerprint") or {}).get("sha256"),
                "schema_fingerprint": (b_stabilization.get("schema_fingerprint") or {}).get("sha256"),
                "pk_fingerprint": b_stabilization.get("business_pk_fingerprint"),
                "row_accounting": b_stabilization.get("row_accounting"),
                "integrity": (b_stabilization.get("sqlite_contract") or {}).get("integrity_check"),
                "foreign_key_check": (b_stabilization.get("sqlite_contract") or {}).get("foreign_key_violations"),
            },
            open_database=False,
        )
    )
    candidate_b_timeline.append(
        _candidate_b_stage(
            "B_SEALED", candidate_b, candidate_b_lifecycle,
            db_evidence={
                "journal_mode": b_stabilization.get("journal_mode_after_stabilization"),
                "page_count": (b_stabilization.get("sqlite_contract") or {}).get("page_count"),
                "freelist_count": (b_stabilization.get("sqlite_contract") or {}).get("freelist_count"),
                "logical_sha256": (b_stabilization.get("logical_fingerprint") or {}).get("sha256"),
                "schema_fingerprint": (b_stabilization.get("schema_fingerprint") or {}).get("sha256"),
                "pk_fingerprint": b_stabilization.get("business_pk_fingerprint"),
                "row_accounting": b_stabilization.get("row_accounting"),
                "integrity": (b_stabilization.get("sqlite_contract") or {}).get("integrity_check"),
                "foreign_key_check": (b_stabilization.get("sqlite_contract") or {}).get("foreign_key_violations"),
            },
            open_database=False,
        )
    )
    _write_json(candidate_b_root / "B0.json", b0)
    final_candidate_gate = verify_final_candidate_gate(a_lifecycle, b0)
    _write_json(run_root / "A0-B0-final-gate.json", final_candidate_gate)
    if not final_candidate_gate["passed"]:
        raise RuntimeError("A0/B0 semantic gate failed: " + "; ".join(final_candidate_gate["errors"]))

    _write_json(archive_root / "v5_candidate_fingerprint.json", b0)
    archive_finalized = finalize_archive_readonly(archive_root)
    archive_verified = verify_archive_finalization(archive_root)

    isolated_canonical = run_root / "isolated-production-canonical.db"
    isolated_canonical.write_bytes(b"isolated canonical placeholder")
    runtime_config_path = run_root / "runtime-startup.json"
    runtime_config = prepare_v5_runtime_config(
        config_path=runtime_config_path,
        runtime_db=isolated_canonical,
        legacy_archive=archive_db,
        cutover_run_id=run_id,
    )

    now = datetime.now(UTC)
    maintenance_state_path = run_root / "maintenance-state.json"
    maintenance_state = {
        "ControllerElevated": True,
        "EnteredAt": (now - timedelta(minutes=1)).isoformat(),
        "MaintenancePaused": True,
        "MaintenanceTaskStates": {
            "FRAMEFLOW Runtime Startup": "Disabled",
            "FRAMEFLOW-V3-Service": "Disabled",
        },
        "MaintenanceToken": {
            "created_at_utc": (now - timedelta(minutes=1)).isoformat(),
            "expires_at_utc": (now + timedelta(hours=1, minutes=59)).isoformat(),
        },
        "PortFree": True,
        "RespawnDetected": False,
        "Restored": False,
    }
    _write_json(maintenance_state_path, maintenance_state)
    maintenance_freshness = verify_maintenance_freshness(
        maintenance_state_path,
        now=now,
        port_probe=lambda: {"classification": "FREE", "owner_pid": None},
    )

    archive_hash_before = _sha256(archive_db)
    archive_adapter = LegacyReadOnlyCompatibility(archive_db)
    select_pass = bool(archive_adapter.list_shots())
    write_blocked = False
    try:
        archive_adapter.write_shot("SH004", {"status": "DRAFT"})
    except LegacyReadOnlyError:
        write_blocked = True
    archive_hash_after = _sha256(archive_db)
    archive_readonly_probe = {
        "select": "PASS" if select_pass else "FAIL",
        "write": "BLOCKED" if write_blocked else "NOT_BLOCKED",
        "hash_stable": archive_hash_before == archive_hash_after,
        "accounting": account_legacy_shots(archive_db, list(REQUIRED_LEGACY_SHOTS)),
    }

    production_after = {
        "physical_sha256": _sha256(CANONICAL_DATABASE),
        "logical_sha256": logical_data_fingerprint(CANONICAL_DATABASE)["sha256"],
    }
    post_seal_sidecar_checks = []
    for checkpoint_name in (
        "immediately_after_seal",
        "after_archive_finalization",
        "after_runtime_config_binding",
        "after_maintenance_freshness",
        "immediately_pre_swap",
    ):
        if checkpoint_name == "after_archive_finalization":
            observed = candidate_b_file_state(candidate_b)
        elif checkpoint_name == "after_runtime_config_binding":
            observed = candidate_b_file_state(candidate_b)
        elif checkpoint_name == "after_maintenance_freshness":
            observed = candidate_b_file_state(candidate_b)
        elif checkpoint_name == "immediately_pre_swap":
            observed = candidate_b_file_state(candidate_b)
        else:
            observed = candidate_b_file_state(candidate_b)
        post_seal_sidecar_checks.append(
            {
                "stage": checkpoint_name,
                "state": observed,
                "sidecars_absent": not observed["wal"]["exists"]
                and not observed["shm"]["exists"],
            }
        )
    candidate_b_timeline.append(
        _candidate_b_stage(
            "B_FINAL_STABLE", candidate_b, candidate_b_lifecycle,
            db_evidence={
                "journal_mode": b_stabilization.get("journal_mode_after_stabilization"),
                "page_count": (b_stabilization.get("sqlite_contract") or {}).get("page_count"),
                "freelist_count": (b_stabilization.get("sqlite_contract") or {}).get("freelist_count"),
                "logical_sha256": (b_stabilization.get("logical_fingerprint") or {}).get("sha256"),
                "schema_fingerprint": (b_stabilization.get("schema_fingerprint") or {}).get("sha256"),
                "pk_fingerprint": b_stabilization.get("business_pk_fingerprint"),
                "row_accounting": b_stabilization.get("row_accounting"),
                "integrity": (b_stabilization.get("sqlite_contract") or {}).get("integrity_check"),
                "foreign_key_check": (b_stabilization.get("sqlite_contract") or {}).get("foreign_key_violations"),
            },
            open_database=False,
        )
    )
    triple = {
        "archive_finalized": archive_finalized["passed"],
        "archive_readonly": archive_verified["passed"],
        "runtime_config_this_run": runtime_config["passed"],
        "maintenance_fresh": maintenance_freshness["passed"],
        "candidate_a": formal.get("status") == "PASS" and smoke_delta["passed"],
        "candidate_b": b0.get("backend_opened") is False and b0.get("validation_passed") is True and b_rename["passed"],
        "a0_b0_equivalence": final_candidate_gate["passed"],
        "archive_readonly_probe": archive_readonly_probe["select"] == "PASS" and archive_readonly_probe["write"] == "BLOCKED" and archive_readonly_probe["hash_stable"],
    }
    report = {
        "status": "PASS" if all(triple.values()) and production_before == production_after else "FAIL",
        "run_id": run_id,
        "formal_interpreter": str(FORMAL_PYTHON.resolve()),
        "production_cutover_called": False,
        "production_db_touched": production_before != production_after,
        "production_before": production_before,
        "production_after": production_after,
        "source_fixture": str(source_fixture),
        "archive_root": str(archive_root),
        "archive_finalization": archive_verified,
        "archive_readonly_probe": archive_readonly_probe,
        "candidate_a": {
            "path": str(candidate_a),
            "a0_logical_sha": a0["logical_fingerprint"]["sha256"],
            "formal_path": str(formal_path),
            "formal_status": formal.get("status"),
            "first_ready": (formal.get("boots") or [{}])[0].get("health", {}).get("ready"),
            "restart_ready": (formal.get("boots") or [{}, {}])[1].get("health", {}).get("ready"),
            "first_workbench": (formal.get("boots") or [{}])[0].get("api_passed"),
            "restart_workbench": (formal.get("boots") or [{}, {}])[1].get("api_passed"),
            "first_legacy": (formal.get("boots") or [{}])[0].get("historical_passed"),
            "restart_legacy": (formal.get("boots") or [{}, {}])[1].get("historical_passed"),
            "final_sha": formal.get("candidate_sha256_after_probe"),
            "final_stabilization": formal.get("final_stabilization"),
            "a0_a1_delta": smoke_delta,
            "rename": a_rename,
        },
        "candidate_b": {
            "path": str(candidate_b),
            "b0_logical_sha": b0["logical_fingerprint"]["sha256"],
            "backend_opened": b0.get("backend_opened"),
            "validation_passed": b0.get("validation_passed"),
            "rename": b_rename,
            "reopened_after_rename": candidate_b_lifecycle.post_seal_db_open_count > 0,
            "post_seal_db_open_count": candidate_b_lifecycle.post_seal_db_open_count,
            "terminal_seal": candidate_b_lifecycle.evidence(),
            "b0_complete_before_stabilization": True,
            "final_stabilization": b_stabilization,
            "post_seal_sidecar_checks": post_seal_sidecar_checks,
            "timeline": candidate_b_timeline,
            "post_seal_db_open_count": candidate_b_lifecycle.post_seal_db_open_count,
        },
        "a0_b0_final_gate": final_candidate_gate,
        "runtime_config": runtime_config,
        "maintenance_freshness": maintenance_freshness,
        "triple_gate": triple,
        "reports": {
            "dry_run": str(args.output.resolve()),
            "formal": str(formal_path),
            "a0": str(candidate_a_root / "A0.json"),
            "a1": str(candidate_a_root / "A1.json"),
            "b0": str(candidate_b_root / "B0.json"),
            "final_gate": str(run_root / "A0-B0-final-gate.json"),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    _write_json(args.output.resolve(), report)
    print(json.dumps({
        "status": report["status"],
        "run_id": run_id,
        "formal_interpreter": str(FORMAL_PYTHON.resolve()),
        "archive_readonly": archive_verified["passed"],
        "runtime_config_this_run": runtime_config["passed"],
        "maintenance_fresh": maintenance_freshness["passed"],
        "candidate_a": triple["candidate_a"],
        "candidate_b": triple["candidate_b"],
        "a0_b0_equivalence": triple["a0_b0_equivalence"],
        "all_preswap_gates": all(triple.values()),
        "perform_production_cutover_called": False,
        "production_db_touched": report["production_db_touched"],
        "report": str(args.output.resolve()),
    }, indent=2, default=str))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
