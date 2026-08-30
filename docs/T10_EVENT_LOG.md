# FRAMEFLOW V5.3.2 — T10 EventLog

## Responsibility

`core/runtime/event_log.py` provides the persistent Runtime EventLog over the
existing `events` table. It appends structured facts and supports deterministic
queries by trace, entity, and event type. It does not implement Supervisor,
restart Recovery, Provider event sourcing, or a new event table.

## Event contract

Each event persists:

```text
id
trace_id
entity_type
entity_id
event_type
payload
created_at
```

Missing event IDs and trace IDs are generated locally. Identity and type
fields are validated against the existing column lengths. Payloads are
canonical UTF-8 JSON using the shared `frameflow.idempotency.canonical_json`
helper, with sorted object keys, stable separators, and NaN rejection.
Common credential keys such as token, password, secret, API key, credential,
and authorization are redacted before persistence.

## Transaction boundary

`EventLog.append()` owns one short StateStore transaction. For a domain
mutation that must be atomic with its event, callers use:

```text
with event_log.transaction() as connection:
    domain mutation
    event_log.append_in_transaction(connection, ...)
```

`append_in_transaction()` never commits by itself. If either the domain write
or event insert fails, the StateStore transaction rolls both back. The
external handler/provider work must occur outside the write transaction.

Existing StateStore CRUD methods may continue to supply their optional event
specification in their own transaction; T10 adds the explicit EventLog seam
for Runtime lifecycle code and companion writes.  The canonical TaskStore now
uses that seam for Task lifecycle facts:

```text
Task create       -> TASK_CREATED
Queue enqueue     -> CREATED -> QUEUED
Queue claim       -> QUEUED -> RUNNING
Queue cancel      -> CREATED/QUEUED -> CANCELLED
Queue retry       -> FAILED/INTERRUPTED -> QUEUED
Worker success    -> RUNNING -> SUCCEEDED
Worker failure    -> RUNNING -> FAILED
```

Each listed mutation and its event share one transaction.  A no-op status
write and Worker heartbeat do not append a state event.  The Task event
taxonomy is intentionally limited to `TASK_CREATED` and
`TASK_STATE_CHANGED`; no new table or migration is introduced.

## Queries and ordering

`list()` supports `trace_id`, `entity_type`, `entity_id`, and `event_type`
filters with a bounded limit from 1 to 1000. Results are ordered by:

```text
created_at ASC, id ASC
```

`by_trace()` and `for_entity()` are small query aliases. Reading events never
mutates the canonical production database.

## Scope boundaries

T10 does not scan stale workers, change `RUNNING` to `INTERRUPTED`, add
Supervisor liveness, call Providers, acquire ResourceLocks, or add EventLog
history tables.  Queue retry remains the existing bounded T06 operation; T10
only records its already-persisted transition.  Tests use isolated SQLite
databases; production is checked read-only for its V5 Runtime contract and
absence of T10 test rows.
