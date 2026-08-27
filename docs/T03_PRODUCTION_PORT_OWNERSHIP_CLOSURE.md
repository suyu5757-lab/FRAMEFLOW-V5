# FRAMEFLOW V5.3.2 — Production Port Ownership Closure

Date: 2026-08-27

Branch: `dev/v5.3.2`

HEAD before repair: `5269824f9e2a830d84094b3779fdb51a741b1159`

Production cutover performed: **NO**

Runtime source of truth: **LEGACY_V3**

## Executive Summary

The previous production V5 launcher did not fail because the Legacy backend
respawned after a successful shutdown. PID 39204 had never been stopped. The
cutover preflight used `Get-NetTCPConnection -ErrorAction SilentlyContinue`
from a token that could not see the elevated listener and interpreted the empty
result as `8787 = FREE`. `netstat -ano` later proved the existing listener.

PID, scheduled-task, process-creation, doctor, and startup-log evidence
positively identifies PID 39204 as the formal FRAMEFLOW Legacy Uvicorn worker
started by `FRAMEFLOW-V3-Service`, which was invoked by the logon-triggered
`FRAMEFLOW Runtime Startup` task.

The repaired maintenance lifecycle uses unprivileged `netstat` PID discovery,
application identity proof, an elevated exact-PID controller, a TTL maintenance
token, and temporary disabling of both exact FRAMEFLOW tasks. Cutover now
requires saved repeated-FREE evidence plus two live port probes, including one
immediately before replacement. Foreign and unknown owners fail closed.

Real Windows integration stopped the formal Legacy owner, proved four
consecutive FREE observations with no replacement PID, proved both task and
stack launch paths were blocked, and restored the original task states and a
healthy Legacy runtime under a new PID.

## PID 39204 Identity

```text
PID = 39204
Name = python.exe
Session = 7
Creation = 2026-08-27 20:04:55
PPID = 3836
```

The process executable and command line were hidden from the non-elevated CIM
query, but the identity is established by four independent facts:

1. `FRAMEFLOW-V3-Service` LastRunTime is exactly 20:04:55.
2. Its action is
   `D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8787` with the project root as working directory.
3. PID 39204 and parent 3836 were both created at 20:04:55.
4. The live doctor endpoint reported the exact project `web\dist` and canonical
   `data\frameflow.db` paths.

An elevated reproduction of the identical task chain exposed the normally
hidden fields directly:

```text
worker executable = C:\Users\11067\AppData\Local\Programs\Python\Python314\python.exe
worker command = "D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe" -m uvicorn server:app --host 127.0.0.1 --port 8787
parent executable = D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe
parent command = same Uvicorn command
```

PID 39204 is therefore the base-Python worker launched through the project
`.venv` redirector, not a foreign Python workload.

## Parent Process Chain

```text
FRAMEFLOW Runtime Startup (logon scheduled task, 20:04:40)
  -> start-frameflow-stack.ps1
     -> Start-ScheduledTask FRAMEFLOW-V3-Service (20:04:55)
        -> wscript.exe + run-hidden.vbs (exited after asynchronous Shell.Run)
           -> PID 3836: project .venv Python redirector
              -> PID 39204: base Python Uvicorn worker, owner of 8787
```

The original wscript parent had already exited when audited, but the scheduled
task action, LastRunTime, startup log, and synchronized Python creation times
close the chain.

## Port Ownership Timeline

Previous failed cutover:

```text
T0 20:04:40  logon stack task started
T1 20:04:55  FRAMEFLOW-V3-Service task invoked
T2 20:04:55  Python PIDs 3836/39204 created
T3 20:04:57  Legacy health ready on 8787
T4 cutover    Get-NetTCPConnection false-negative returned no owner
T5 cutover    no stop request was sent to PID 39204
T6 post-swap  formal V5 launcher failed bind with WinError 10048
T7 rollback   Legacy database and runtime ownership restored
```

Final integration:

```text
T0 owner PID 38132, positively identified FRAMEFLOW
T1 elevated maintenance controller wrote TTL token and disabled both tasks
T2 exact owner stop requested
T3 samples 0-3: owner NONE, no respawn
T4 direct scheduled-task start blocked
T5 direct stack start blocked by maintenance token
T6 restore moved token to evidence and enabled only the service task
T7 formal service started PID 33312 and passed doctor/health
T8 logon startup task restored to its original Enabled state
```

## Service, Task, Watchdog, and Startup Audit

- No Windows Service launches FRAMEFLOW or owns PID 39204.
- No HKCU/HKLM Run entry launches FRAMEFLOW.
- `FRAMEFLOW Runtime Startup` has the sole automatic logon trigger.
- `FRAMEFLOW-V3-Service` has zero triggers and is on-demand.
- Both tasks specify `RestartOnFailure`, but their wscript action returns after
  `Shell.Run(..., wait=False)`. Task Scheduler therefore does not supervise or
  restart the detached Python backend.
- No project watchdog or continuous recovery loop was found.

Automatic backend respawn after an exact stop was not observed. The competing
automatic start source was the logon task; it is now maintenance-controlled.

## Actual Root Cause

Classification: **SCHEDULED_TASK / STALE_PROCESS**.

The formal scheduled-task backend remained alive because the cutover used a
permission-sensitive listener query and never invoked a real shutdown
lifecycle. Task state was also misleading: the task showed `Ready` while its
detached Python child continued running. Checking only task state or an old PID
is therefore insufficient.

## Why the Previous Shutdown Gate Missed It

- Errors and access restrictions from `Get-NetTCPConnection` were suppressed.
- Empty cmdlet output was treated as proof of a free port.
- No `netstat` owner cross-check existed.
- No doctor/process identity classification existed.
- No elevated exact-PID shutdown occurred.
- No repeated port-owner observation occurred.
- The logon task and service task were not paused for maintenance.
- The final V5 launcher discovered the conflict only after the database swap.

## Repair

### Port ownership module

`core/migration/port_ownership.py` provides:

- `netstat -ano` listener parsing;
- process, parent, doctor, and task-source evidence;
- `FREE`, `FRAMEFLOW_EXPECTED`, `FRAMEFLOW_STALE`,
  `FRAMEFLOW_SUPERVISED`, `FOREIGN_PROCESS`, and `UNKNOWN` classifications;
- repeated-FREE evidence validation;
- PID-change detection;
- maintenance-source state validation;
- lifecycle restoration validation.

### Maintenance controller

`scripts/frameflow-maintenance.ps1`:

1. Requires elevation before stopping an elevated backend.
2. Records exact task/action/owner/parent/doctor state.
3. Creates a two-hour TTL maintenance token.
4. Temporarily disables only `FRAMEFLOW Runtime Startup` and
   `FRAMEFLOW-V3-Service`.
5. Stops only a positively identified FRAMEFLOW owner PID.
6. Records repeated port observations and fails on any new PID.
7. On restore, moves the token to evidence, restores original task Enabled
   states, starts the same formal service task, and verifies doctor/health.

It never kills all Python processes.

### Stack launcher

`scripts/start-frameflow-stack.ps1` now validates the TTL maintenance token at
entry and immediately before starting the backend task. An active or malformed
token fails closed. An expired valid token is stale-safe and no longer blocks
startup; task disabling remains the primary maintenance exclusion.

### Cutover gate

`perform_production_cutover` now requires:

- complete repeated-FREE maintenance evidence;
- proof that both startup sources are paused;
- a live FREE observation after formal Candidate gates;
- a second live FREE observation immediately before any config write or
  `os.replace`.

Any failure occurs before production mutation.

## Maintenance Lifecycle

```text
NORMAL
  -> inspect/classify owner
  -> ENTER_MAINTENANCE (elevated)
  -> TTL token ACTIVE
  -> exact tasks DISABLED
  -> verified FRAMEFLOW owner STOPPED
  -> repeated owner samples FREE
  -> PRE_SWAP_READY
  -> P3 live FREE immediately before swap
  -> future P4 live FREE after swap/before launcher
  -> RESTORE/START desired runtime
  -> service health verified
  -> startup task restored
  -> NORMAL
```

Rollback uses the same `Restore` path after Legacy DB/config restoration.

## Port Ownership State Machine

- `FREE`: allowed only with maintenance sources paused.
- `FRAMEFLOW_EXPECTED`: may be stopped only by the elevated exact-owner path.
- `FRAMEFLOW_SUPERVISED`: same, plus supervisor/task evidence must be paused.
- `FRAMEFLOW_STALE`: may be stopped only after project-path proof.
- `FOREIGN_PROCESS`: blocked; never killed.
- `UNKNOWN`: blocked; never killed.

## Fail-Closed and Foreign-Process Behavior

An owner with a foreign executable/command is `FOREIGN_PROCESS`. Missing
identity that cannot be closed by FRAMEFLOW doctor/task evidence is `UNKNOWN`.
Both fail the gate before any database or startup-config change. Only an exact
FRAMEFLOW owner with matching doctor paths can be stopped.

## TOCTOU Protection

The primary protection is removal of the start sources throughout maintenance:
both tasks are Disabled and the direct stack path is token-blocked. Repeated
FREE samples detect immediate replacement owners. Cutover then probes once
after all formal gates and again immediately before replacement. A PID or owner
change fails before `os.replace`. P4 remains a mandatory operator check after a
future swap and before enabling/starting the formal service task.

## Windows Integration Evidence

Final evidence:

`D:\11067\CodexWorkspaces\frameflow-v3\.tmp\tests\port-ownership-integration-final-20260827T1520.json`

```text
Controller elevated = YES
Entry owner = PID 38132, FRAMEFLOW doctor matched
Tasks during maintenance = Disabled / Disabled
Port samples = 4/4 FREE
Respawn detected = NO
Direct task start = BLOCKED
Direct stack start = BLOCKED
Restore = PASS
Restored owner = PID 33312
Restored classification = FRAMEFLOW_SUPERVISED
Legacy health = version 3.0.0, schema 16, ready=true
Task Enabled states restored = YES
Maintenance token remaining = NO
```

## Automated Tests

```text
port ownership tests = 12 passed
production environment + runtime startup + equivalence + handles = 43 passed
V3 regression = 37 passed
unique relevant total = 92 passed
failed = 0
blocked = 0
```

## Production DB Safety

```text
Production DB replaced = NO
Atomic replacement = NOT_PERFORMED
Runtime source = LEGACY_V3
Tables = 41
Schema version = 16
Integrity = ok
Foreign-key violations = 0
Production DB intentionally modified = NO
runtime-startup.json = absent
Dual write = NO
Dual source of truth = NO
```

Normal Legacy startup may update provider runtime state; no migration,
candidate, transaction fixture, or deliberate remediation write targeted the
production database.

## Independent Review

1. PID 39204 identity is positively tied to the formal task and project.
2. Parent/launcher/task chain is proven by time-aligned evidence.
3. No service, watchdog, or registry startup source was found.
4. The false-negative listener query is replaced by netstat ownership.
5. Elevated ownership is required and tested.
6. Automatic and on-demand task sources are disabled during maintenance.
7. Direct stack startup is independently token-blocked.
8. No automatic replacement PID appeared during the final observation window.
9. Foreign and unknown owners cannot be killed by the controller.
10. A live PID change before swap leaves production untouched.
11. Restore returned tasks and Legacy health to their original lifecycle.
12. No production DB replacement occurred.

Independent review: **PASS**.

## Remaining Risks

- A future production cutover controller must run elevated; a non-elevated
  controller fails before token/task/process mutation.
- If an elevated controller crashes, tasks remain disabled and startup remains
  blocked until the saved state is restored. This is fail-safe but can leave the
  application offline.
- The maintenance token expires after two hours for stale-lock safety. A longer
  maintenance window must create a fresh state rather than silently extending
  an old token.
- P4 must still be recorded after the future atomic swap and before the formal
  service task is re-enabled and started.

## Final Verdict

```text
STATUS = PASS
PRODUCTION CUTOVER = NOT_PERFORMED
RUNTIME SOURCE OF TRUTH = LEGACY_V3
ROOT CAUSE FIXED = YES
READY FOR FINAL PRODUCTION CUTOVER = YES
```

The stop rule was honored. No new final archive, startup config, database
replacement, or T05 work was performed.
