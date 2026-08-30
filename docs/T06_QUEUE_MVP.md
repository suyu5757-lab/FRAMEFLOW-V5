# FRAMEFLOW V5.3.2 — T06 Queue MVP

## Responsibility

`core/runtime/queue.py` provides the persistent `TaskQueue` facade over the
T05 `TaskStore`. Queue state is not held in a Python list, deque, priority
queue, or global dictionary; the canonical source remains the V5 `tasks`
table.

The Queue supports enqueue, read-only peek, queued count, atomic claim,
pending cancellation, and bounded retry eligibility. It does not execute a
Task or call any provider.

## Ordering and claim semantics

Larger `priority` values are higher priority. Ties are deterministic:

```text
priority DESC, created_at ASC, id ASC
```

`claim_next()` acquires a SQLite `BEGIN IMMEDIATE` transaction, selects the
first `QUEUED` row using that ordering, and conditionally changes it to
`RUNNING` in the same transaction. A competing consumer therefore cannot
claim the same row. Claim does not increment `attempt`; `attempt` counts
execution starts and belongs to the future Worker boundary.

## Cancellation and retry

`CREATED` and `QUEUED` Tasks may be changed to `CANCELLED`. A cancelled Task
is never eligible for peek or claim. T06 does not provide process
cancellation for `RUNNING` Tasks.

`FAILED` and `INTERRUPTED` Tasks may be requeued only when both
`attempt < max_attempts` and `attempt < 3`. Requeue does not increment
`attempt`; queue placement is not an execution attempt. There is no backoff,
retry planner, provider reconciliation, or recovery orchestration.

## Boundaries and safety

The Queue reuses the existing StateStore connection policy:
`journal_mode=WAL`, `foreign_keys=ON`, and `busy_timeout=5000`. No migration,
new tasks table, second Task model, production schema change, or canonical DB
initialization is performed. T06 tests use isolated temporary databases.

T07 owns worker execution and attempt-start behavior. Resource locks,
provider idempotency, EventLog orchestration, Supervisor, Recovery, and
Manifest/Retention remain outside T06.
