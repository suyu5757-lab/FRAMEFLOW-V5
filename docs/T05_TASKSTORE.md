# FRAMEFLOW V5.3.2 — T05 TaskStore

## Responsibility

`core/runtime/state_store/task_store.py` provides the typed persistence
boundary for the existing V5 `tasks` table. It creates, reads, updates, and
filters Task rows while serializing `payload`, `result`, and `error` at the
JSON boundary. Lifecycle timestamps, worker identity, and attempt values are
stored exactly as supplied by the caller.

The implementation reuses `StateStore.connection()` and
`StateStore.transaction()`. It does not create another SQLite engine,
connection policy, schema, or migration.

## TaskState contract

The only accepted T05 states are:

```text
CREATED
QUEUED
WAITING_FOR_RESOURCE
RUNNING
SUCCEEDED
FAILED
INTERRUPTED
CANCELLED
```

T05 validates state values but does not implement a transition engine. A
caller may persist a valid state; queue scheduling, worker execution, retry
orchestration, provider submission, resource locks, and EventLog behavior
remain later-task responsibilities.

## Database and production boundary

No migration or schema change is required. The existing `tasks` contract is
used as declared by `core/schemas/runtime_mvp.py`: `project_id` remains
required, `shot_id` remains nullable, and the database check constraint
rejects states outside the contract. All writes use the established WAL,
foreign-key, and busy-timeout StateStore configuration. T05 tests use isolated
temporary databases and never write fixture Tasks to the canonical production
database.

## T06 integration boundary

T06 may use `TaskStore.list(status=..., project_id=..., shot_id=...)` to find
persisted work. Scheduling, dequeue ordering, claiming, worker leases, and
execution remain outside this interface.
