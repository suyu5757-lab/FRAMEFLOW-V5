# FRAMEFLOW V5.3.2 — T09 Provider Submission Idempotency

## Scope

T09 provides the persisted idempotency foundation for Provider Submit. It is
not a Seedance adapter, Manual Adapter, Provider Gateway, polling/fetch
lifecycle, EventLog, Worker integration, or Recovery implementation. Tests
use a fake provider and never contact a real or paid Provider.

## Identity and hashes

The logical `idempotency_key` is an auditable canonical JSON envelope with
exactly these inputs:

```text
project_id
shot_id
package_version
shot_spec_version
provider
provider_config_hash
```

The existing `frameflow.idempotency.canonical_json()` helper is reused. It
uses UTF-8 JSON with sorted object keys, stable separators, and NaN rejection.
`provider_config_hash` is SHA-256 over the canonical provider configuration;
`request_hash` is an independent SHA-256 over only the actual Provider
Submit request payload. Neither hash includes a timestamp, submission
attempt, or external task ID.

Consequently, changing `shot_spec_version`, `package_version`, `provider`,
or provider configuration changes the logical key. Reordering JSON object
keys does not change either canonical hash. The same request hash with a
different logical key is not globally deduplicated.

## Persist-before-side-effect flow

`ProviderIdempotencyService` follows this boundary:

```text
build idempotency_key + request_hash
↓
validate Generation → Shot → Project and Provider
↓
BEGIN IMMEDIATE: find or insert provider_submission intent
↓
commit intent/election
↓
mark PREPARED → SUBMITTING and commit attempt +1
↓
call fake/explicit submitter outside the DB transaction
↓
bind returned external_task_id and mark SUBMITTED
```

The unique `provider_submissions.idempotency_key` constraint and the
`BEGIN IMMEDIATE` intent transaction elect exactly one submit owner. Other
callers read the persisted record and never issue a second external submit.

## Status contract

The existing table has no status check constraint, so T09 defines these
minimal implementation statuses without changing schema:

| Status | Meaning |
|---|---|
| `PREPARED` | Intent persisted; no external call has started |
| `SUBMITTING` | Elected caller has committed provider-attempt ownership |
| `SUBMITTED` | Real external task ID is persisted |
| `UNKNOWN` | External outcome is ambiguous; reconcile before submit |
| `FAILED` | Known failure recorded without inventing an external ID |

`provider_submissions.attempt` counts Provider submission attempts and is
independent from `tasks.attempt`, which counts Worker execution attempts.

## Duplicate, timeout, and restart behavior

Sequential and concurrent duplicate requests reuse one logical record and
produce one external submit invocation. A concurrent caller observing
`SUBMITTING` returns `IN_PROGRESS` and does not call the provider.

If a fake Provider creates a remote job and then raises
`ProviderSubmitTimeout`, the record becomes `UNKNOWN`. The service calls an
explicit `reconcile(request_payload, submission)` callback before any second
submit. If reconciliation finds the remote ID, it binds that ID and returns
`RECONCILED`; without a lookup capability it remains `NEEDS_RECONCILE`.

Closing the StateStore and creating a new service instance preserves the
submission row. A later identical request with `SUBMITTED` state returns
`REUSED` and does not call the provider again.

If the same logical key is paired with a different `request_hash`, T09 raises
`SubmissionConflictError` before any external call. This prevents silently
reusing a job for different request content and also prevents an automatic
second submit.

## Safety boundaries

Only a valid persisted Generation whose Shot, Project, and Provider match the
request may create an intent. No `external_task_id` is fabricated before a
submitter returns one. SQLite transactions are short and never span an
external call. No Provider lock, cost/billing logic, EventLog, Supervisor,
Recovery, or production DB write is part of T09.
