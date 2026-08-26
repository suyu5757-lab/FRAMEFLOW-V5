# FRAMEFLOW V5.3.2

## T03-R2 Application Persistence Integration

### 1 Executive Verdict

```text
T03-R2 = PASS
V5 BACKEND READY = YES
PRODUCTION CUTOVER READY = YES
PRODUCTION CUTOVER = NOT_PERFORMED
```

The same `server.py` now supports an explicit isolated V5 mode. It opens only
the explicit candidate through `RuntimePersistence -> StateStore`, serves the
Workbench P0 read surface, permits basic project metadata writes, and
survives a backend restart. The default remains legacy until a later cutover.

### 2 Server Dependency Before

Before R2, startup always constructed `frameflow.database.Database`. That
constructor could migrate and write V3 tables, while the V5 candidate has only
11 domain tables. The frontend also loaded ten project snapshot endpoints in
parallel, so changing only `/api/health` was insufficient.

The full matrix is in `docs/T03_SERVER_PERSISTENCE_MAP.md`. Static legacy
handlers remain for legacy mode, but are not reachable from the V5 gateway.

### 3 Persistence Boundary

```text
FRAMEFLOW_RUNTIME_MODE=legacy (default)
    -> existing frameflow.database.Database -> current V3 production DB

FRAMEFLOW_RUNTIME_MODE=v5 (explicit candidate only)
    -> core.runtime.persistence.factory
    -> RuntimePersistence facade
    -> core.runtime.state_store.factory
    -> StateStore -> explicit V5 candidate

historical SH004..SH020
    -> LegacyReadOnlyCompatibility(mode=ro) -> explicit legacy snapshot
```

V5 mode has no fallback to legacy writable `Database`. Missing/invalid V5
configuration aborts startup. Unsupported V3 endpoints return 501 before
their legacy handlers can execute.

### 4 Server Call Matrix

The V5-mode endpoint count is 18: `V5_NATIVE=17`,
`LEGACY_READ_ONLY=1`, `FUTURE_T05=0` reachable calls, and
`INVALID_DIRECT_ACCESS=0`. The legacy handler inventory is documented but is
not V5 runtime reachability.

### 5 Legacy Compatibility

`FRAMEFLOW_LEGACY_READONLY_DB` is optional but explicit. When configured,
`LegacyReadOnlyCompatibility` opens the snapshot with SQLite `mode=ro`.
`SELECT` succeeds and `INSERT`, `UPDATE`, and `DELETE` fail with
`sqlite3.OperationalError`; the adapter's write methods fail with
`LegacyReadOnlyError`.

SH004, SH010, and SH020 were read through the backend compatibility endpoint.
All SH004–SH020 remain accounted as `LEGACY_READ_ONLY_COMPAT`, 17/17, with no
rewrites.

### 6 Fresh Candidate

A fresh candidate was generated from the current production snapshot using
the T02 backup/migration/validation path. It was not the old T02 candidate.

```text
Candidate domain tables: 11/11
Candidate rows: projects=1, sequences=1, shots=3, assets=26, artifacts=31,
                events=160, generations=0, reviews=0
Candidate StateStore PRAGMAs: WAL / foreign_keys=1 / busy_timeout=5000
integrity_check: ok
foreign_key_check: 0
Candidate polluted by V3 migrations: NO
```

### 7 V5 Backend Startup

The actual application was started in a subprocess with:

```text
FRAMEFLOW_RUNTIME_MODE=v5
FRAMEFLOW_V5_DB=<fresh candidate>
FRAMEFLOW_LEGACY_READONLY_DB=<fresh legacy snapshot>
```

The TestClient lifecycle entered and exited `server.py` without a schema
exception. Startup did not call V3 `Database`, `seed_defaults`, daily V3
backup, or V3 task/run resume functions.

### 8 Workbench Critical APIs

The P0 API set returned HTTP 200 for health, settings, data audit, projects,
dashboard, graph, timeline, preflight, story, story runs, assets,
asset-board, asset-audit, and audio-studio. The retired `/api/projects` path
returned 410, and an unsupported V3 route returned 501. The project detail
contained the migrated shots and asset library contained the migrated assets.

### 9 V5 Runtime DB Ownership

During V5 mode, `server.py` exposed no raw SQLite/SQLAlchemy connection to the
request gateway. The only writable object was StateStore behind the facade.
The production DB was not opened by the isolated process; the candidate was
the only writable source.

### 10 Restart Persistence

The test created `T03R2_FIXTURE_CREATE`, updated it to
`T03R2_FIXTURE_UPDATED`, closed the first backend lifecycle, started a second
backend lifecycle, and read the updated name back. The metadata update is
committed through the facade; a fault-injected event failure rolls it back.

### 11 Legacy Mode Regression

The default environment remains `legacy`. Existing V3 regression tests pass
without using V5 mode. No legacy code, legacy tests, Workbench UI, Provider,
Skill, ComfyUI, or production database was removed or disabled.

### 12 Production DB Protection

```text
Path: D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db
SHA before: fccac6a29fa5c91d0ccccdc2545ae1f17010e9349aadd60712401e54d0142cf6
SHA after:  fccac6a29fa5c91d0ccccdc2545ae1f17010e9349aadd60712401e54d0142cf6
Size: 3657728 bytes before and after
Tables: 41 before and after
integrity_check: ok
foreign_key_check: 0
Unchanged: YES
```

No production listener was taken over, no production process was stopped,
and no production DB/WAL/SHM file was staged.

### 13 Remaining Cutover Work

Only the explicitly deferred production operations remain:

```text
maintenance window
identify/stop only the FRAMEFLOW writer
permanent rollback snapshot
final fresh candidate
atomic swap
restart in V5 production mode
production schema/PRAGMA/integrity/runtime verification
```

Production cutover is still forbidden in this task. T03-R3 may be considered
only after supervisor review of this R2 commit.

### 14 Test Evidence

```text
python -m pytest -q tests/schema tests/migration tests/runtime -v: 46 passed
python -m unittest tests.test_v3 -v: 28 passed
npm test: 33 frontend tests passed
Total: 107 passed, 0 failed, 0 skipped, 0 blocked
```

The first frontend invocation in the restricted sandbox hit an esbuild
`spawn EPERM`; the same unchanged suite passed with the approved process-spawn
permission. No frontend source or build output was modified by R2.
