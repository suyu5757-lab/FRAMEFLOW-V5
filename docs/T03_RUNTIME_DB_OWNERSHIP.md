# FRAMEFLOW V5.3.2 — T03-R Runtime DB Ownership Audit

Audit date: 2026-08-27
Branch: `dev/v5.3.2`
HEAD at audit: `46cba108d0ce54eebc4d95ae5309e95900c275bd`
Canonical production path: `D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db`

## Verdict

**T03-R3E final cutover: ROLLED_BACK. Current runtime source of truth: LEGACY_V3.**

The one authorized R3E atomic replacement completed, but the post-cutover
legacy compatibility gate failed because the V5 production process was started
without `FRAMEFLOW_LEGACY_READONLY_DB`. The V5 database was preserved for
diagnosis, the permanent Legacy archive remains in place, and the canonical
path was atomically restored from that archive. No second cutover was attempted.

The V5 `StateStore` factory, `RuntimePersistence` facade, explicit `v5` mode,
and read-only legacy compatibility adapter are present. In V5 mode, the
application startup and P0 API gateway use the facade; old V3 handlers are
not dispatched and return an explicit out-of-scope response. Therefore
`INVALID_DIRECT_ACCESS=0` for V5 runtime reachability.

The current production runtime is again `FRAMEFLOW_RUNTIME_MODE=legacy`; the
legacy branch owns the canonical V3 file after rollback. The V5 branch is not
the active production runtime, and the Legacy writable runtime has not been
disabled because the R3E cutover did not pass its post-cutover gates.

There is no dual write or dual source of truth after rollback: the Legacy V3
runtime is the sole active writable source, while the archived Legacy snapshot
is read-only. The failed V5 production database is preserved outside the
active runtime for diagnosis only.

## R3E rollback evidence

The complete attempt and gate results are recorded in
`docs/T03_R3E_FINAL_PRODUCTION_CUTOVER_REPORT.md`. The permanent archive is:

`D:\11067\CodexWorkspaces\frameflow-v3\archives\migrations\v5.3.2\T03R3E-20260827T073218Z-1d10d139`

It contains the five required archive files. The current canonical database is
Legacy V3 again; production V5 ownership is **not active** until a separately
authorized future cutover.

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
checks. The same application code started in explicit V5 mode against that
candidate, served the P0 API set, wrote a test project through the facade,
restarted, and read the write back. The source file remained unchanged.

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
| `core/runtime/persistence/factory.py` and `facade.py` | `V5_NATIVE` | Explicit V5 mode resolves the candidate, opens StateStore, and exposes only typed P0 persistence methods. |
| `server.py:201` V5 branch | `V5_NATIVE` | V5 startup creates `RuntimePersistence`; it does not call V3 `Database`, seed, backup, or resume functions. |
| `server.py` V5 gateway | `V5_NATIVE` | Dispatches the P0 API set to the facade and returns 501 for non-migrated V3 routes. |
| `server.py` legacy branch | `INVALID_DIRECT_ACCESS` outside V5 mode | Preserved default legacy compatibility; not reachable from V5 mode and therefore counted as 0 in V5 runtime. |
| `frameflow/database.py:1002-1060` | `INVALID_DIRECT_ACCESS` outside V5 mode | Writable V3 implementation retained for default legacy mode; V5 mode never constructs it. |
| `frameflow/recovery.py:96` | `INVALID_DIRECT_ACCESS` outside V5 mode | V3 recovery path remains legacy-only and is blocked by the V5 gateway. |
| `tests/**` | `TEST_ONLY` | Direct database use is isolated to V3 regression, migration, and fixture tests. |

`server.py` still contains many legacy direct SQL reads/writes for the default
legacy mode. The scan found V3-only tables including `provider_profiles`,
`capability_bindings`, `workflow_runs_v3`, `render_jobs_v6`, and
`audit_events_v16`. These are not present in the 11-table candidate. In V5
mode the gateway prevents those handlers from running, and the P0 routes use
the V5 facade instead.

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
are not application runtime ownership. V5 mode requires an explicit candidate
path and never silently falls back to writable V3.

## Required closure before production cutover

1. Open a maintenance window and identify/stop only the FRAMEFLOW writer.
2. Create the permanent rollback snapshot and a final fresh candidate.
3. Re-run the candidate gate and atomically swap the canonical database.
4. Restart the production backend in V5 mode and repeat schema, PRAGMA,
   transaction, and Workbench smoke checks.
5. Only then use the explicit `production_cutover=True` operation. Its default
   CLI path is a no-op/inspection path.
