# FRAMEFLOW V5.3.2 Final Production Cutover and Audit

Date: 2026-08-27

Branch: `dev/v5.3.2`

HEAD before attempt: `e213121feb9ed76bc23433fd85e064445b1938d9`

## Historical lifecycle failure — 2026-08-28

The later authorized run `T03FINAL-20260828T052147Z-bed3dc7b` is preserved
under `data/.cutover/T03FINAL-20260828T052147Z-bed3dc7b/`. It reached:

```text
Atomic replacement = PASS
V5 canonical validation = PASS
P4 8787 = FREE
```

It then failed at the post-swap lifecycle restore/start boundary:

```text
POST_SWAP_V5_LIFECYCLE_RESTORE_NO_LISTENER
```

The failure was not migration nondeterminism, port ownership conflict, or the
full-regression database assumption; those remain closed historical findings.
The concrete lifecycle defect was that maintenance `Restore` conflated future
Scheduled Task policy restoration with starting and verifying the current
runtime. The startup task uses an `AtLogOn` trigger and the service task has no
trigger, so enabling either task is not an immediate or mode-verified process
start. The service Action was also a direct V3-shaped Uvicorn invocation, and
the stack launcher did not validate `runtime-startup.json` or
`health.runtime_mode`.

The repair is documented in
`docs/T03_PRODUCTION_LIFECYCLE_MODE_AWARE_CLOSURE.md` and introduces the
explicit sequence:

```text
StartTarget
  -> resolve and explicitly start the selected runtime
  -> verify owner, doctor database, health, and runtime_mode
RestoreAutostartPolicy
  -> restore only future task Enabled policy
```

Rollback uses `StartTarget` after restoring Legacy DB/config and then
`RestoreLegacy`. This historical run was rolled back successfully, leaving the
production source of truth as Legacy V3. No retry or new production swap was
performed by the lifecycle repair.

### Real Scheduled Task activation certification attempt

The user subsequently authorized the exact `FRAMEFLOW-V3-Service` Action-only
mutation and real Legacy lifecycle certification. The initial Codex-host
attempt used `Set-ScheduledTask -Action`, but the host process had no
administrator token (`IsAdministrator=False`) and Windows returned `Access
Denied`. The operator then ran the same updater successfully from an
Administrator PowerShell. A fresh independent export proved Action-only
installation with unchanged trigger, principal, run level, and settings.

The failed first attempt's before/after XML SHA-256 values were identical:

```text
before = 1B70D542B930731BE830C1C1595FF642C1A0E48A252B485187B85F826D3B1766
after  = 1B70D542B930731BE830C1C1595FF642C1A0E48A252B485187B85F826D3B1766
```

The installed service task is now mode-aware. No `Enter`, `StartTarget`, or
`RestoreLegacy` production lifecycle was started because the Codex controller
itself remains non-elevated; production remains Legacy V3 and no V5 cutover was
attempted. Full details and evidence paths are in
`docs/T03_PRODUCTION_LIFECYCLE_MODE_AWARE_CLOSURE.md`.

## Final authorized production swap — rolled back (2026-08-27)

The one authorized production replacement was executed from blocker-repair
HEAD `5269824f9e2a830d84094b3779fdb51a741b1159`. All formal environment,
43-test safety regression, permanent archive, Candidate A, Candidate B, and
A0/B0 deterministic equivalence gates passed before the replacement.

Run ID:

`T03FINAL-20260827T135157Z-a483f658`

```text
FINAL_LEGACY_SHA = 38c4342bae668e5d6198602059c83bb261b6206a7de04e17e20cf11838ca30d8
Permanent archive = 5/5, READ_ONLY
Migration implementation = v3_to_v5:20260826_01-deterministic-v2
A0 logical SHA = f469daa1b2746c3fe259e964d009e37070e277972fc6bd7d21a23229441acf59
A1 logical SHA = f469daa1b2746c3fe259e964d009e37070e277972fc6bd7d21a23229441acf59
B0 logical SHA = f469daa1b2746c3fe259e964d009e37070e277972fc6bd7d21a23229441acf59
Candidate A first/restart = 19/19 + 17/17 twice
Candidate B backend-opened = NO
Candidate B validation/rename = PASS/PASS
UNKNOWN = 0
UNACCOUNTED = 0
Atomic replacement = PASS (one attempt)
```

The preflight command `Get-NetTCPConnection -ErrorAction SilentlyContinue`
returned no listener, but this was a false negative caused by process visibility
permissions. After replacement, the formal V5 launcher exited with WinError
10048 because port 8787 was already held. `netstat -ano` then proved that
long-lived Python PID 39204, created at 20:04:55, was listening on
127.0.0.1:8787. The attempted V5 process never owned production traffic.

The hard rollback rule was applied immediately. The failed V5 canonical DB and
its startup config were preserved under this run's `data/.cutover` directory.
The same run's read-only Legacy archive was copied through the tested SQLite
backup mechanism to a same-volume rollback candidate and atomically restored.
The V5 startup config was removed. No second cutover was attempted.

Independent rollback audit:

```text
Production schema = LEGACY_V3
Production tables = 41
Schema version = 16
Integrity = ok
Foreign-key violations = 0
Live health = HTTP 200, version 3.0.0, ready=true
Live listener = PID 39204
data/runtime-startup.json = absent
Failed V5 DB preserved = YES
Archive = 5/5 READ_ONLY
V3 regression = 37 passed
Dual write = NO
Dual source of truth = NO
Rollback verification = PASS
Second production swap = NO
```

Final result for this authorized run:

```text
PRODUCTION CUTOVER = ROLLED_BACK
RUNTIME SOURCE OF TRUTH = LEGACY_V3
T03 FINAL STATUS = FAIL
READY FOR T00-T03 FINAL RE-AUDIT = NO
```

The failure is an operational listener-ownership preflight defect, not a
Candidate migration/equivalence regression. Per authorization, this run is
closed and cannot retry the production swap.

### Port ownership remediation closure

The conflict was subsequently closed without another production replacement.
PID 39204 was positively identified as the formal Legacy Uvicorn worker started
by `FRAMEFLOW-V3-Service`, itself invoked by the logon `FRAMEFLOW Runtime
Startup` task. The cutover had never stopped it: a permission-sensitive
`Get-NetTCPConnection -ErrorAction SilentlyContinue` query returned a false
empty result.

The repaired lifecycle uses netstat PID ownership, FRAMEFLOW doctor identity,
an elevated exact-PID controller, a TTL maintenance token, temporary disabling
of both exact tasks, repeated FREE observations, and two live pre-swap probes.
Foreign and unknown owners fail closed. Real Windows integration stopped the
formal Legacy owner, proved no respawn and blocked both task/stack starts, then
restored the original task states and healthy Legacy runtime under a new PID.

```text
Port ownership closure = PASS
Relevant tests = 92 passed, 0 failed, 0 blocked
Production DB replacement during closure = NO
Atomic replacement during closure = NOT_PERFORMED
Runtime source of truth = LEGACY_V3
READY FOR FINAL PRODUCTION CUTOVER = YES
```

## Candidate B terminal seal closure — 2026-08-28

The failed run `T03FINAL-20260828T151315Z-48f5ec56` is preserved as historical
`PRE_SWAP_ABORT` evidence. Its only unresolved defect was
`CANDIDATE_B_POST_RENAME_REOPEN`: the run-local rename helper recomputed a
logical fingerprint after the final Candidate B rename, reopening the file
through a read-only `sqlite3` connection. Candidate B was not modified and
its logical state did not change.

The closure is documented in
`docs/T03_CANDIDATE_B_TERMINAL_SEAL_CLOSURE.md`. Candidate B now has an
explicit terminal lifecycle ending in `SEALED`; all known database-open
boundaries fail closed after sealing. The final rename is filesystem-only and
all logical equivalence, schema, PK, row-accounting, integrity, FK, and SQLite
contract evidence is captured before the seal.

Fresh isolated certification:

```text
Run = T03-TRIPLE-GATE-20260828T154604Z-e9990c3d
Candidate B backend-opened = NO
Candidate B validation = PASS
Candidate B handles closed = YES
Candidate B rename = PASS
Candidate B reopened after rename = NO
Candidate B post-seal DB open count = 0
Candidate B state = SEALED
A0/B0 equivalence = PASS
Archive = 5/5 readonly
Runtime config THIS RUN = YES
Maintenance freshness = PASS
ALL PRE_SWAP GATES = PASS
perform_production_cutover = NOT_CALLED
Production DB touched = NO
```

Post-closure regressions:

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

Independent Production audit remains Legacy V3: canonical path unchanged,
41 tables, schema 16, integrity `ok`, zero FK violations, HTTP 200,
`runtime_mode=legacy`, `status=ready`, `ready=true`, and
`runtime-startup.json` absent. No Production replacement or migration was
performed.

```text
STATUS = PASS
PRODUCTION CUTOVER = NOT_PERFORMED
READY FOR NEW FINAL PRODUCTION CUTOVER AUTHORIZATION = YES
```

## FINAL_PRESWAP_TRIPLE_GATE_CLOSURE_2026-08-28

The failed run `T03FINAL-20260828T140500Z-0b2dc631` was preserved as a
pre-swap abort. No Production replacement was attempted. Its final three
pre-swap defects were positively identified:

```text
Archive readonly = FAIL because only legacy_frameflow_v3.db had the
  ReadOnly attribute; the four JSON/Markdown artifacts remained writable.
Runtime config THIS RUN = NO because runtime-startup.json was a target path
  only and perform_production_cutover was never called after the earlier gate
  failure.
Maintenance freshness = NOT_EVALUATED because the A0/B0 gate aborted before
  the final freshness predicate; the two-hour token itself was not expired.
Formal interpreter path discrepancy = REPORTING_TYPO; actual execution used
  D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe.
```

The closure added fail-closed controls for the five-file permanent archive,
current-run runtime configuration binding, and maintenance freshness. The
archive contract is all five artifacts ReadOnly, not only the database. The
config contract distinguishes the target path from file existence and binds
`runtime_mode=v5`, the canonical runtime database, this run's archive, and the
current `cutover_run_id`. The freshness contract checks an active bounded TTL,
paused startup tasks, no respawn, stored FREE state, and a fresh live FREE
probe.

The no-swap formal harness used the corrected `A0_MIGRATION_BASELINE` and
`B0_MIGRATION_BASELINE` constants and completed:

```text
Run = T03-TRIPLE-GATE-20260828T144221Z-b92a6c72
Archive readonly = PASS
Runtime config THIS RUN = PASS
Maintenance fresh immediately pre-swap = PASS
Candidate A first/restart = ready=true; 19/19 + 17/17 twice
Candidate A final stabilization = PASS; four stable samples; WAL/SHM absent
Candidate B backend-opened = NO; validation = PASS; rename = PASS
A0/B0 equivalence = PASS
ALL PRE_SWAP GATES = PASS
perform_production_cutover = NOT_CALLED
Production DB touched = NO
```

New regression results:

```text
focused = 55 passed
schema/migration/runtime = 135 passed
V3 = 37 passed
full suite = 273 passed
failed = 0
errors = 0
blocked = 0
```

Independent Production audit after the dry-run remained Legacy V3: 41 tables,
schema 16, integrity `ok`, zero foreign-key violations, healthy Legacy on
8787, and `runtime-startup.json` absent. This closure does not authorize a
future Production swap.

## CANDIDATE_A_FORMAL_EVIDENCE_STABILIZATION_CLOSURE_2026-08-28

The prior `T03FINAL-20260828T122832Z-bab2dd19` pre-swap abort is retained as
historical evidence. Its formal Candidate A SHA was captured before the
isolated SQLite WAL/checkpoint lifecycle had fully stabilized:

```text
recorded formal SHA = 1682c25313356186cc7fd5d3ffa0eafb9588bfd94c680bbcb3e6282f0c123681
final stabilized SHA = eb98fedc0d087dd0ea3526e1670b721e3eb5b88af4588af07cb819a88b703155
logical/domain/PK/row-accounting state = unchanged after cleanup
```

Fresh byte-level evidence proved legitimate Candidate A WAL activity and a
final evidence timing defect, not a hidden migration or Candidate B write.
The formal harness now waits for isolated port FREE, requires closed fixture
cleanup, executes a non-busy `wal_checkpoint(TRUNCATE)`, requires WAL/SHM
absence and stable physical samples, then binds the final SHA. Candidate A
physical SHA remains artifact-integrity evidence; semantic equivalence remains
source/revision/implementation/schema/logical/PK/row-accounting based.

Closure report:

```text
docs/T03_CANDIDATE_A_EVIDENCE_STABILIZATION_CLOSURE.md
```

Fresh isolated certification passed Candidate A first/restart readiness,
19/19, 17/17, A0/A1 logical NONE, Candidate A rename, Candidate B unopened
validation/rename, A0/B0 equivalence, and aggregate pre-swap dry-run. The dry
run did not call `perform_production_cutover`; production remains Legacy V3.

```text
focused stabilization regressions = 50 passed
schema/migration/runtime = 130 passed
V3 = 37 passed
post-cutover DB contract = 1 passed
Git safety = 10 passed
full suite = 268 passed
production replacement = NO
runtime-startup.json = ABSENT
```

## V5 readiness closure — 2026-08-28

The blocker from the failed run is now positively identified as
`V5_HTTP_200_BUT_READY_FALSE` caused by a Legacy compatibility readiness
projection failure. `RuntimePersistence.health_payload()` had returned
hard-coded `unbound` capability entries even though the startup config's
read-only Legacy archive contained the healthy OpenCode orchestrator and
Jimeng video bindings used by the established Legacy readiness contract.

The repair is documented in
`docs/T03_V5_PRODUCTION_READINESS_CLOSURE.md`, with the complete predicate
matrix in `docs/T03_V5_PRODUCTION_READINESS_PREDICATE_MATRIX.md`.

The formal readiness harness now requires V5 `ready=true`, and the mode-aware
launcher plus both PowerShell StartTarget validation paths fail closed when a
V5 process returns HTTP 200 but is not ready. A production=true-like isolated
certification passed first start and restart, with 19/19 Workbench routes,
17/17 SH004-SH020 compatibility routes, exact isolated doctor DB, WAL,
foreign keys, busy timeout 5000, integrity, and FK checks all passing. The
invalid-provider negative test also remained false with the exact failing
predicate reported.

```text
READINESS CLOSURE = PASS
PRODUCTION CUTOVER = NOT_PERFORMED
RUNTIME SOURCE OF TRUTH = LEGACY_V3
Production DB replaced = NO
Production DB intentionally migrated = NO
runtime-startup.json = ABSENT
Dual write = NO
Dual source = NO
READY FOR ONE FINAL PRODUCTION CUTOVER RETRY = YES
```

This closure does not authorize or perform another production swap. The
historical rollback and all prior evidence remain retained.

## FINAL_VERIFIED_PRODUCTION_CUTOVER_2026-08-28_ROLLED_BACK

Fresh run:

`T03FINAL-20260828T110620Z-817060f4`

The pre-swap certification passed from a newly checkpointed Legacy source:

```text
FINAL_LEGACY_SHA = 246df9c2ee8216a289c22b5ff6652c9b9c7660a824d5782e7eabc19e80e9a975
FINAL_LEGACY_LOGICAL_SHA = 32f2ce5e06781def72f3873bbfd906855110545cb0b43d2304b7fb9487c0467a
Archive = 5/5 READ_ONLY
Candidate A first/restart = 19/19 + 17/17 twice
Candidate A A0/A1 delta = NONE
Candidate B backend-opened = NO
A0/B0 = source/schema/logical/PK/row accounting PASS
UNKNOWN = 0
UNACCOUNTED = 0
```

The one authorized atomic replacement completed successfully, but the first
real V5 `StartTarget` gate failed because the runtime returned HTTP 200 with
`runtime_mode=v5` while `ready=false` and `status=not_ready`. The mandatory
ready gate was not weakened. The failed V5 canonical DB, startup config, and
WAL sidecars were preserved at:

```text
data/.cutover/T03FINAL-20260828T110620Z-817060f4/failed-v5-production.db
data/.cutover/T03FINAL-20260828T110620Z-817060f4/failed-v5-runtime-startup.json
```

Rollback then passed exactly once:

```text
V5 owner stopped = PID 31956
8787 after V5 stop = FREE
Legacy archive restored = PASS
runtime-startup.json = ABSENT
Legacy canonical = 41 tables / schema 16 / integrity PASS / FK PASS
StartTarget(LEGACY) = PASS
RestoreLegacy = PASS
Installed Task Legacy restart = PASS (PID 24196, LastTaskResult=0)
Second V5 swap = NO
```

Post-cutover V5 restart and V5-state regression were not run after the
mandatory immediate rollback. The existing pre-cutover suites remained
untouched and passed 31 lifecycle-focused, 123 schema/migration/runtime, and
37 V3 tests. No T00-T03 re-audit or T05 work was started.

```text
PRODUCTION CUTOVER = ROLLED_BACK
RUNTIME SOURCE OF TRUTH = LEGACY_V3
ROLLBACK VERIFICATION = PASS
INDEPENDENT FINAL AUDIT = PASS FOR ROLLED-BACK LEGACY STATE
T03 FINAL STATUS = FAIL
READY FOR T00-T03 FINAL INDEPENDENT RE-AUDIT = NO
```

Full evidence is in `docs/T03_PRODUCTION_PORT_OWNERSHIP_CLOSURE.md`. A future
cutover must create a new final archive and use a new elevated maintenance
state; the rolled-back run remains historical evidence only.

## Final Cutover Retry — pre-swap abort (2026-08-27)

The separately authorized Final Production Cutover Retry was stopped during
preflight, before the production service was stopped and before any archive,
candidate, startup configuration, or atomic replacement was created.

```text
HEAD before retry = 8612bd05b394b0d8ecc3a12ee482a521e92628d6
Formal interpreter = D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe
Formal environment gate = PASS
Production cutover = NOT_PERFORMED
Runtime source of truth = LEGACY_V3
Rollback triggered = NO
```

The retry instructions require the exact formal launcher probe to use an
independent Smoke Candidate A and prohibit the backend from ever opening the
final swap Candidate B. The current mandatory cutover implementation requires
the formal-launcher evidence to name the exact final candidate path and also
requires the evidence's persisted runtime configuration to point to that same
candidate:

```text
core/migration/production_environment.py:181
  formal launcher evidence candidate mismatch

core/migration/production_environment.py:200
  formal launcher runtime config candidate mismatch

core/migration/cutover.py:348-353
  perform_production_cutover verifies that evidence against the swap candidate
```

A controlled preflight invocation using Candidate A evidence and Candidate B
as the intended target returned:

```text
ProductionEnvironmentError: formal launcher evidence candidate mismatch
```

Passing the gate would therefore require either opening Candidate B with the
backend, changing the production gate during this no-development retry, or
rewriting evidence so it no longer described the probe that actually ran.
All three are prohibited. This is a concrete cutover-contract blocker, not a
runtime-environment regression. The required `ABORT BEFORE SWAP` rule was
applied without attempting a second path.

Preflight and independent audit evidence:

```text
Formal sys.executable resolved = D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe
sys.prefix resolved = D:\11067\CodexWorkspaces\frameflow-v3\.venv
sys.base_prefix = C:\Users\11067\AppData\Local\Programs\Python\Python314
Python = 3.14.6
jsonschema / SQLAlchemy / Alembic / server-runtime imports = PASS
pip check = PASS
requirements dry-run consistency = PASS
Environment tests = 10 passed, 0 failed
Combined relevant regression = 119 passed, 0 failed, 0 blocked
8787 listener retained = PID 33880
Live health = HTTP 200, runtime_mode legacy, schema_version 16
Canonical schema = LEGACY_V3, 41 tables
Canonical SHA at final audit = 917ecbc9d120b419555a63a6a273a352eede45b6ab04b8b9ea91eb8a41631986
Canonical integrity = ok
Canonical FK violations = 0
data/runtime-startup.json = absent
Production DB staged = NO
Archive staged = NO
```

Current retry verdict:

```text
T03 FINAL STATUS = FAIL
PRODUCTION CUTOVER = NOT_PERFORMED
RUNTIME SOURCE OF TRUTH = LEGACY_V3
READY FOR T00-T03 FINAL RE-AUDIT = NO
```

The remainder of this document preserves the prior rolled-back cutover attempt
as historical evidence.

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

## POST_CUTOVER_FULL_REGRESSION_LEGACY_CANONICAL_ASSUMPTION

The later T03 test-architecture closure retained the recorded failed-V5 and
rollback evidence from `T03FINAL-20260828T043608Z-bbfd9415` and made no new
production cutover attempt. It established that the post-swap regression
failure was a test-only canonical-as-Legacy assumption, not a V5 runtime,
port-ownership, migration-determinism, environment, or R3E defect.

Tests now construct an explicit Legacy fixture, a distinct V5 fixture, and a
distinct Legacy readonly source below `FRAMEFLOW_TEST_TMP`. The exact full
regression passed both in the current Legacy rollback state and with an
isolated V5 canonical simulation: `117 passed` in each state. The V3
specialized regression passed `37 passed`. See
`T03_FULL_REGRESSION_DB_ASSUMPTION_MATRIX.md` and
`T03_FULL_REGRESSION_DB_DECOUPLING.md` for the 31-entry failure inventory and
independent test-architecture audit.

## ELEVATED_REAL_LEGACY_LIFECYCLE_CERTIFICATION_2026-08-28

The elevated real Legacy lifecycle certification was completed after the
mode-aware service Action had already been installed. No production V5
replacement, migration, Candidate B use, or T05 work was performed.

Evidence:

```text
State = data/.cutover/T03-LUNA-ELEVATED-REAL-20260828T145000Z.json
Administrator controller = TRUE
runtime-startup.json = ABSENT
Production canonical = D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db
Production schema = LEGACY_V3 / 16
Production tables = 41
Production integrity = PASS
Production FK = PASS (0 violations)
```

Real lifecycle result:

```text
Enter = PASS
  real verified entry owner 39756 stopped by exact PID
  maintenance token created; both maintenance Tasks disabled
  repeated classifier observations = FREE; no respawn
StartTarget = PASS
  formal mode-aware launcher; expected/actual = LEGACY/LEGACY
  owner 27184; one 8787 listener; health ready; doctor DB canonical
RestoreLegacy = PASS
  policy-only; original Enabled policy restored; no start operation
Installed Task restart = PASS
  verified owner 27184 stopped exactly; 8787 FREE
  Start-ScheduledTask executed; LastRunTime 2026-08-28 18:49:28; result 0
  owner 32516; one listener; runtime_mode legacy; health ready; doctor DB canonical
```

The installed `FRAMEFLOW-V3-Service` Action was independently rechecked as
mode-aware: `run-hidden.vbs` invokes `start-frameflow-stack.ps1 -RuntimeOnly`.
Its trigger count remained zero, RunLevel remained Highest, and the current
Task XML SHA-256 was
`074CAA623F9A5C8FC165F73204061E121C78952DBF87BABD7BCABD6007273D3C`.
The live port classifier returned `FRAMEFLOW_SUPERVISED` with exactly one
listener.

This turn's isolated and regression results were:

```text
V5 first/restart = PASS/PASS
V5 Workbench = 19/19 then 19/19
V5 SH004-SH020 = 17/17 then 17/17
Invalid V5 config fail-closed = PASS
Foreign owner / unknown owner / PID race / repeated FREE = PASS
Lifecycle-focused tests = 31 passed, 0 failed/errors/blocked
Schema/migration/runtime = 123 passed, 0 failed/errors/blocked
V3 regression = 37 passed, 0 failed
Post-cutover DB contract = PASS
```

Independent final decision:

```text
STATUS = PASS
PRODUCTION CUTOVER = NOT_PERFORMED
RUNTIME SOURCE OF TRUTH = LEGACY_V3
Production DB replaced = NO
Production DB intentionally migrated = NO
Dual write = NO
Dual source = NO
READY FOR FINAL PRODUCTION CUTOVER = YES
```
