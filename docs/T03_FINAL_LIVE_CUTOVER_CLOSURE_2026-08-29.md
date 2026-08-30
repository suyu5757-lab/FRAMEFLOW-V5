# FRAMEFLOW V5.3.2 — T03 Final Live Cutover Closure

## Result

`T03 = PASS`

The production Runtime source of truth is now V5 at
`data/frameflow.db`. The prior V3 database is preserved as a read-only
archive; no dual-write path is active.

## Live run

- Maintenance run: `T03FINAL-20260829T203500Z-live`
- Final candidate run: `T03-TRIPLE-GATE-20260829T204000Z-final-live`
- Pre-swap certification:
  `data/.cutover/T03-TRIPLE-GATE-20260829T204000Z-final-live/PRE_SWAP_CERTIFICATION.json`
- Atomic-cutover evidence:
  `data/.cutover/T03-TRIPLE-GATE-20260829T204000Z-final-live/ATOMIC_CUTOVER_RESULT.json`
- Legacy read-only archive:
  `archives/migrations/v5.3.2/T03-TRIPLE-GATE-20260829T204000Z-final-live/legacy_frameflow_v3.db`

## Verified production state

- `/api/health`: `runtime_mode=v5`, `ready=true`, `status=ready`.
- Runtime contract endpoint reports `journal_mode=wal`, `foreign_keys=1`, and
  `busy_timeout=5000` against the canonical V5 database.
- The canonical database contains the 11 Runtime MVP domain tables plus
  `alembic_version` at revision `20260826_01`.
- SQLite `integrity_check` is `ok`; `foreign_key_check` has zero violations.
- Both `FRAMEFLOW Runtime Startup` and `FRAMEFLOW-V3-Service` scheduled tasks
  were independently verified enabled after the maintenance window.
- A restart through `FRAMEFLOW-V3-Service` returned `runtime_mode=v5` and the
  same Runtime contract.

## Post-cutover regression

The following isolated suite passed after the live restart:

```text
tests/runtime/test_post_cutover_db_contract.py
tests/test_runtime_isolation.py
tests/migration/test_runtime_startup_cutover.py

6 passed
```

## Safety outcome

The initial two atomic-cutover calls were rejected before file replacement:
one for incomplete Candidate A lifecycle evidence and one for SQLite sidecar
presence. The final attempt ran only after the complete lifecycle evidence,
maintenance port proof, and an explicit WAL checkpoint had passed.

The V5 database is active. The Legacy archive is retained for read-only
compatibility and rollback evidence; it must not be deleted during cleanup.
