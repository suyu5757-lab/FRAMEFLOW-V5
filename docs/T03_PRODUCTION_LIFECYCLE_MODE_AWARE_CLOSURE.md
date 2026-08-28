# FRAMEFLOW V5.3.2 — Production Lifecycle Mode-Aware Closure

Date: 2026-08-28
Branch: `dev/v5.3.2`
HEAD before this repair: `a5a9af0957dce30ac825d154cfae06625c43ba7f`
Production cutover performed in this repair: **NO**
Runtime source of truth: **LEGACY_V3**

## Executive Summary

The latest failed run reached a successful atomic V5 database replacement, but
the post-swap lifecycle did not establish a verified V5 process. The failure
was in the maintenance/task lifecycle, not migration, candidate equivalence,
SQLite replacement, or port ownership.

The code repair separates these two meanings:

1. `StartTarget` explicitly resolves and starts the runtime selected by the
   current startup configuration, then verifies port ownership, doctor database
   identity, health, and `runtime_mode`.
2. `RestoreAutostartPolicy` only restores the previous Scheduled Task Enabled
   states after the target process is already verified.
3. `RestoreLegacy` is the rollback-specific policy operation and requires that
   the explicitly started target is Legacy.

The production launcher is now mode-aware. An absent implicit default
`data/runtime-startup.json` selects Legacy; a present V5 configuration is
validated fail-closed against the V5 database and read-only Legacy archive.
The isolated Windows launcher integration passed first start, restart, 19/19
Workbench API checks, 17/17 Legacy compatibility checks, and invalid-config
fail-closed behavior.

The final real Task Scheduler Action update and the new real Legacy
`Enter -> StartTarget -> RestoreAutostartPolicy` integration were attempted
under the explicit authorization in this task. The first Codex-host attempts
had no administrator token (`IsAdministrator=False`) and produced no
successful mutation; the operator then completed the exact Action-only update
from Administrator PowerShell. The remaining real Legacy lifecycle still
requires an elevated controller, so this document does not yet claim final
production readiness.

## Latest Failed Cutover

Run: `T03FINAL-20260828T052147Z-bed3dc7b`

Evidence files were preserved under:

`data/.cutover/T03FINAL-20260828T052147Z-bed3dc7b/`

The run proves:

- atomic replacement: PASS;
- resulting V5 canonical database: 12 tables, integrity `ok`, FK violations 0;
- persisted V5 startup configuration: present and valid;
- P4 8787 observation: FREE;
- V5 formal isolated candidate evidence: first/restart 19/19 and 17/17;
- lifecycle restore gate: failed to establish the expected V5 listener;
- rollback: PASS;
- final canonical database: Legacy V3, 41 tables, schema version 16;
- final `runtime-startup.json`: absent.

## Failure Timeline

The timestamps below are from the preserved run evidence. The run used UTC
timestamps in JSON; Task Scheduler display times are local Windows time.

```text
T0  2026-08-28T05:22:51.2109423Z  Enter maintenance; owner PID 31688 recorded
T1  2026-08-28T05:22:51.2191374Z  TTL maintenance token created; both tasks disabled
T2  2026-08-28T05:22:51.3984396Z  owner stop observed; 8787 FREE sample 0
T3  2026-08-28T05:22:51.6732769Z  8787 FREE sample 1
T4  2026-08-28T05:22:51.9627662Z  8787 FREE sample 2
T5  2026-08-28T05:22:52.2308088Z  8787 FREE sample 3; no respawn
T6  2026-08-28T05:24:31.159749Z   V5 runtime-startup.json prepared
T7  2026-08-28T05:24:31+Z          atomic V5 replacement completed; P4 was FREE
T8  2026-08-28T05:24-05:26Z        Restore/lifecycle start did not establish V5 8787 health
T9  2026-08-28T05:26:30.567927Z   failed V5 DB backed up for rollback
T10 2026-08-28T05:28:30.3160667Z  rollback maintenance state entered
T11 2026-08-28T05:32:47.0556567Z  historical Restore evidence recorded owner PID 39756
T12 after rollback                      Legacy DB/config restored; final health HTTP 200
```

The preserved final-run summary identifies the lifecycle blocker as:

`Formal maintenance Restore did not reclaim port 8787; direct non-UAC elevation reports Enable-ScheduledTask access denied; UAC wrapper did not execute/create its result file.`

The recorded state eventually contains `Restored=true` and PID 39756, but the
cutover controller had already failed its V5 listener/health gate. That timing
also demonstrates why a policy/task result must not be treated as proof that
the intended runtime is serving traffic.

## Scheduled Task Audit

The elevated read-only Task Scheduler audit found these production tasks:

| Task | Trigger | Action | Working directory | Run level |
| --- | --- | --- | --- | --- |
| `FRAMEFLOW Runtime Startup` | `LogonTrigger` (`AtLogOn`) | `wscript.exe -> run-hidden.vbs -> powershell.exe -> start-frameflow-stack.ps1 -OpenBrowser` | `D:\11067\CodexWorkspaces\frameflow-v3` | `HighestAvailable` |
| `FRAMEFLOW-V3-Service` | no trigger; on demand | `wscript.exe -> run-hidden.vbs -> .venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8787` | `D:\11067\CodexWorkspaces\frameflow-v3` | `HighestAvailable` |

Both tasks use `InteractiveToken`, `MultipleInstancesPolicy=IgnoreNew`,
`ExecutionTimeLimit=PT0S`, and `StartWhenAvailable=true`. Their XML declares
`RestartOnFailure` with count 3 and interval 1 minute, but the hidden runner
uses asynchronous `WScript.Shell.Run(..., wait=False)`, so the detached worker
is not actually supervised by the task process.

The `AtLogOn` trigger proves the key distinction:

```text
Enable-ScheduledTask != Start-ScheduledTask
Start-ScheduledTask != verified process health
verified process health != verified target runtime mode
```

Re-enabling an `AtLogOn` task does not fire its logon trigger immediately. The
service task has no trigger at all, so enabling it cannot start anything.

The task name `FRAMEFLOW-V3-Service` is a historical name only. The repository
repair keeps that name to avoid ACL/reference churn. The narrow updater
`scripts/update-frameflow-service-task.ps1` changes only that task's Action to
the mode-aware launcher and preserves its triggers, principal, and settings.
The first updater attempt was executed but Windows returned `Access Denied`; the
before and after XML SHA-256 values were identical, proving no partial mutation.

## Real Installed Task Activation Attempt

Evidence root:

`data/.cutover/T03LIFECYCLE-20260828T062801Z-3813598a/`

The updater was audited and executed with the exact authorized scope:

```text
target = FRAMEFLOW-V3-Service only
API = Set-ScheduledTask -Action
unrelated task mutation = NO
ACL widening = NO
database operation = NO
```

The host reported:

```text
Codex process IsAdministrator = False
Set-ScheduledTask = Access Denied
UAC RunAs confirmation = not returned
task update executed successfully = NO
```

The preserved XML comparison is:

```text
before SHA256 = 1B70D542B930731BE830C1C1595FF642C1A0E48A252B485187B85F826D3B1766
after SHA256  = 1B70D542B930731BE830C1C1595FF642C1A0E48A252B485187B85F826D3B1766
byte-identical = YES
installed mode-aware = NO
```

At that failed attempt the task remained Enabled/Ready with its original direct
Uvicorn Action. No trigger, principal, run level, settings, ACL, process, or
database state was changed by the failed attempt.

### Manual Task Action update confirmation

The operator subsequently ran the updater successfully from an Administrator
PowerShell. A fresh independent export proved:

```text
installed mode-aware Action = YES
Task name unchanged = YES
Trigger unchanged = YES
Principal unchanged = YES
RunLevel unchanged = YES
Settings unchanged = YES
Task XML safety diff = PASS
```

The after XML is preserved as
`data/.cutover/T03LIFECYCLE-20260828T062801Z-3813598a/task-after-manual-update.xml`.

## Launcher Audit

### Before repair

`scripts/start-frameflow-stack.ps1`:

- did not read or validate `runtime-startup.json` itself;
- checked only the frontend path and canonical database path through doctor;
- logged and named its health gate `FRAMEFLOW V3`;
- started `FRAMEFLOW-V3-Service` as a separate Scheduled Task;
- could therefore validate a canonical listener without checking the expected
  runtime mode;
- used a permission-sensitive `Get-NetTCPConnection` probe.

The service Action directly invoked Uvicorn and did not inject
`FRAMEFLOW_RUNTIME_CONFIG`. The server could load the implicit default config
when it imported, but task Action semantics did not independently prove the
selected mode or target database.

### After repair in the repository

`scripts/start-frameflow-stack.ps1` now has two explicit roles:

- normal stack role: starts OpenCode, starts the service task, and verifies the
  selected target;
- `-RuntimeOnly` role: directly invokes the formal `.venv` Python module
  `core.runtime.production_launcher`, without relying on a task trigger.

The launcher validates both:

- `health.runtime_mode == expected mode`;
- `/api/system/doctor.database == expected runtime_db`.

The formal module starts:

```text
D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe
  -m uvicorn server:app --host <loopback> --port <port>
```

It removes stale runtime environment fields before creating the child
environment, then injects the persisted config's environment. It verifies a
single listener, HTTP health, runtime mode, and doctor database identity.

## Maintenance Script Audit

### Before repair

`-Mode Restore` did the following:

1. required maintenance state and disabled tasks;
2. moved the maintenance token;
3. enabled `FRAMEFLOW-V3-Service`;
4. if the entry runtime had been listening, called `Start-ScheduledTask`;
5. waited for a 8787 owner and doctor path match;
6. enabled `FRAMEFLOW Runtime Startup`.

It did not resolve the current target config, did not require a target
`runtime_mode`, did not verify health mode, and gave the operation the
misleading semantics of restoring a runtime and restoring a future policy at
the same time.

### After repair in the repository

The interface is now explicit:

```text
Enter
StartTarget
RestoreAutostartPolicy
RestoreLegacy
Inspect
```

`StartTarget` requires both maintenance tasks disabled and 8787 FREE. It
permits one explicit start through the active maintenance token, invokes the
mode-aware launcher, and records verified target mode/database/owner/health.

`RestoreAutostartPolicy` requires `TargetRuntimeStarted=true`, revalidates the
current config and live target, then only restores the original task Enabled
states. It does not call `Start-ScheduledTask`.

`RestoreLegacy` uses the same policy-only operation but requires the explicit
target mode to be Legacy. Rollback must therefore remove/restore the V5 config
first, run `StartTarget`, verify Legacy, and only then run `RestoreLegacy`.

## Cutover Call Graph

### Before repair

```text
maintenance Enter
  -> disable tasks
  -> stop current owner
  -> repeated FREE evidence
perform_production_cutover
  -> write V5 runtime-startup.json
  -> atomic database replacement
external Restore
  -> enable service task
  -> optionally Start-ScheduledTask service
  -> enable logon startup task
  -> assume current runtime is restored
```

The cutover function itself only owns the verified database/config replacement;
the external `Restore` call was the semantic gap.

### After repair

```text
maintenance Enter
  -> TTL token + both tasks disabled
  -> exact current owner stopped
  -> repeated FREE evidence
perform_production_cutover
  -> V5 config + atomic database replacement
  -> P4 FREE evidence
maintenance StartTarget
  -> resolve current config
  -> explicit V5 launcher start
  -> verify owner + doctor DB + health + runtime_mode=v5
maintenance RestoreAutostartPolicy
  -> restore future task Enabled policy only
  -> verify current V5 runtime remains healthy
```

Rollback is intentionally separate:

```text
hold maintenance
  -> stop failed V5
  -> restore Legacy DB
  -> remove/restore V5 startup config
maintenance StartTarget
  -> explicit Legacy launcher start
  -> verify runtime_mode=legacy
maintenance RestoreLegacy
  -> restore future Legacy autostart policy only
```

`core/migration/cutover.py` now documents this contract and explicitly rejects
the interpretation that a database replacement returns a running backend.

## Actual Root Cause

Primary classification:

```text
SUCCESS_ROLLBACK_RESTORE_CONFLATION
TASK_ENABLE_NOT_RUNTIME_START
MODE_UNAWARE_PRODUCTION_LAUNCHER
MAINTENANCE_STATE_MACHINE_DEFECT
```

Exact explanation: the successful swap created V5 ownership state, but the
post-swap operation was still named and implemented as restoration of the
previous task/runtime lifecycle. The automatic startup task was `AtLogOn`, the
service task had no trigger, and the service Action was a direct Legacy-shaped
Uvicorn command. The operation did not have a mandatory, mode-aware,
explicit-start phase followed by a target-mode health gate. Permission failure
in the attempted elevation wrapper made the timing visible, but changing task
Enabled state was never a sufficient V5-start contract.

Answers to the requested Q1-Q8:

1. Before repair `Restore` restored task state and, conditionally, invoked the
   old service task; it did not resolve/verify the current target mode.
2. It was not literally only `Enable-ScheduledTask`; the code did call
   `Start-ScheduledTask` when `RuntimeWasListening` was true. However, the
   operation still treated task state as the lifecycle and the actual failed
   wrapper encountered task permission failure.
3. Yes. The startup task is `AtLogOn`; enabling it does not immediately fire
   it. The service task has zero triggers.
4. Before repair, only the startup task called `start-frameflow-stack.ps1`;
   the service task called the direct Python command.
5. The old PowerShell stack launcher did not read the config. The server could
   read the implicit default config during import, which was not an adequate
   launcher-level contract.
6. Yes, the old stack/action semantics were Legacy/V3-shaped: V3 health/path
   checks and a direct fixed-port Uvicorn service action with no target-mode
   verification.
7. Yes. Success and rollback both used the same ambiguous `Restore` action.
8. Legacy rollback passed because rollback separately restored the Legacy DB,
   removed the V5 config, and ultimately brought up a Legacy process. V5
   startup failed because no equivalent explicit, config-aware V5 start and
   mode gate was guaranteed by the Restore lifecycle.

## Mode-Aware Launcher Contract

```text
implicit default config absent
  -> LEGACY_V3
  -> canonical data/frameflow.db

explicit/default config present, runtime_mode=v5
  -> V5_RUNTIME
  -> valid selected runtime_db
  -> valid distinct Legacy read-only archive

invalid config, missing V5 DB/archive, wrong schema, or invalid archive
  -> fail closed
  -> do not silently start Legacy
```

The child process receives a clean environment. A stale V5 environment cannot
turn an absent Legacy config into an accidental V5 start, and an invalid V5
config cannot silently fall back to Legacy.

## Windows Isolated V5 Integration

The test `tests/runtime/test_mode_aware_launcher_integration.py` invokes the
actual PowerShell launcher with an isolated V5 fixture and a non-8787 port.
It demonstrated:

```text
first start via start-frameflow-stack.ps1 -RuntimeOnly = PASS
first runtime_mode = v5
first Workbench API gate = 19/19
first SH004-SH020 gate = 17/17
stop exact isolated listener = PASS
restart via the same mode-aware launcher = PASS
restart persisted project = PASS
restart Workbench API gate = 19/19
restart SH004-SH020 gate = 17/17
invalid V5 archive config = fail closed
invalid config listener created = NO
```

This is the required isolated equivalent of the real Scheduled Task Action
semantics. The narrow task updater is ready but was not installed on the host.

## Windows Legacy Integration

New semantic Legacy integration was attempted from the Codex host but stopped
before mutation because its controller token was not elevated. The maintenance
script reported `ControllerElevated=False` before creating a token, disabling a
task, or stopping the 8787 owner. The operator's separate Administrator shell
is required to run the remaining lifecycle commands. The pre-existing port ownership
integration in `docs/T03_PRODUCTION_PORT_OWNERSHIP_CLOSURE.md` remains valid
historical evidence for foreign/unknown/PID-race protections, but it used the
old Restore semantics and is not relabeled as proof of this closure.

The current production read-only audit after code changes shows:

```text
canonical = data/frameflow.db
schema = LEGACY_V3
tables = 41
integrity = ok
foreign_key_check = []
runtime-startup.json = absent
8787 listener = PID 39756
live HTTP health = 200, version 3.0.0, ready=true
```

The already-running process predates this code change and its live health
payload does not yet expose the newly-added `runtime_mode=legacy` field. A
restart is intentionally not claimed without the same explicit approval
needed for the real maintenance lifecycle.

## Automated Tests

Executed with the formal interpreter:

```text
D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe
```

Results:

```text
targeted lifecycle + port ownership + startup cutover = 20 passed
schema/migration/runtime regression = 123 passed
V3 regression = 37 passed
post-cutover DB contract = 1 passed
isolated mode-aware V5 wrapper integration = 1 passed
failed = 0
errors = 0
blocked = 0
```

The formal interpreter check, `pip check`, server import, PowerShell parser
checks, existing foreign/unknown/PID-race tests, and isolated invalid-config
test all passed. No skipped or xfailed blocker was added.

## Production Safety

This repair performed no production database replacement and no intentional
production database write. It did not call `perform_production_cutover` with
an authorized replacement path. No archive or `data/.cutover` evidence was
deleted.

```text
Production DB replaced = NO
Production DB intentionally modified by this repair = NO
Production schema = LEGACY_V3
Production tables = 41
Production integrity = PASS
Production FK = PASS
runtime-startup.json = ABSENT
Dual write = NO
Dual source of truth = NO
```

## Independent Lifecycle Audit

| Question | Result | Evidence |
| --- | --- | --- |
| Enable task is distinct from runtime start | PASS | policy-only restore contains no start operation |
| Success has explicit V5 start API | PASS in repository | `StartTarget` + mode-aware launcher |
| Rollback has explicit Legacy start API | PASS in repository | `StartTarget` + `RestoreLegacy` contract |
| Success does not restore Legacy-only runtime state | PASS in repository | target config is resolved and mode-verified |
| Launcher honors runtime-startup | PASS isolated | actual PowerShell wrapper integration |
| Invalid V5 config fails closed | PASS | unit and actual wrapper integration |
| V5 restart stays V5 | PASS isolated | first/restart integration, 19/19 + 17/17 |
| Legacy rollback restart stays Legacy | NOT VERIFIED this turn | real lifecycle approval blocked |
| Foreign/unknown owner fail closed | PASS | existing port ownership regression |
| PID race protection | PASS | existing port ownership regression |
| Real installed service task Action is updated | BLOCKED | host reviewer rejected persistent mutation |
| Production remains completely uncut | PASS | canonical read-only audit and no cutover call |

## Remaining Risks and Blocker

The remaining blocker is operational authority, not an unresolved code defect:

```text
REAL_TASK_ACTION_UPDATE_AND_LEGACY_LIFECYCLE_APPROVAL_REQUIRED
```

Once explicitly approved, the safe completion sequence is:

1. run `scripts/update-frameflow-service-task.ps1` (one task Action only);
2. export and audit the resulting XML;
3. run elevated Legacy `Enter`;
4. run `StartTarget` with absent config and verify `runtime_mode=legacy`;
5. run `RestoreAutostartPolicy`/`RestoreLegacy` and verify tasks stay enabled;
6. restart through the installed mode-aware task Action and verify Legacy;
7. rerun the independent audit.

No production V5 cutover should be attempted until those steps pass.

## Final Verdict

```text
STATUS = PARTIAL
ROOT CAUSE POSITIVELY IDENTIFIED = YES
CODE REPAIR = PASS
ISOLATED V5 LIFECYCLE = PASS
REAL INSTALLED TASK LIFECYCLE = NOT VERIFIED
PRODUCTION CUTOVER = NOT_PERFORMED
RUNTIME SOURCE OF TRUTH = LEGACY_V3
READY FOR FINAL PRODUCTION CUTOVER = NO
```

## Elevated real Legacy lifecycle certification — 2026-08-28

This section records the subsequently authorized elevated certification. The
production V5 cutover remained forbidden and was not attempted.

Evidence state:

```text
Evidence state = data/.cutover/T03-LUNA-ELEVATED-REAL-20260828T145000Z.json
Administrator controller = TRUE
runtime-startup.json = ABSENT
target resolver = LEGACY
canonical = D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db
canonical schema = LEGACY_V3 / version 16
canonical tables = 41
canonical integrity = PASS
canonical foreign_key_check = 0
```

The real lifecycle completed as follows:

```text
Enter = PASS
  entry owner PID 39756 was live-verified, then stopped by exact PID
  maintenance token created
  FRAMEFLOW Runtime Startup and FRAMEFLOW-V3-Service disabled
  8787 = FREE across repeated observations
  respawn = NO

StartTarget = PASS
  formal mode-aware launcher used
  target mode = LEGACY
  target owner PID = 27184
  exactly one 8787 listener
  health = 200 / ready=true
  runtime_mode = legacy
  doctor database = canonical

RestoreLegacy = PASS
  policy-only restore
  both original Task Enabled states restored
  no runtime start delegated to policy restoration

Installed Task restart = PASS
  verified PID 27184 stopped by exact PID
  8787 became FREE
  Start-ScheduledTask FRAMEFLOW-V3-Service executed
  Task LastRunTime = 2026-08-28 18:49:28
  Task LastTaskResult = 0
  restart owner PID = 32516
  exactly one listener, health ready, runtime_mode = legacy
  doctor database = canonical
```

The installed service Action remained mode-aware (`run-hidden.vbs` →
`start-frameflow-stack.ps1 -RuntimeOnly`), with zero triggers, Highest
RunLevel, and unchanged principal/settings. The live ownership classifier
returned `FRAMEFLOW_SUPERVISED`; the single listener was the expected
FRAMEFLOW process. The doctor endpoint reported the canonical database; its
unrelated FFmpeg fields were unavailable and did not affect the requested
runtime/database gate.

This turn also reran the isolated and regression gates:

```text
V5 isolated first = PASS                 Workbench 19/19, SH004-SH020 17/17
V5 isolated restart = PASS               Workbench 19/19, SH004-SH020 17/17
Invalid V5 config fail-closed = PASS     no listener, no Legacy fallback
Port ownership/race suite = PASS         12 passed
Lifecycle-focused suite = PASS           31 passed, 0 failed/errors/blocked
Schema/migration/runtime = PASS           123 passed, 0 failed/errors/blocked
V3 regression = PASS                      37 passed, 0 failed
Post-cutover DB contract = PASS           1 passed
```

Independent final audit:

```text
Production DB replaced = NO
Production DB intentionally migrated = NO
Production source of truth = LEGACY_V3
Production final 8787 = exactly one expected supervised owner
Production final health = PASS
Production final runtime = LEGACY
Dual write = NO
Dual source of truth = NO
```

```text
STATUS = PASS
REAL INSTALLED TASK LIFECYCLE = VERIFIED
PRODUCTION CUTOVER = NOT_PERFORMED
READY FOR FINAL PRODUCTION CUTOVER = YES
```
