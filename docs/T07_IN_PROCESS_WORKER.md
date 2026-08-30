# FRAMEFLOW V5.3.2 — T07 In-process Worker MVP

## Responsibility and boundaries

`core/runtime/worker.py` implements one synchronous `Worker.run_once()`
operation. It consumes the persistent T06 `TaskQueue`, uses the T05
`TaskStore` for all Task lifecycle writes, invokes one explicitly registered
trusted handler, and returns an explicit idle/success/failure outcome.

The Worker does not create a second queue or persistence layer. It does not
call Seedance, a provider, ComfyUI production generation, Photoshop, After
Effects, Resolve, or any shell command. ResourceLockManager is T08, provider
idempotency is T09, EventLog orchestration is T10, Supervisor is T11, and
restart recovery is T12.

## Handler registry

`HandlerRegistry` is an in-memory allowlist of code-defined callables. A
handler has the form:

```text
handler(task_mapping, execution_context) -> JSON-compatible result
```

There is no `eval`, `exec`, dynamic import path, payload command, or LLM
generated code execution. An unregistered Task type becomes a structured
`FAILED` Task with `handler_not_registered`.

## Ownership and attempt semantics

T06 first atomically changes `QUEUED → RUNNING`. T07 then calls the minimal
TaskStore `begin_execution()` primitive, which atomically requires an
unowned `RUNNING` row and writes:

```text
worker = worker_id
started_at = now
heartbeat_at = now
attempt = attempt + 1
```

The transaction commits before the handler is called. Therefore enqueue,
requeue, and claim do not increment `attempt`; one actual Worker execution
increments it exactly once. Retry requeue clears the previous execution
ownership/timestamps, while preserving the attempt count for the next start.

## Success and failure lifecycle

The normal path is:

```text
QUEUED → RUNNING → begin_execution ownership → handler → SUCCEEDED
```

JSON-compatible handler results cross the serialization boundary before
being stored in `result_json`. Success clears any previous `error_json` and
writes `finished_at`.

Handler exceptions, unknown handlers, timeout signals, and invalid results
are converted into structured errors with `code`, `type`, `message`,
`retryable`, `worker_id`, `attempt`, and `task_type`. Failure writes
`FAILED`, `error_json`, and `finished_at` while preserving execution
ownership evidence. Error messages redact common credential markers.

If finalization itself cannot be committed, the Worker returns
`finalization_failed` and never reports `SUCCEEDED`. If the compensating
failure write also fails, the Task remains visibly `RUNNING` for future
recovery inspection rather than being falsely marked complete.

## Heartbeat and timeout

Execution start initializes `heartbeat_at`. A short-lived heartbeat thread
updates it periodically through a short TaskStore transaction and is joined
before finalization. A handler may also call `context.heartbeat()` directly.
The interval is injectable for tests; the default is five seconds and is
unrelated to the T08 resource-lock lease interval.

Timeout is cooperative. The context exposes a monotonic `deadline`, a
`cancel_event`, and `check_cancelled()`. A cooperative handler must check the
context and stop its own work; the Worker never kills Python threads or
injects asynchronous exceptions. A timed-out cooperative handler becomes
`FAILED` with error code `timeout`. A non-cooperative handler cannot be safely
forced to stop by this in-process MVP and is not represented as safely timed
out while it is still running.

## Transaction boundary

Ownership, heartbeat, and finalization use short transactions. The handler
always executes after the ownership transaction commits and never while a
long-lived SQLite write transaction is held. No migration or production
schema change is required; the existing Task fields are sufficient.

All automated tests use isolated temporary SQLite databases. The canonical
production database and the legacy archive are read-only verification
targets for this task.
