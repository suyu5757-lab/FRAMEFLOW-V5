# T03-R3D Candidate Handle Closure & Windows Test Environment Report

## Result

```text
T03-R3D STATUS: PASS
PRODUCTION CUTOVER: NOT_PERFORMED
RUNTIME SOURCE OF TRUTH: LEGACY_V3
READY FOR T03-R3E FINAL CUTOVER: YES
```

This task only closed candidate/database handles and remediated the Windows
test environment. It did not stop or replace the production database, create a
production archive, or switch the runtime source of truth.

## Implemented controls

- All short-lived SQLite connections in the migration, validation, backup,
  and runtime ownership paths now have explicit `close()` ownership.
- Backup/restore closes the source connection even when destination connection
  creation fails.
- V3-to-V5 migration closes both legacy and candidate connections when setup or
  row transformation raises.
- Candidate validation and read-only inspection close connections on setup
  exceptions as well as normal completion.
- `StateStore` initialization failure disposes its SQLAlchemy engine;
  `StateStore.dispose()` is idempotent; runtime factory PRAGMA failure and
  persistence-facade construction failure dispose their owned pools.
- `inspect_database()` uses a normal read-only WAL view when an existing WAL is
  present and uses `immutable=1` for stopped databases without a WAL sidecar.
- Pytest uses `FRAMEFLOW_TEST_TMP`, defaulting to:
  `D:\11067\CodexWorkspaces\frameflow-v3\.tmp\tests`.
  The test process and spawned backend processes inherit this path. Pytest
  cache writes are disabled so the Windows cache-directory ACL issue cannot
  create additional restricted temporary directories.
- Tests that previously used Python's Windows-restricted
  `TemporaryDirectory()` now create explicit writable workspace directories.

## Required evidence

| Gate | Evidence | Result |
|---|---|---|
| SQLite explicit close / no connection context manager | R3D static handle audit | PASS |
| StateStore shutdown and double shutdown | `test_t03_r3d_handles.py` | PASS |
| SQLAlchemy pool disposal | R3D StateStore/persistence rename probes | PASS |
| Persistence factory reset/shutdown | R3D factory shutdown test | PASS |
| Candidate A backend smoke and rename | R3C backend probe plus V5 persistence P0 routes | PASS |
| Candidate B validation and D: rename | R3D candidate-B test | PASS |
| Candidate B validation-exception cleanup and rename | R3D injected-exception test | PASS |
| Windows temporary ACL remediation | `FRAMEFLOW_TEST_TMP` test environment | PASS |
| V3 regression | `tests/test_v3.py`, `tests/test_recovery_v3.py`, `tests/test_v3_function_matrix.py` | PASS |

## Test results

```text
pytest tests/runtime/test_t03_r3d_handles.py
5 passed, 0 failed

pytest tests/runtime/test_t03_r3c_handles.py tests/migration/test_t03_r3b_cutover.py
13 passed, 0 failed

pytest tests/schema tests/migration tests/runtime
59 passed, 0 failed

pytest tests/runtime/test_server_v5_persistence.py
6 passed, 0 failed

pytest tests/test_v3.py tests/test_recovery_v3.py tests/test_v3_function_matrix.py
37 passed, 0 failed

Combined final relevant validation set
96 passed, 0 failed
```

```text
blocked = 0
Windows temporary-directory ACL failures = 0
Candidate B validation = PASS
Candidate B validation-exception cleanup = PASS
Candidate B rename probe = PASS
Production replacement = NOT_PERFORMED
```

## Gate decision

T03-R3D is PASS. The project may proceed to the separately authorized
T03-R3E one-final-cutover task. That cutover was not started in this task.
