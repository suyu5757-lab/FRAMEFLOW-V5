# FRAMEFLOW V5.3.2 Final Production Cutover and Audit

Date: 2026-08-27

Branch: `dev/v5.3.2`

HEAD before attempt: `e213121feb9ed76bc23433fd85e064445b1938d9`

## Final verdict

```text
T03 FINAL STATUS = FAIL
PRODUCTION CUTOVER = ROLLED_BACK
RUNTIME SOURCE OF TRUTH = LEGACY_V3
READY FOR T00-T03 FINAL RE-AUDIT = NO
```

The single authorized production replacement succeeded. The mandatory first
startup health gate failed because the formal scheduled-task Python environment
could not import a required runtime dependency. Stop Rule and rollback were
executed immediately. No V5 repair, dependency installation, second V5 start,
or second database replacement was attempted.

## Final Legacy baseline

The identified FRAMEFLOW backend PID 18792 was the only listener on
127.0.0.1:8787 and ran `python -m uvicorn server:app --host 127.0.0.1
--port 8787`. It was stopped explicitly; PID exit and absence of the listener
were verified. SQLite checkpointing completed with an explicitly closed
connection before the final fingerprint.

```text
FINAL_LEGACY_SHA = 4e742df1c46fb0af92f56426cecd04dd03e8a0cd5daa02ffa55fcc64fcda6455
size = 3,657,728 bytes
tables = 41
schema_migrations = 16
integrity_check = ok
foreign_key violations = 0
```

The full table and row-count baseline is retained in the run's
`pre_swap_evidence.json` and permanent migration manifest.

## New permanent archive

Run ID:

`T03FINAL-20260827T084503Z-b71c4c75`

Archive:

`D:\11067\CodexWorkspaces\frameflow-v3\archives\migrations\v5.3.2\T03FINAL-20260827T084503Z-b71c4c75`

The archive contained exactly 5/5 required files before production was touched:

```text
legacy_frameflow_v3.db
migration_manifest.json
legacy_fingerprint.json
v5_candidate_fingerprint.json
rollback_instructions.md
```

The Legacy archive SHA equals the final stopped baseline, has 41 Legacy V3
tables, schema version 16, integrity `ok`, zero FK violations, and a Windows
ReadOnly file attribute. SH004-SH020 accounting was 17/17 with UNACCOUNTED=0.

## Fresh Candidate B

Candidate B was freshly migrated from this run's stopped permanent archive,
not from any earlier candidate or failed V5 database.

```text
Candidate SHA = bbbdaf5408c1dba96fbd6f8579740bba649444ef0e740b51836d8eec5f1b1d8c
V5 domain tables = 11
schema drift/errors = 0
integrity_check = ok
foreign_key violations = 0
StateStore PRAGMAs = WAL / foreign_keys=1 / busy_timeout=5000
SH004-SH020 accounted = 17/17
UNACCOUNTED = 0
Candidate volume = D:
Production volume = D:
same-volume = PASS
rename away/back = PASS
```

All candidate connections and StateStore pools were closed before the rename
probe. Candidate B was not reopened between the successful rename probe and
the atomic replacement.

## Runtime startup configuration

Before swap, `data/runtime-startup.json` was atomically generated and validated:

```text
runtime_mode = v5
runtime_db = D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db
legacy_readonly_db = D:\11067\CodexWorkspaces\frameflow-v3\archives\migrations\v5.3.2\T03FINAL-20260827T084503Z-b71c4c75\legacy_frameflow_v3.db
production = true
generated_by = core.migration.cutover.perform_production_cutover
cutover_run_id = T03FINAL-20260827T084503Z-b71c4c75
```

JSON parsing, exact current-archive relationship, path inequality, Legacy
schema/integrity, read-only adapter construction, and 17-shot accounting all
passed.

## Atomic swap

The one permitted `perform_production_cutover` call completed its same-volume
`os.replace` successfully.

```text
Atomic replacement = PASS
V5 production SHA = bbbdaf5408c1dba96fbd6f8579740bba649444ef0e740b51836d8eec5f1b1d8c
V5 domain tables = 11
V3 schema pollution = NO
integrity_check = ok
foreign_key violations = 0
```

## First production startup failure

The normal `FRAMEFLOW-V3-Service` scheduled task was used. Its action selects:

`D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe`

and starts `-m uvicorn server:app --host 127.0.0.1 --port 8787` without runtime
ownership environment injection. The task wrapper returned, but no 8787
listener appeared and health connections were refused.

Independent reproduction of the task interpreter's import produced:

```text
ModuleNotFoundError: No module named 'jsonschema'
```

The failure occurs while importing `core.migration.legacy_compat`, before the
FastAPI lifespan and before StateStore opens. The same formal task also failed
after the Legacy database and Legacy startup state were restored, confirming a
formal launcher `.venv` dependency problem rather than a V5 database,
`runtime-startup.json`, or Legacy archive validation failure.

Because the first health gate failed, the 19 API, 17 historical compatibility,
production WAL/FK connection, transaction, FK-enforcement, and restart gates
were not run. They are failures for this production attempt and were not
lowered or substituted with isolated evidence.

## Rollback

Rollback began immediately after the first startup failure:

1. Confirmed no V5 backend/listener remained.
2. Preserved the failed V5 production database at
   `data\.cutover\T03FINAL-20260827T084503Z-b71c4c75\failed_v5_production.db`.
3. Preserved the failed V5 startup config beside it.
4. Copied the permanent archive to a same-volume rollback candidate.
5. Atomically restored the canonical production path.
6. Removed `data/runtime-startup.json`, restoring the prior default Legacy state.
7. Attempted the formal scheduled task; it failed with the same missing
   dependency.
8. Restored Legacy 8787 using the exact global-Python Uvicorn command observed
   before cutover.

Pre-start rollback verification matched the archive exactly:

```text
restored SHA = 4e742df1c46fb0af92f56426cecd04dd03e8a0cd5daa02ffa55fcc64fcda6455
tables = 41
schema version = 16
integrity_check = ok
foreign_key violations = 0
runtime-startup.json = absent
```

After normal Legacy startup writes to provider profile/capability state, the
active main-file SHA became
`b02ec8bdf4f70b751152e73b3a311e6dcc1bedb566801d39d31c083d1adbfd69`.
The runtime remains a healthy 41-table Legacy V3 database with integrity `ok`.
The permanent archive SHA remains unchanged.

```text
Rollback health = HTTP 200
version = 3.0.0
schema_version = 16
runtime_mode = legacy
ready = true
```

## Runtime ownership after rollback

```text
Writable source of truth = data/frameflow.db (LEGACY_V3)
Permanent archive = READ_ONLY
Failed V5 DB = preserved, inactive
runtime-startup.json = absent
Invalid direct writable access = 0 observed
Dual write = NO
Dual source of truth = NO
Legacy writable runtime disabled = NO
```

## Automated regression

The complete repair/regression set was rerun after rollback:

```text
109 passed
0 failed
0 skipped
0 blocked
duration = 20.00s
```

## Independent production audit

The audit independently checked the canonical DB path and table set, live
health, active runtime mode, absence of `runtime-startup.json`, new archive path
and ReadOnly attribute, exact archive file count, unchanged archive SHA,
preserved failed V5 DB, rollback health, Git branch/HEAD, and the formal task
interpreter import failure.

The database/archive/candidate gates and atomic replacement passed, but the
mandatory formal first-start gate did not. Therefore production V5 was not
retained and T03 cannot pass.

## Final decision

```text
PRODUCTION CUTOVER = ROLLED_BACK
RUNTIME SOURCE OF TRUTH = LEGACY_V3
Production rollback triggered = YES
Rollback verification = PASS
Second cutover attempted = NO
T03 FINAL STATUS = FAIL
READY FOR T00-T03 FINAL RE-AUDIT = NO
```

Per the task Stop Rule, no launcher repair, dependency installation, or T05
work was performed in this attempt.
