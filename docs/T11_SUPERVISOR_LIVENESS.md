# FRAMEFLOW V5.3.2 — T11 Supervisor Liveness

## Responsibility

`core/runtime/supervisor/` provides a point-in-time, read-only observation of
the three frozen Creative App targets.  It answers whether an allowlisted
process identity is currently observable; it does not manage the process or
Runtime state.

The accepted typed targets are:

```text
PHOTOSHOP
AFTER_EFFECTS
RESOLVE
```

Their exact Windows executable identities are:

```text
PHOTOSHOP    -> Photoshop.exe
AFTER_EFFECTS -> AfterFX.exe, aerender.exe
RESOLVE      -> Resolve.exe
```

The names are matched as normalized executable basenames, case-insensitively.
Substring matches such as `FakePhotoshop.exe` and `ResolveHelperFake.exe` do
not qualify.  `AfterFX.exe` and `aerender.exe` are both evidence for the one
`AFTER_EFFECTS` target; T11 does not create separate Resource IDs.

## API and result contract

`Supervisor.probe(target)` observes one `SupervisorTarget`.
`Supervisor.snapshot()` enumerates processes once and returns all three target
results.

Each typed `LivenessResult` contains:

```text
target
state
observed_at
matched_processes
```

`matched_processes` exposes only `pid`, `executable_name`, and an optional
`executable_path`.  It never includes command lines, environments, or
credentials.  `observed_at` is an aware UTC timestamp.  Multiple matches are
valid and returned deterministically by PID.

The states are:

```text
RUNNING     at least one exact allowlisted process is observed
NOT_RUNNING enumeration completed and no exact match is observed
UNKNOWN     the backend could not provide a reliable enumeration
```

An unknown backend result is never converted to `NOT_RUNNING`.

## OS backend and failure handling

`WindowsProcessInspector` uses the already installed lightweight `psutil`
process API when available.  A minimal formal environment without psutil uses
the fixed Windows `tasklist.exe /FO CSV /NH` fallback with `shell=False`; no
caller-controlled command or argument is accepted.  It has no process-start,
process-kill, or termination path.  `ProcessInspector` is a small injectable
protocol used by the fake inspectors in unit tests.

`NoSuchProcess`, `ZombieProcess`, and per-process `AccessDenied` are tolerated
while a point-in-time scan continues.  A backend-level failure or malformed
process record returns `UNKNOWN` with a bounded `enumeration_failed` or
`invalid_process_record` error code.  Process start/exit races are expected;
this is an observation, not a strong OS transaction.

## Runtime and database boundaries

T11 does not open the Runtime StateStore and does not write `tasks`,
`resource_locks`, or `events`.  It does not change TaskState, release locks,
retry work, or emit liveness events.  It does not start, stop, kill, or restart
Photoshop, After Effects, Resolve, or any other process.

`RUNNING` and `NOT_RUNNING` observations do not imply ResourceLock ownership
or Task execution state.  Reconciliation of `RUNNING` Tasks belongs to T12 —
Restart Recovery and is not implemented here.

## Verification

The T11 suite covers all target mappings, exact/case-safe matching, multiple
PIDs, snapshot single-enumeration behavior, process disappearance,
AccessDenied, backend failure, typed-target rejection, database no-side-effect
checks, and a real Windows `psutil` smoke.  The production database and
legacy archive are read-only verification targets only.
