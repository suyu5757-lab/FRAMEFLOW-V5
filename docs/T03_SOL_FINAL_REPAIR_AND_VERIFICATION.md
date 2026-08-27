# T03 SOL Final Repair and Verification

Date: 2026-08-27

Branch: `dev/v5.3.2`

HEAD before repair: `8560a7eeaf73c918ada749f5bd202e9e9e4f35cb`

Verification mode: repair plus isolated verification only

Production cutover performed: **NO**

## 1. Root Cause

R3E correctly placed and opened the V5 database, but the production startup
contract had no persistent owner for the Legacy compatibility archive path.
The application consumed `FRAMEFLOW_LEGACY_READONLY_DB` only from the spawning
process environment. The formal scheduled-task action starts
`python -m uvicorn server:app` without that value, and `perform_production_cutover`
did not create any restart configuration. Consequently, R3E's first V5 process
could return HTTP 200 while every historical compatibility request failed later
with `FRAMEFLOW_LEGACY_READONLY_DB is not configured`; a normal restart would
also lose any shell-only injection.

The database migration and atomic replacement were not the cause.

## 2. Actual Runtime Startup Flow

The repaired flow is:

```text
perform_production_cutover (only during an authorized future cutover)
  -> atomically writes data/runtime-startup.json
     -> records mode, runtime DB, Legacy archive, producer, UTC time, run ID
  -> performs the already-guarded candidate replacement

formal launcher / scheduled task
  -> python -m uvicorn server:app
     -> server.resolve_runtime_environment()
        -> data/runtime-startup.json (authoritative when present)
        -> resolve_runtime_mode()
        -> create_runtime_persistence()
           -> validate explicit Legacy archive before writable V5 open
           -> open_runtime_store()
           -> RuntimePersistence
              -> LegacyReadOnlyCompatibility(mode=ro, immutable=1)
```

Before cutover, no default config file exists, so the current Legacy behavior
continues unchanged. Isolated verification selects a non-production config with
`FRAMEFLOW_RUNTIME_CONFIG`; ownership values themselves are read from the file.

## 3. Repair Selected

- Added a typed `RuntimeStartupConfig` JSON contract and atomic UTF-8 writer.
- Made the persisted file authoritative for runtime ownership values.
- Connected `server.py` startup to the resolved configuration on every process
  start.
- Made V5 startup require an explicit, distinct Legacy archive before opening
  the writable StateStore.
- Added Legacy V3 schema version, required table/column, SQLite integrity, and
  foreign-key validation.
- Updated cutover to persist the exact archive relationship before replacement
  and restore the prior configuration when replacement fails.
- Added a reproducible two-boot HTTP and read-only verification harness.

## 4. Why This Repair Was Chosen

The solution uses repository-owned configuration already colocated with the
canonical database lifecycle. It does not modify machine or user environment,
the Registry, PATH, scheduled-task environment, or system-global state. The
configuration is explicit rather than archive-directory discovery, survives
process and machine restarts, is inspectable JSON, and supports a different
archive for every authorized cutover without hardcoding an archive timestamp
in application code.

Writing the V5 config before the database replacement is deliberate: a crash
in that narrow interval makes startup inspect the still-Legacy canonical DB as
V5 and fail closed. It cannot reopen that file through writable Legacy code.

## 5. Configuration Ownership

| Responsibility | Owner |
|---|---|
| Produce | `core.migration.cutover.perform_production_cutover` |
| Persist | `write_runtime_startup_config`, atomic `os.replace` |
| Validate document | `RuntimeStartupConfig.validated/read` |
| Validate Legacy DB | `inspect_legacy_archive` |
| Propagate | repository file read by every `server:app` process |
| Consume | `server.py` -> persistence factory -> facade |

The document answers the current mode, writable runtime DB, read-only Legacy
DB, producer, generation time, cutover run ID, and restart source directly.
It contains paths and audit metadata only; no secret is stored.

## 6. Fail-Closed Behavior

The final failure-injection suite started the application lifespan in separate
processes and obtained these results:

| Configuration | Result |
|---|---|
| Valid isolated V5 config | PASS |
| Missing Legacy config | STARTUP FAILED CLOSED |
| Missing Legacy path | STARTUP FAILED CLOSED |
| V5 DB reused as Legacy DB | STARTUP FAILED CLOSED |
| Random SQLite DB | STARTUP FAILED CLOSED |

The Legacy validation runs before `open_runtime_store`, so invalid compatibility
configuration does not first expose a healthy V5 API and fail on SH004.
There is no fallback to `data/frameflow.db` or another writable V3 database.

## 7. Legacy ReadOnly Verification

Explicit archive used for this isolated validation:

`D:\11067\CodexWorkspaces\frameflow-v3\archives\migrations\v5.3.2\T03R3E-20260827T073218Z-1d10d139\legacy_frameflow_v3.db`

```text
schema = LEGACY_V3
schema version = 16
tables = 41
integrity_check = ok
foreign_key violations = 0
Windows file attribute = ReadOnly
connection = mode=ro, immutable=1
SELECT = PASS
INSERT = BLOCKED
UPDATE = BLOCKED
DELETE = BLOCKED
SHA before = 249b7581a66ba9c127b80f3c855aab19a447e9215deb22f775389bed6a314843
SHA after  = 249b7581a66ba9c127b80f3c855aab19a447e9215deb22f775389bed6a314843
```

## 8. First Startup Results

The candidate was freshly migrated from the explicit permanent archive into
`data/.cutover/T03SOL-FINAL-d1b2e318/v5-candidate.db`. It was never the
production path.

```text
backend startup = PASS
bind = 127.0.0.1:8877
HTTP health = 200
runtime_mode = v5
V5 domain tables = 11
V3 schema pollution = NO
integrity_check = ok
foreign_key violations = 0
StateStore startup PRAGMA gate = WAL / FK=1 / busy_timeout=5000
```

The health payload's provider readiness remains the known T03-R2 deferred and
unbound state; it is not a startup persistence failure.

## 9. Restart Results

The first backend was terminated and fully waited. The second backend used the
same persisted config file and the same process environment object. Before both
starts the harness removed `FRAMEFLOW_RUNTIME_MODE`, `FRAMEFLOW_V5_DB`,
`FRAMEFLOW_DB_PATH`, `FRAMEFLOW_LEGACY_READONLY_DB`, and
`FRAMEFLOW_V5_PRODUCTION` from the child environment. Only the isolated config
selector and bind host were provided.

```text
second backend startup = PASS
HTTP health = 200
runtime_mode = v5
first-boot write readable after restart = PASS
candidate handle-free rename after stop = PASS
```

Production restart will not need the selector because an authorized cutover
writes the default `data/runtime-startup.json` path.

## 10. 19/19 API Evidence

Both first startup and restart passed the same 19-operation gate:

```text
health, doctor, projects, dashboard, settings, workflows, data-audit,
project, graph, timeline, timeline-preflight, story, story-runs, assets,
asset-board, asset-audit, audio-studio, create-project, update-project
```

```text
first startup: passed=19 failed=0
restart:       passed=19 failed=0
```

The additional gateway checks also passed: retired `/api/projects` returned
410 and an unsupported V5 write path returned 501.

## 11. 17/17 Historical Compatibility Evidence

Every ID from SH004 through SH020 was requested through
`/api/v2/legacy/shots/{id}` and returned HTTP 200 with `read_only=true`.

```text
first startup: passed=17 failed=0
restart:       passed=17 failed=0
```

No sampling or reduced gate was used.

## 12. Regression Results

Final combined command:

```text
python -m pytest tests/schema tests/migration tests/runtime \
  tests/test_v3.py tests/test_recovery_v3.py tests/test_v3_function_matrix.py -q
```

```text
passed = 109
failed = 0
skipped = 0
blocked = 0
duration = 21.46s
FRAMEFLOW_TEST_TMP = D:\11067\CodexWorkspaces\frameflow-v3\.tmp\tests
```

This includes migration, runtime ownership, StateStore, server V5 persistence,
R3C/R3D handle closure, cutover config success/failure restoration, V5 startup
failure injection, and Legacy V3 regression.

## 13. Production Safety Verification

```text
Production cutover performed = NO
Production backend stopped = NO
Production runtime = LEGACY_V3
Production 8787 health = HTTP 200, version 3.0.0, schema 16
Production DB intentionally written by verification = NO
Production DB SHA = 4e742df1c46fb0af92f56426cecd04dd03e8a0cd5daa02ffa55fcc64fcda6455
Production integrity = ok
Production FK violations = 0
Default data/runtime-startup.json created = NO
Production DB staged = NO
Archive/candidate DB staged = NO
```

The isolated V5 server used port 8877 and was stopped. The final listener check
found no process on 8877. No global environment, Registry, PATH, scheduled task,
production DB, permanent archive, or service state was changed.

## 14. Independent Final Review

The final review was performed after implementation and all live gates.

| Review item | Result |
|---|---|
| Shell-only configuration dependency | None |
| First-spawn-only injection | None |
| Hardcoded archive timestamp in application code | None |
| Archive guessing/glob newest behavior | None |
| Writable Legacy fallback | None |
| Hidden exception swallowing in startup validation | None |
| Test-only launcher bypass | No; real `python -m uvicorn server:app` used twice |
| Production DB mutation | None |
| Reduced historical/API gate | None |
| Legacy V3 fallback safety regression | 37/37 PASS |
| Secret in config | None |
| Second writable truth | None |
| UTF-8 BOM in new text files | None |
| `git diff --check` | PASS |

`INVALID_DIRECT_ACCESS=0`: V5 mode continues to intercept the complete P0
persistence surface, the retired V3 path returned 410, the unsupported write
returned 501, and no direct V3 handler was dispatched against the candidate or
archive. The candidate is the only writable source and the archive is read-only,
so dual write and dual source of truth are both absent.

## 15. Remaining Risk

- The real production cutover is still a separately authorized operation and
  must repeat the candidate/archive/fingerprint gates with a fresh final archive.
- Config persistence and database replacement cannot be one cross-file atomic
  filesystem transaction. The selected ordering is fail-closed, and injected
  replacement failure proved that the prior config is restored.
- Provider persistence/readiness remains deferred exactly as documented by
  T03-R2; this repair makes no T05 or provider architecture claims.

No remaining blocker belongs to the startup/configuration root cause.

## 16. Final Gate Decision

```text
FINAL REPAIR = PASS
root cause fixed = YES
configuration survives restart = YES
valid V5 startup = PASS
missing/invalid config fail closed = PASS
Legacy read-only = PASS
19/19 first boot = PASS
17/17 first boot = PASS
19/19 after restart = PASS
17/17 after restart = PASS
INVALID_DIRECT_ACCESS = 0
Dual write = NO
Dual source of truth = NO
Legacy V3 regression = PASS
relevant tests failed = 0
blocked = 0
production cutover performed = NO
READY FOR ONE FINAL PRODUCTION CUTOVER = YES
```
