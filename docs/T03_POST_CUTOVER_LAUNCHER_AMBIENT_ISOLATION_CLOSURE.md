# T03 post-cutover launcher ambient-isolation closure

## Scope

This closure remediates the rolled-back Production run
`T03FINAL-20260829T103409Z-77935850`.  It changes no Production database,
runtime-startup configuration, Scheduled Task, archive, or historical evidence.

## Positive root cause

The failed post-cutover test was
`tests/runtime/test_mode_aware_launcher_integration.py::test_exact_runtime_launcher_honors_v5_config_on_first_start_and_restart`.

Its PowerShell invocation passed an explicit isolated `-RuntimeConfigPath`, but
did not pass a maintenance-state path or `-AllowDuringMaintenance`.  During
the real cutover the global `data/.cutover-maintenance.json` was active with
`allow_runtime_start=false`.  The launcher therefore exited at
`scripts/start-frameflow-stack.ps1:104`, before target resolution, bind, child
environment construction, or Uvicorn startup.  The preserved runtime log at
2026-08-29 18:37:27Z records the same rejection.

This is not a runtime-config precedence failure, a canonical-DB ownership
failure, a port collision, or a V5 route failure.  The historical failure
classification is `OTHER: global maintenance gate captured an isolated test
launcher`.

## Repair

`start-frameflow-stack.ps1` now accepts `-MaintenanceStatePath` for an
explicit non-production target only.  Production targets reject that override.
The formal Scheduled Tasks do not pass it and retain the repository's global
maintenance gate.  The integration test passes a new, nonexistent file within
its own temporary root, so it never reads or changes the Production maintenance
token.

The production launcher also scopes `FRAMEFLOW_V5_PRODUCTION_SIMULATION` to
the selected production target.  An explicit isolated V5 configuration is no
longer rejected merely because its parent environment represents an ambient
production-like simulation.

## Regression evidence

The launcher integration regression now starts an isolated ambient V5 runtime
with `production=true`, a distinct config, database, legacy archive, and port.
It then launches and restarts another explicit non-production V5 target through
the real PowerShell launcher.  It proves:

- explicit isolated config wins over the ambient V5 configuration;
- the two listeners use different ports;
- both isolated starts are ready and their doctor database is the isolated DB;
- the simulated ambient V5 database/config remain unchanged;
- the real canonical DB and `data/runtime-startup.json` remain unchanged; and
- both isolated process trees exit completely.

`tests/runtime/test_production_launcher.py` separately proves the explicit
isolated resolver ignores an ambient production-simulation flag.

## Live StateStore SQLite contract

`GET /api/v2/system/runtime-contract` reports PRAGMAs from the active
`RuntimePersistence` object's `StateStore` pool, rather than from a newly
opened sqlite3 connection.  The formal isolated verifier checks it immediately
after V5 readiness and before the Workbench API gate.  Required values are
`journal_mode=wal`, `foreign_keys=1`, and `busy_timeout=5000` for the expected
runtime database.

## Historical SHA terminology

The two observed SHA-256 values are distinct stages, not a reporting typo:

| Name | SHA-256 | Evidence |
| --- | --- | --- |
| `LEGACY_FINAL_STABLE_SHA` | `0879ebefdc115a0fcb076a1a1fd2d520b9dbc0f2d326ee314a0cb76508360182` | Stopped/checkpointed pre-swap canonical; identical frozen source, archive, and rollback source. |
| `LEGACY_RESTARTED_RUNTIME_SHA` | `b5a29c3124c8c7599fe7f694469f0cb71824e514843944aad4159c58c6a83ac0` | Current canonical after rollback recovery and Legacy runtime restart. |

The frozen source and archive both have the first SHA and the same 3,657,728
byte size.  Rollback evidence records the same source and rollback-candidate
SHA.  A read-only comparison gives both the current canonical and historical
archive the logical SHA
`aecc9a92215bc526934151dd9eb0bb92037739579ba0a461be7ea6acd57386ce`.
The restarted Legacy runtime subsequently establishes WAL/SHM state, so the
physical SQLite layout is not an identity label for the pre-swap frozen source.
Future cutover reports must use the stage-specific names above and record a
separate logical fingerprint.
