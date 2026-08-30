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
for Runtime lifecycle code and companion writes.

## Queries and ordering

`list()` supports `trace_id`, `entity_type`, `entity_id`, and `event_type`
filters with a bounded limit from 1 to 1000. Results are ordered by:

```text
created_at ASC, id ASC
```

`by_trace()` and `for_entity()` are small query aliases. Reading events never
mutates the canonical production database.

## Scope boundaries

T10 does not scan stale workers, change `RUNNING` to `INTERRUPTED`, retry
Tasks, call Providers, acquire ResourceLocks, or add EventLog history tables.
Tests use isolated SQLite databases; production is checked read-only for its
V5 Runtime contract and absence of T10 test rows.
