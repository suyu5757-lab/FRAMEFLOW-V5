# FRAMEFLOW V5.3.2 — T03-R Runtime DB Ownership Audit

Audit date: 2026-08-26
Branch: `dev/v5.3.2`
HEAD at audit: `5baf76344184841ef56ddde9dd020e45842f43d8`
Canonical production path: `D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db`

## Verdict

**T03-R ownership gate: PARTIAL / BLOCKED.**

The V5 `StateStore` factory, V5 schema detection, and a read-only legacy
compatibility adapter are present. The existing production application is not
yet routed through that factory. `server.py` still constructs the V3
`frameflow.database.Database`, whose startup and endpoint helpers expect V3
tables and can write the legacy database. Therefore `INVALID_DIRECT_ACCESS`
is not zero and production replacement was not attempted.

There is no dual write: only the existing V3 application was running against
the legacy database, and the isolated V5 candidate was never placed at the
canonical path. There is also no dual source of truth because no cutover took
place; the current source of truth remains V3.

## Source facts

The production file was opened with SQLite read-only URI mode for this audit.

| Check | Result |
|---|---|
| Path | `D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db` |
| Size | 3,657,728 bytes |
| SHA-256 | `fccac6a29fa5c91d0ccccdc2545ae1f17010e9349aadd60712401e54d0142cf6` |
| Tables | 41 legacy V3 tables |
| Schema marker | `schema_migrations` version 16 |
| Journal mode | `wal` |
| Raw connection foreign keys | `0` (V3 `Database.connect()` enables it per connection) |
| Busy timeout | `5000` |
| Integrity check | `ok` |
| Foreign-key check | 0 violations |
| Source changed during audit | NO |

The current project document contains `SH001` through `SH020`. A fresh
side-by-side candidate was generated in a temporary directory. The candidate
had the exact 11 V5 domain tables, opened through `StateStore`, and passed
`journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`, integrity, and FK
checks. The source file remained unchanged.

## Call-point classification

Classification is based on the actual source scan for `sqlite3.connect`,
`create_engine`, `Database(`, `StateStore(`, `frameflow.db`, and imports of
`frameflow.database`.

| Call point | Classification | Evidence / boundary |
|---|---|---|
| `core/runtime/state_store/store.py:69` (`create_engine`) | `V5_RUNTIME` | V5 StateStore implementation; production opening is now intended to occur through `factory.py` only. |
| `core/runtime/state_store/factory.py` | `V5_RUNTIME` | Resolves the canonical path, detects schema, refuses legacy writable ownership, and verifies PRAGMAs. |
| `core/migration/env.py:76` (`create_engine`) | `MIGRATION_ONLY` | Explicit non-production Alembic candidate; production path is rejected. |
| `core/migration/backup.py` | `MIGRATION_ONLY` | Source is read-only; destination is a non-production backup/candidate. |
| `core/migration/v3_to_v5.py` | `MIGRATION_ONLY` | Legacy source is read-only; V5 output is a fresh side-by-side candidate. |
| `core/migration/validation.py` | `MIGRATION_ONLY` | Candidate is opened read-only for schema/data validation. |
| `core/migration/legacy_compat.py` | `LEGACY_READ_ONLY` | Every connection uses `mode=ro`; all write methods raise `LegacyReadOnlyError`. |
| `server.py:45,201,300+` | `INVALID_DIRECT_ACCESS` | Imports and constructs V3 `Database`; startup calls `seed_defaults`, backup, and V3 resume paths. |
| `frameflow/database.py:1002-1060` | `INVALID_DIRECT_ACCESS` | `Database.__init__` creates/migrates the supplied path; `connect()` is writable. |
| `frameflow/recovery.py:96` | `INVALID_DIRECT_ACCESS` | Runtime recovery backup path uses the legacy `Database` and V3 backup tables. |
| `tests/**` | `TEST_ONLY` | Direct database use is isolated to V3 regression, migration, and fixture tests. |

`server.py` also performs many direct SQL reads/writes through its `Database`
object. The scan found V3-only tables including `provider_profiles`,
`capability_bindings`, `workflow_runs_v3`, `render_jobs_v6`, and
`audit_events_v16`. These are not present in the 11-table candidate, so the
current backend cannot be pointed at a V5 candidate without an application
adapter and a route-by-route persistence migration.

## Single-owner policy

The required end state is:

```text
server/backend
    -> core.runtime.state_store.factory.open_runtime_store()
        -> StateStore
            -> canonical data/frameflow.db (V5 only)

historical SH004..SH020
    -> LegacyReadOnlyCompatibility(mode=ro)
        -> protected legacy archive only
```

The factory refuses a legacy or mixed schema before opening it for writes. The
legacy adapter has no update/delete/execute-write API. Migration, backup,
validation, and tests may access non-production candidates explicitly; they
are not application runtime ownership.

## Required closure before production cutover

1. Replace the `server.py` V3 startup boundary with the factory and a tested
   V5 application persistence adapter.
2. Migrate or explicitly retire each V3 endpoint that currently assumes a
   V3-only table; no endpoint may silently write the legacy archive.
3. Run backend startup, Workbench read/write smoke, restart persistence, and
   transaction rollback against a fresh V5 candidate.
4. Stop only the identified FRAMEFLOW writer, create the permanent rollback
   snapshot, re-run the fresh candidate gate, and obtain `INVALID_DIRECT_ACCESS=0`.
5. Only then use the explicit `production_cutover=True` operation. Its default
   CLI path is a no-op/inspection path.
