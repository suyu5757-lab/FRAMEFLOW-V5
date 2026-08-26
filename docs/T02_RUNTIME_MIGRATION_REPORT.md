# FRAMEFLOW V5.3.2

## T02 Runtime Migration Remediation

Audit date: 2026-08-26
Task: T02-R Schema v2.2 + ShotSpec v2.2 + Safe Runtime Migration
Branch: dev/v5.3.2

### 1. Executive Verdict

    T02-R = PASS
    MIGRATION READY = YES
    PRODUCTION CUTOVER = NOT PERFORMED

P0-002 migration mechanism: REMEDIATED.

This task proved a side-by-side V3 to V5 migration using a consistent SQLite backup, a fresh Alembic candidate, explicit data mapping, schema validation, data validation, real online downgrade, backup restore, failure injection, candidate StateStore reads and V3 regression. It did not replace the production database or switch runtime ownership. Seventeen embedded legacy shots remain explicit UNMAPPED review items because BLOCKED, PARTIAL and MISSING are not valid ShotSpec v2.2 statuses.

### 2. Source DB Reality

| Field | Result |
|---|---|
| Path | D:/11067/CodexWorkspaces/frameflow-v3/data/frameflow.db |
| Size | 3657728 bytes before and after |
| Mtime | 2026-08-26T20:01:51.5553533+08:00 |
| SHA before | fccac6a29fa5c91d0ccccdc2545ae1f17010e9349aadd60712401e54d0142cf6 |
| SHA after | fccac6a29fa5c91d0ccccdc2545ae1f17010e9349aadd60712401e54d0142cf6 |
| Unchanged | YES |
| Tables | 41 |
| Schema version | legacy schema_migrations version 16 |
| integrity_check | ok |
| foreign_key_check | 0 violations |
| journal_mode | wal |
| foreign_keys | 0 on raw read-only probe; V3 connection enables it |
| busy_timeout | 5000 |

The source was only opened with SQLite read-only URI or read for fingerprint metadata. No production ALTER, DROP, INSERT, UPDATE, DELETE, VACUUM or Alembic migration was executed.

### 3. Backup Strategy

Implementation: core/migration/backup.py

The source is backed up with sqlite3.Connection.backup(), not by copying only the main DB file. Backup metadata includes source/backup paths, timestamps, source/backup SHA, schema version, table count, integrity result, FK violations, journal mode and busy timeout. Restore refuses a production target and refuses silent backup overwrite.

Real production-copy run:

| Artifact | Path |
|---|---|
| Backup | C:/Users/11067/AppData/Local/Temp/frameflow-t02-prod-5206708be0f940b98f68eda3f33e494c-backup.db |
| Candidate | C:/Users/11067/AppData/Local/Temp/frameflow-t02-prod-5206708be0f940b98f68eda3f33e494c-candidate.db |
| Manifest | C:/Users/11067/AppData/Local/Temp/frameflow-t02-prod-5206708be0f940b98f68eda3f33e494c-manifest.json |
| Backup verification | PASS |
| Backup restore | PASS |
| Backup staged | NO |

### 4. V3 to V5 Mapping

Complete table, column, PK, FK, index, classification and row-count facts are in docs/T02_V3_TO_V5_DATA_MAP.md.

| V3 source | V5 target | Rule |
|---|---|---|
| projects.id/name/document_json/lifecycle_status | projects | Preserve ID; map explicit project fields; record fallbacks |
| document_json.shots[] | sequences/shots | Use existing ShotSpec adapter; preserve IDs; validate every inserted shot |
| document_json.assets[] and asset_versions.logical_asset_id | assets | Preserve logical IDs, version, status, artifact link and LOCKED/approved state |
| artifacts | artifacts | Preserve ID, project, confirmed shot/asset links, path, SHA and task link |
| tasks | tasks | Preserve ID, type, request/result/error and attempts; use explicit status aliases only |
| audit_events_v16, asset_events, timeline_events_v6, workflow_graph_events | events | Derive historical facts; retain original tables in backup |
| provider, generation, QA, recovery and workflow tables without exact target semantics | legacy backup | Archive; do not guess incompatible V5 rows |
| schema_migrations and sqlite_sequence | legacy backup | Legacy-only; not V5 domain tables |

Actual classification:

    MIGRATE      = 3
    DERIVE       = 4
    ARCHIVE_ONLY = 11
    LEGACY_ONLY  = 2
    EMPTY        = 21
    UNKNOWN      = 0

Real row accounting:

    migrated = 61
    derived = 160
    archived = 156
    unmapped = 17 embedded SH rows

### 5. Alembic Online Migration

core/migration/env.py now requires an explicit file-backed candidate from -x db_path=... or DATABASE_URL. core/migration/alembic.ini has no production default. The production path guard rejects data/frameflow.db in both helper and CLI paths.

| Operation | Result |
|---|---|
| Fresh online upgrade head | PASS |
| Alembic version after upgrade | 20260826_01 |
| Real online downgrade base | PASS; 0 V5 domain tables |
| Upgrade after downgrade | PASS; 11 V5 domain tables |
| No explicit candidate | FAIL SAFE, exit 1 |
| Explicit production path | FAIL SAFE, exit 1 |
| Offline SQL with explicit candidate | PASS |

The online env applies WAL, foreign_keys and busy_timeout before the migration transaction. The revision emits PRAGMAs only for offline SQL and uses metadata create/drop for online transactions, so Alembic version bookkeeping remains correct.

### 6. Candidate DB

Candidate domain tables are exactly:

    projects, sequences, shots, assets, artifacts, tasks, events,
    resource_locks, generations, provider_submissions, reviews

Real candidate row counts:

    projects=1 sequences=1 shots=3 assets=26 artifacts=31
    tasks=0 events=160 resource_locks=0 generations=0
    provider_submissions=0 reviews=0

Candidate results:

    domain tables = 11
    integrity_check = ok
    foreign_key_check = no violations
    journal_mode = wal
    foreign_keys = 1
    busy_timeout = 5000
    schema drift = PASS
    candidate StateStore read = PASS

### 7. Schema Validation

Schema comparison covers table set, columns, SQLite types, nullable flags, primary keys, foreign keys and relevant unique indexes against core/schemas/runtime_mvp.py.

### 8. Data Validation

All inserted SH001/SH002/SH003 fixture records validate against ShotSpec v2.2. Real production-copy rows are accounted as migrated, derived, archived or explicit unmapped; no source row is silently discarded.

### 9. Upgrade / Downgrade

The candidate ran real online upgrade head, real downgrade base, and upgrade head again. The Alembic revision row and domain table count were checked after every transition.

### 10. Backup / Restore

PASS cases include:

- SQLite-consistent backup opens read-only and verifies integrity.
- Candidate copy is modified and restored from backup.
- Invalid shot in strict mode rolls back the candidate transaction while source remains unchanged.
- Corrupt input aborts.
- Existing candidate is not silently overwritten.
- Production candidate and production restore targets are blocked.
- Bad foreign key is rejected.
- Added unexpected column is reported as schema drift.
- Dry-run creates no candidate.

Backup restore changed only a candidate copy and restored it from the verified backup. Restore into the production path is rejected.

### 11. Failure Tests

Failure cases passed: invalid strict ShotSpec transaction rollback, corrupt source, existing candidate overwrite, production candidate path, production restore target, bad foreign key, schema drift and dry-run no-write behavior.

### 12. V3 Regression

| Command | Result |
|---|---|
| python -m unittest discover -s tests/schema -p test_*.py -v | exit 0; 10 passed |
| python -m unittest discover -s tests/migration -p test_*.py -v | exit 0; 14 passed |
| python -m unittest discover -s tests/runtime -p test_*.py -v | exit 0; 9 passed; isolated permission profile |
| python -m unittest tests.test_v3 -v | exit 0; 28 passed |

Total:

    passed = 61
    failed = 0
    skipped = 0
    blocked = 0

### 13. Production DB Protection

    SHA BEFORE = fccac6a29fa5c91d0ccccdc2545ae1f17010e9349aadd60712401e54d0142cf6
    SHA AFTER  = fccac6a29fa5c91d0ccccdc2545ae1f17010e9349aadd60712401e54d0142cf6
    UNCHANGED  = YES

No project DB, candidate DB, backup DB, WAL or SHM was staged. No server.py, web/, frameflow/database.py, frameflow/runtime.py or production StateStore ownership was changed.

### 14. Remaining T03-R Cutover Work

- StateStore integration with the application runtime.
- Legacy compatibility bridge for server.py and existing Workbench.
- Resolution of the 17 explicit unmapped legacy shots.
- Atomic production DB cutover and single runtime owner.
- Restart, rollback and production post-cutover verification.
- Retirement of V3 database writes only after all consumers pass.

Production cutover is intentionally NOT PERFORMED.
