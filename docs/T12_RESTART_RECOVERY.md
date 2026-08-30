# FRAMEFLOW V5.3.2 — T12 Restart Recovery

## Responsibility and canonical startup order

T12 reconciles orphaned Runtime execution after a cold Workbench restart.  It
uses the existing in-process Worker assumption: Worker instances from the
previous Python process cannot survive into the new process.

The canonical V5 hook is `server.py:lifespan()`:

```text
create_runtime_persistence()
        ↓
RestartRecovery(TaskStore(runtime.store)).recover_startup()
        ↓
application.state.persistence = runtime
        ↓
yield / Runtime accepts requests
```

The V5 StateStore is opened and its existing schema/PRAGMA contract is
validated before recovery.  Recovery completes before the lifespan yields;
if recovery cannot commit every required interruption, it raises
`RecoveryError`, disposes the runtime, and does not expose a ready service.

## Cold-start contract

`RestartRecovery.recover_startup()` scans only Tasks whose status is
`RUNNING`.  With an empty active-worker set, each such Task is reconciled as:

```text
RUNNING → INTERRUPTED
```

The transition:

- preserves `attempt` unchanged;
- preserves the previous `worker` value as audit evidence;
- sets `finished_at` to the UTC recovery timestamp;
- writes structured `error_json` with `code`, `reason_code`, `message`,
  `retryable`, `previous_worker`, and `recovered_at`;
- appends the T10 `TASK_STATE_CHANGED` event with
  `RUNNING → INTERRUPTED` and the reason code.

Missing worker ownership uses `missing_worker_owner`.  A non-empty worker ID
from the previous process uses `runtime_restart_interrupted`.

`interrupt_running_if()` is the canonical TaskStore compare-and-set primitive.
It re-checks that the Task is still `RUNNING` and that its observed worker
still matches, then updates the Task and appends the EventLog fact in one short
transaction.  If the event insert fails, the Task remains `RUNNING` and no
interruption event is persisted.

## Idempotency and explicit retry

The second startup scans no already-interrupted Task, so it creates no second
mutation and no duplicate interruption event.  T12 never changes
`INTERRUPTED → QUEUED` automatically.  A caller may explicitly use the
existing T06 `TaskQueue.retry()` path; that transition preserves `attempt`, and
the next real Worker execution increments `attempt` exactly once.

One controlled `reconcile_running_tasks(active_worker_ids)` seam exists for
tests or a future active-worker registry.  A worker ID in that set is
preserved as `RUNNING`.  Canonical cold startup always uses an empty set.

## Safety boundaries

Recovery does not scan or mutate non-`RUNNING` Tasks.  It does not release
ResourceLocks, modify Provider Submissions, call a Provider, start or kill a
Creative App, emit Supervisor events, or infer Task ownership from
`payload_json`, Task type strings, or Creative App process names.

The optional `Supervisor.snapshot()` is read-only diagnostic evidence in the
recovery report.  It does not decide which Task is interrupted because T11 has
no frozen Task-to-process mapping.

No recovery table, worker registry, Task column, migration, or schema change is
introduced.  The report is an in-memory startup diagnostic containing
`observed_at`, `running_scanned`, `interrupted`, `preserved`, `errors`, and the
diagnostic Supervisor snapshot.

All tests use isolated Runtime databases and isolated startup configuration.
The canonical production database and legacy archive are read-only validation
targets only.
