# FRAMEFLOW V5.3.2 Production Environment Closure

Date: 2026-08-27

Branch: `dev/v5.3.2`

HEAD before repair: `e213121feb9ed76bc23433fd85e064445b1938d9`

Production cutover performed: **NO**

Runtime source of truth: **LEGACY_V3**

## Root cause

The production scheduled task was already pinned to the correct project
interpreter, but the project `.venv` was incomplete. It lacked `jsonschema`,
SQLAlchemy, and Alembic. `jsonschema` was also absent from the project's only
dependency manifest. The preceding 109 tests and candidate smoke used global
Python, whose installed packages masked that drift.

The failed cutover process exited on:

```text
ModuleNotFoundError: No module named 'jsonschema'
```

before FastAPI lifespan and before StateStore opened.

## Test and production interpreters

```text
Test interpreter before repair:
C:\Users\11067\AppData\Local\Programs\Python\Python314\python.exe

Production interpreter:
D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe

Both Python versions:
3.14.6
```

The complete context map is in `docs/T03_PRODUCTION_ENVIRONMENT_MAP.md`.

## Dependency declaration and synchronization

The existing project mechanism is `requirements.txt`. No lock or alternate
packaging system exists. The successful global environment provided the version
selection evidence, so the runtime requirement was added as:

```text
jsonschema==4.26.0
```

The first project-scoped install attempt exposed the known Windows temporary
directory ACL issue. Installation was repeated with a writable workspace temp
directory. A dry run of the complete manifest then proved that only
already-declared SQLAlchemy/Alembic and their direct dependencies were also
missing. Synchronizing `requirements.txt` installed only those missing items;
already-satisfied packages were not upgraded.

Final formal environment results:

```text
jsonschema installed = 4.26.0
jsonschema declared = 4.26.0
pip check = No broken requirements found.
server import = PASS
```

`.venv` and site-packages remain ignored and were not staged.

## Runtime import smoke and interpreter identity

`core.migration.production_environment` now owns the pre-swap environment
contract. It requires the exact project `.venv` interpreter, verifies its
resolved path and prefix, accepts Python 3.11 through 3.14, compares the
installed `jsonschema` version with the exact manifest declaration, runs
`pip check`, and imports only the real V5 startup chain:

```text
jsonschema
server
core.runtime.persistence
core.runtime.persistence.startup_config
core.runtime.state_store
core.runtime.state_store.factory
core.migration.legacy_compat
scripts.migrate_shot_spec_v1_to_v2_2
```

All identity, import, version, and dependency checks passed from the formal
`.venv`.

## Formal Launcher Pre-Swap Gate

The isolated verification harness now refuses to run unless its own
`sys.executable` is the exact formal `.venv` interpreter. It starts the same
Uvicorn entrypoint as production, writes one persisted candidate runtime config,
stops the first process, and starts the same command again without ownership
environment injection.

It removes its two candidate-only API fixtures before emitting versioned
evidence containing:

- exact interpreter identity and import/pip results;
- exact Uvicorn command;
- candidate and Legacy archive paths;
- runtime config payload;
- first-start 19-API and 17-shot results;
- restart 19-API and 17-shot results;
- read-only archive results;
- fixture-cleanup proof and the post-probe candidate SHA.

`perform_production_cutover` now fails before any config write, move, or
`os.replace` unless:

1. the live formal interpreter/import/pip gate passes; and
2. matching complete two-boot formal-launcher evidence is supplied.

The evidence validator rejects a wrong interpreter, wrong Uvicorn entrypoint,
candidate/archive mismatch, ownership environment injection, missing restart,
or any count below 19/19 and 17/17. It also hashes the candidate immediately
before a future swap and rejects evidence if that file changed after the probe.

## Formal first-start and restart verification

Evidence run:

`T03ENV-20260827T093832Z-540a7e12`

Interpreter:

`D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe`

Candidate:

`D:\11067\CodexWorkspaces\frameflow-v3\data\.cutover\T03ENV-20260827T093832Z-540a7e12\v5-candidate.db`

Read-only Legacy source:

`D:\11067\CodexWorkspaces\frameflow-v3\archives\migrations\v5.3.2\T03FINAL-20260827T084503Z-b71c4c75\legacy_frameflow_v3.db`

```text
First startup backend = PASS
First startup HTTP health = 200
First startup runtime_mode = v5
Workbench first startup = 19 passed, 0 failed
SH004-SH020 first startup = 17 passed, 0 failed

Formal launcher restart = PASS
Restart HTTP health = 200
Restart runtime_mode = v5
Workbench after restart = 19 passed, 0 failed
SH004-SH020 after restart = 17 passed, 0 failed
First-boot write persisted across restart = PASS
Runtime configuration survived restart = YES
Legacy SELECT = PASS
Legacy INSERT/UPDATE/DELETE = BLOCKED
Probe fixtures removed = PASS
Candidate unchanged after evidence binding = PASS
```

The isolated backend used port 8877 and was stopped. Production V5 was not
started and no production database replacement occurred.

## Negative pre-swap tests

Ten environment tests were added and all passed:

| Test | Result |
|---|---|
| E1 formal `.venv` interpreter identity | PASS |
| E2 required runtime import smoke | PASS |
| E3 declared/installed `jsonschema` consistency | PASS |
| E4 formal launcher candidate startup | PASS |
| E5 first-start 19/19 | PASS |
| E6 first-start 17/17 | PASS |
| E7 formal launcher restart 19/19 + 17/17 | PASS |
| E8 wrong interpreter blocks | PASS |
| E9 missing dependency blocks before launcher/swap | PASS |
| E10 failed pre-swap evidence leaves production untouched | PASS |

The cutover success-path tests now also require formal-launcher evidence. An
injected replacement failure still restores the prior runtime configuration.

## Existing regression and Legacy V3

```text
Existing relevant suite = 109 passed, 0 failed, 0 blocked
New environment suite = 10 passed, 0 failed, 0 blocked
Legacy V3 regression subset = 37/37 PASS
```

After dependency repair, the temporary global-Python Legacy backend was stopped
and the real `FRAMEFLOW-V3-Service` scheduled task was started. It used the
project `.venv` and returned:

```text
HTTP = 200
version = 3.0.0
schema_version = 16
runtime_mode = legacy
ready = true
```

## Production safety

```text
Production cutover = NOT_PERFORMED
data/frameflow.db replacement = NO
Production V5 startup = NO
Runtime source of truth = LEGACY_V3
data/runtime-startup.json = absent
Test writes to production DB = NO
Candidate/test writes = isolated only
Production DB staged = NO
Archive/candidate staged = NO
```

The main-file SHA changed during the authorized Legacy launcher restart because
Legacy startup normally writes provider profile/capability state. No migration,
candidate, transaction fixture, or deliberate test write targeted the production
database. Schema remained 41-table Legacy V3, integrity `ok`, and FK violations
zero.

## Independent audit

The final audit answered:

```text
Which Python launches production? project .venv, exact absolute path
Is it deterministic? YES
Does .venv contain declared runtime dependencies? YES
Does the manifest declare jsonschema? YES, exact 4.26.0
Does the formal launcher use the tested environment? YES
Can restart work without Codex shell ownership state? YES
Would wrong Python or a missing dependency block before swap? YES
Was a Production Cutover performed? NO
```

Static review found no PATH fallback, system environment modification, hidden
writable DB fallback, archive timestamp hardcode, or `.venv` staging. The
formal evidence is bound to its candidate and archive and is rechecked together
with a live interpreter gate immediately before any future replacement.

## Remaining risks

- The project has ranges rather than a complete lock for most runtime packages.
  This task did not introduce a new packaging system or mass version changes.
- A future cutover must generate fresh formal-launcher evidence for its fresh
  candidate and archive; the prior evidence cannot match new paths.
- Legacy startup's normal provider-state writes mean file hashes must continue
  to be captured only after stopping the writer.

## Final verdict

```text
PRODUCTION ENVIRONMENT CLOSURE = PASS
Production cutover = NOT_PERFORMED
Runtime source of truth = LEGACY_V3
READY FOR FINAL CUTOVER RETRY = YES
```
