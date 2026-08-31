# FRAMEFLOW V5.3.2 — T14 Continuity In/Out Conflict MVP

## Purpose and scope

T14 provides a small, typed, deterministic projection for structured
continuity declarations:

```text
explicit upstream Shot.OUT
            ↓
          compare
            ↓
explicit downstream Shot.IN
```

It detects only declared machine-comparable values. It does not perform image
comparison, identity recognition, scene recognition, similarity scoring,
Decision Engine routing, Retry planning, AI Visual QA, or automatic Shot
mutation.

## Existing continuity contract

The current Runtime schema contains:

```text
shots.continuity_in   TEXT / nullable
shots.continuity_out  TEXT / nullable
```

ShotSpec v2.2 contains:

```text
start_state          required object
end_state            required object
continuity_state_in  optional object / null
continuity_state_out optional object / null
```

The repository audit found no existing continuity reader, no continuity
conflict implementation, and no formal previous/next Shot relation. The
legacy-to-V5 migration mirrors ShotSpec `continuity_state_in/out` into the
Runtime `shots.continuity_in/out` columns, but `StateStore.create_shot()` and
T23 currently keep the two surfaces independently addressable.

T14 therefore freezes this precedence:

1. a non-empty, valid Runtime `shots.continuity_in/out` value is authoritative;
2. when the Runtime field is absent/empty, the corresponding ShotSpec
   `continuity_state_in/out` is used as fallback;
3. when both are present, canonical JSON equality is required;
4. a disagreement is `UNKNOWN` with
   `INCONSISTENT_CONTINUITY_SOURCES`, never a silent merge;
5. malformed Runtime or ShotSpec continuity is `UNKNOWN`, never a fallback;
6. `start_state` and `end_state` are validated as part of ShotSpec v2.2 but are
   not automatically compared by T14.

Empty means `null`, blank text, `{}`, or `[]`. Scalar roots and non-object
roots are unsupported because the frozen ShotSpec continuity fields are
object-or-null declarations.

## Pair and order semantics

The public surface is:

```python
ContinuityChecker(store).check_pair(upstream_shot_id, downstream_shot_id)
check_continuity(store, upstream_shot_id, downstream_shot_id)
```

The direction is explicit in the argument names and result evidence. T14 does
not invent `previous_shot`, `next_shot`, or an adjacent lookup. It does not
use lexicographic IDs, insertion order, filesystem order, or unordered query
results.

The pair is valid only when:

```text
both Shot rows exist
upstream != downstream
same Project
same Sequence
the Sequence exists and belongs to that Project
both ShotSpec JSON objects pass ShotSpec v2.2 validation
```

Invalid pair membership returns `INVALID`. Missing/corrupt continuity data
for an otherwise valid pair returns `UNKNOWN`.

## Result contract

`ContinuityCheckResult` contains:

```text
upstream_shot_id
downstream_shot_id
status
compared_keys
conflicts[]
missing_in[]
missing_out[]
evidence
issues[]
```

Statuses:

| Status | Meaning |
| --- | --- |
| `MATCH` | Every declared key on both sides compares equal and there are no missing keys. |
| `CONFLICT` | At least one key is explicitly declared on both sides and its normalized values differ. Missing keys are still returned. |
| `INCOMPLETE` | One side is absent, or one side declares keys the other side does not declare; no explicit mismatch exists. |
| `NOT_APPLICABLE` | Both sides have no declaration. |
| `UNKNOWN` | Continuity source is malformed or the two authority surfaces disagree. |
| `INVALID` | The explicit Shot pair or ShotSpec/sequence identity is invalid. |

`missing_in` means a key declared by upstream OUT but missing from downstream
IN. `missing_out` means a key declared by downstream IN but missing from
upstream OUT.

Each conflict contains:

```text
path
upstream_value
downstream_value
reason = explicit_value_mismatch
```

## Comparison rules

- JSON object key ordering is normalized for source equality and comparison
  order is sorted by canonical string path.
- Nested objects are traversed recursively.
- A common scalar, list, or object/scalar shape is compared exactly at its
  common path.
- Lists use canonical JSON exact equality; list order is significant.
- Numeric values use typed exact equality; `5` and `5.0` are not silently
  treated as the same value.
- No case folding of IDs, fuzzy strings, synonyms, color equivalence,
  tolerance, embeddings, or semantic LLM equivalence is applied.
- A missing key is incomplete evidence, not a conflict.
- A common key with different values is a conflict, including when one value
  is an object and the other is a scalar.

## Read-only and integration boundaries

`check_pair()` performs SELECT-only reads. It does not create a Task/Event,
write `shots.metadata_json`, change ShotSpec status, set T13 `RETRY_REQUIRED`,
create Review, alter Artifact/Generation state, call a Provider, or call the
network. T13 7D state is not rewritten; continuity evidence is available only
in the T14 result for a later consumer.

T14 does not implement:

```text
T15 Decision Engine 4-route
T24+ Provider work
T33/T34 Technical or AI Visual QA
T36 Retry Planner
T49 Pilot E2E
automatic adjacency
schema migration or new domain tables
```

## Tests

`tests/runtime/test_t14_continuity.py` covers:

- exact match;
- scalar, nested, and multiple conflicts with stable ordering;
- both sides missing;
- one-side missing and partial overlap;
- conflicts with simultaneous missing evidence;
- Runtime authority, ShotSpec fallback, and inconsistent sources;
- list order and typed numeric equality;
- missing/same/cross-project/cross-sequence pair validation;
- malformed and unsupported continuity values;
- deterministic repeated results;
- zero Task/Event/Shot/Artifact/Generation/Review/filesystem mutation.

All T14 fixtures use an isolated repository-local SQLite root. The known
`.tmp/tests` and Windows TEMP ACL issue is not repaired or bypassed.

## Production DB safety

The canonical database is only inspected read-only. T14 does not initialize,
migrate, seed, or write test data to it. Required before/after checks are:

```text
Alembic: 20260830_01
journal_mode: wal
runtime foreign_keys: 1
busy_timeout: 5000
integrity_check: ok
foreign_key_check: clean

projects: 45
sequences: 45
shots: 3
assets: 26
artifacts: 31
tasks: 0
events: 212
resource_locks: 0
generations: 0
provider_submissions: 0
reviews: 0
```

```text
production pollution = 0
new table = 0
new column = 0
Alembic migration = 0
```
