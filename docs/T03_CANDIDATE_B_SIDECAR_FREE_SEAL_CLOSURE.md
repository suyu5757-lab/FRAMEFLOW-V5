# T03 Candidate B Sidecar-Free Terminal Seal Closure

## Scope

This closure addresses only `CANDIDATE_B_FINAL_SEAL_SIDECAR_PRESENT` from
`T03FINAL-20260828T155843Z-16fbdb3b`. No Production cutover was called, the
canonical database was not replaced, and no real V5 runtime was activated.
The failed run remains preserved as read-only `PRE_SWAP_ABORT` evidence.

## Root cause

The failed Candidate B path completed migration, B0 evidence, validation, and
handle closure without a final Candidate B SQLite stabilization step. The last
DB-dependent reader was `logical_data_fingerprint`, whose connection closes in
`core/migration/equivalence.py:264`; Candidate B itself had no checkpoint.

The preserved failed artifact proved:

- `candidate-b.db-wal` existed, size `0` bytes, SHA-256
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`, and
  valid WAL frame count `0`.
- `candidate-b.db-shm` existed, size `32768` bytes, SHA-256
  `fd4c9fda9cd3f9ae7c962b0ddf37232294d55580e1aa165aa06129b8549389eb`.
- Candidate B was not reopened after rename, was not modified by a backend,
  and its logical state did not change.
- No uncheckpointed committed frames were present.

The proven classification is `E + G`:

1. `CHECKPOINT_ORDERING_DEFECT`: the final Candidate B checkpoint was omitted.
2. `ORPHAN_EMPTY_SIDECARS_AFTER_CLEAN_CLOSE`: the artifact remained in WAL
   mode with empty/persistence-only WAL/SHM sidecars after clean close.

Blind sidecar deletion was not used.

## Finalization contract

Candidate B now follows this terminal sequence:

```text
BUILDING
  -> VALIDATING
  -> EVIDENCE_COMPLETE
  -> FINAL_DB_STABILIZATION
  -> HANDLES_CLOSED
  -> FINAL_RENAME_PROBE
  -> SEALED
```

All SQLite-dependent evidence is captured before `HANDLES_CLOSED`. The final
stabilization rejects malformed or non-zero WAL frame counts, executes
`wal_checkpoint(TRUNCATE)`, changes the stopped artifact to
`journal_mode=DELETE`, enables and verifies `foreign_keys=ON`, verifies
`busy_timeout=5000`, integrity, FK violations, page/freelist counts, logical
fingerprint, schema fingerprint, PK fingerprint, and row accounting. It then
closes the DB connection and requires WAL/SHM absence plus four stable
filesystem samples before the final rename probe.

The sealed artifact is sidecar-free DELETE-mode SQLite. This does not weaken
the Production contract: `StateStore._configure_connection` re-establishes
`journal_mode=WAL`, `foreign_keys=ON`, and `busy_timeout=5000` on the first
real runtime connection.

After `SEALED`, only filesystem/evidence operations are allowed. Candidate B
SQLite, SQLAlchemy, StateStore, RuntimePersistence, migration, logical/schema/
row/integrity/FK queries are prohibited until atomic replacement. The lifecycle
counter fail-closes any attempted DB reopen.

## Fresh isolated dry-run

Run ID:
`T03-B-SIDECAR-CLOSURE-20260828T162825Z-a484e32b`

Report:
`data/.cutover/T03-B-SIDECAR-CLOSURE-20260828T162825Z-a484e32b/PRE_SWAP_DRY_RUN.json`

Candidate B result:

```text
backend-opened = NO
B0 complete before stabilization = YES
final stabilization = PASS
journal_mode after stabilization = delete
WAL absent before rename = YES
SHM absent before rename = YES
stable physical samples = 4
handles closed = YES
rename = PASS
SEALED = YES
reopened after rename = NO
post-seal DB open count = 0
WAL/SHM absent at all five post-seal watch points = YES
```

The dry-run's B timeline recorded all required stages:

```text
B_CREATED
B_AFTER_MIGRATION
B_AFTER_B0_CAPTURE
B_AFTER_VALIDATION
B_BEFORE_FINAL_CLOSE
B_AFTER_CHECKPOINT
B_AFTER_FINAL_CLOSE
B_BEFORE_RENAME
B_AFTER_RENAME
B_SEALED
B_FINAL_STABLE
```

Captured B0 and final stabilization evidence retained identical logical,
schema, PK, and row-accounting identities; `UNKNOWN=0`, `UNACCOUNTED=0`, and
`SH004-SH020=17/17`.

Archive finalization was `5/5` and all five artifacts were read-only. Runtime
config bound to this run and maintenance freshness passed. The isolated
controller explicitly reported `perform_production_cutover_called=false` and
`production_db_touched=false`.

## Regression evidence

```text
focused Candidate B/A/lifecycle/cutover suite = 98 passed
schema/migration/runtime = 140 passed
V3 = 37 passed
post-cutover DB contract = 1 passed
Git safety = 10 passed
full suite = 278 passed
failed = 0
errors = 0
blocked = 0
```

The new negative tests cover real pending WAL frames, an open write handle,
and post-seal logical reopen. The positive test covers SQLite sidecar cleanup,
four stable samples, terminal rename, and zero post-seal DB opens.

## Production safety audit

Production remains untouched Legacy V3:

```text
canonical = D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db
physical SHA-256 = 1e4324ed367ad768005da7e58e369cb4db11c0671001399c5ff56e5ca6658ad0
logical SHA-256 = aecc9a92215bc526934151dd9eb0bb92037739579ba0a461be7ea6acd57386ce
schema = LEGACY_V3
tables = 41
schema version = 16
integrity = PASS
foreign_key_check = 0
runtime-startup.json = ABSENT
HTTP = 200
runtime_mode = legacy
status = ready
ready = true
Production DB replaced = NO
Production DB intentionally migrated = NO
dual write = NO
dual source = NO
```

The current Codex controller's Administrator probe returned `False`; therefore
no privileged Production lifecycle operation was attempted in this closure.

## Result

```text
PRODUCTION CUTOVER = NOT_PERFORMED
RUNTIME SOURCE OF TRUTH = LEGACY_V3
ALL PRE_SWAP GATES = PASS (isolated dry-run only)
perform_production_cutover = NOT_CALLED
READY FOR NEW FINAL PRODUCTION CUTOVER AUTHORIZATION = YES
```
