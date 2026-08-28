# T03 Candidate B Terminal Seal Closure

## Scope

This closure addresses only `CANDIDATE_B_POST_RENAME_REOPEN` from
`T03FINAL-20260828T151315Z-48f5ec56`. Production cutover was forbidden for
this turn and was not called. The historical `PRE_SWAP_ABORT` evidence is
preserved unchanged.

## Root cause

The failed run's run-local helper
`data/.cutover/T03FINAL-20260828T151315Z-48f5ec56/prepare_production_preswap.py`
called `logical_data_fingerprint(path)` at line 83 after
`handle_free_rename_probe(path)` returned at line 81. The logical fingerprint
helper uses `sqlite3.connect(..., mode=ro)` through
`core/migration/equivalence.py` `_read_only()` at lines 63-74. Its purpose was
to recompute a post-rename logical SHA for an unchanged-state assertion.

The final rename implementation is
`core/migration/cutover.py:123-155`, and is filesystem-only. The reopen was a
direct read-only SQLite connection; no Runtime backend, StateStore, or
SQLAlchemy Engine was used after the rename. Candidate B was not modified and
its logical state did not change.

## Terminal lifecycle

`core/migration/candidate_b_lifecycle.py` now enforces:

```text
BUILDING
  -> VALIDATING
  -> EVIDENCE_COMPLETE
  -> HANDLES_CLOSED
  -> FINAL_RENAME_PROBE
  -> SEALED
```

All known migration, validation, logical/schema fingerprint, StateStore,
backup, compatibility, and checkpoint open boundaries consult the lifecycle
guard. After `SEALED`, database opens fail closed with:

```text
Candidate B is sealed; database reopen after final rename is forbidden
```

The terminal evidence records the pre-seal database-open count, seal and
rename timestamps, post-seal open count, and post-seal open attempts.

## Evidence boundary

Before `HANDLES_CLOSED`, the run captures the frozen source, migration
revision and implementation, schema fingerprint, logical/domain fingerprints,
business PKs, row accounting, UNKNOWN/UNACCOUNTED, SH004-SH020 accounting,
integrity, foreign-key checks, and the required SQLite contract evidence.

After `SEALED`, only filesystem/path/volume/file-attribute checks, captured
evidence comparison, archive JSON finalization from stored B0, runtime-config
binding, maintenance freshness, and aggregate gate evaluation are allowed.
No Candidate B SQLite, SQLAlchemy, StateStore, RuntimePersistence,
FastAPI/Uvicorn, migration, schema, logical, row-count, integrity, or FK query
is permitted.

The physical SHA/stat check after rename is explicitly a filesystem artifact
check; it does not open SQLite. Logical equivalence uses the already captured
B0 evidence.

## Regression and isolated certification

Fresh isolated dry-run:

```text
Run = T03-TRIPLE-GATE-20260828T154604Z-e9990c3d
Candidate B backend-opened = NO
Candidate B validation = PASS
Candidate B handles closed = YES
Candidate B rename = PASS
Candidate B state = SEALED
Candidate B reopened after rename = NO
Candidate B post-seal DB open count = 0
A0/B0 equivalence = PASS
Archive = 5/5 readonly
Runtime config THIS RUN = YES
Maintenance freshness = PASS
ALL PRE_SWAP GATES = PASS
perform_production_cutover = NOT_CALLED
Production DB touched = NO
```

The negative regression reproduces the failed ordering and fails closed after
seal. The positive regression proves the terminal sequence and zero post-seal
database opens.

Regression totals after closure:

```text
Focused = 63 passed
Schema/migration/runtime = 137 passed
V3 = 37 passed
Post-cutover DB contract = 1 passed
Git safety = 10 passed
Full suite = 275 passed
Failed = 0
Errors = 0
Blocked = 0
```

## Production safety audit

Production remains Legacy V3:

```text
canonical = D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db
tables = 41
schema = 16
integrity = ok
foreign_key_check = 0
HTTP = 200
runtime_mode = legacy
status = ready
ready = true
runtime-startup.json = ABSENT
Production DB replaced = NO
Production DB intentionally migrated = NO
Dual write = NO
Dual source = NO
```

## Closure decision

```text
STATUS = PASS
PRODUCTION CUTOVER = NOT_PERFORMED
READY FOR NEW FINAL PRODUCTION CUTOVER AUTHORIZATION = YES
```
