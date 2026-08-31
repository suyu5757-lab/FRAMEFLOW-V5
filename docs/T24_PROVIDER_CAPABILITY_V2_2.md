# T24 — Provider Capability v2.2

## Purpose and existing surface

T24 defines a provider-neutral capability contract and a read-only
compatibility evaluator. It does not verify a remote Provider and does not
execute a submission.

The repository already declared the eight v2.2 field names and nullable
defaults in `core/schemas/runtime_mvp.py`; that declaration is outside the 11
Runtime tables. No profile model, capability registry, or V5 compatibility
evaluator existed before T24. The V3 `frameflow/provider_adapters.py` and
settings `provider_profiles`/`capability_bindings` remain legacy application
surfaces and are not reused as V5 Runtime capability storage.

The current provider-neutral Runtime adapters use the exact identifiers
`manual` and `mock`. `ManualProviderAdapter` provides a local manual bridge;
`MockProviderAdapter` is a deterministic local T48 test double. Neither
adapter currently provides a unified, verified duration/image hard-limit
contract.

## Profile contract

`ProviderCapabilityProfile` has exactly these eight v2.2 fields:

| Field | Type and validation | Semantics |
| --- | --- | --- |
| `provider` | non-empty string; whitespace trimmed; case is not merged | stable provider identifier |
| `supports_first_frame` | strict boolean | declared first-frame support |
| `supports_last_frame` | strict boolean | declared last-frame support |
| `max_duration` | finite real number greater than 0 | declared maximum duration |
| `max_images` | strict integer greater than or equal to 0 | declared provider-consumable image limit |
| `manual_only` | strict boolean | automated execution is not supported when true |
| `estimated_cost_per_submit` | nullable finite real number greater than or equal to 0 | estimate only; not a ledger |
| `last_verified_at` | nullable timezone-aware datetime or ISO timestamp | explicit verification evidence timestamp |

Unknown profile fields and missing required fields are rejected. Validation is
strict for booleans, integers, numeric special values, and provider IDs. No
default is invented for duration, image count, or capability flags. The only
profile defaults are the existing nullable `estimated_cost_per_submit` and
`last_verified_at` fields.

The model accepts a static ISO timestamp or aware `datetime` and normalizes it
to UTC. It never calls `datetime.now()` while loading or reading a profile.

## Declared versus verified

`last_verified_at is None` means the profile is declared but `UNVERIFIED`.
`last_verified_at is not None` derives `verified=true`; the timestamp must be
provided by a caller with real verification evidence. T24 does not create the
timestamp and does not claim that a declaration has been verified merely
because it passed schema validation.

Consequently, a profile whose declared limits satisfy all requirements returns
`UNVERIFIED` when its timestamp is null, rather than `COMPATIBLE` or a fake
`VERIFIED_COMPATIBLE` result.

## Cost semantics

`estimated_cost_per_submit` is nullable and has a separate derived
`cost_status`:

- `null` → `UNKNOWN`, never implicit zero;
- explicit `0` → `KNOWN` zero estimate;
- positive finite number → `KNOWN` estimate;
- negative, non-numeric, NaN, or infinite values → validation failure.

The Manual Provider identifier is `manual`; its existing adapter reports
`MANUAL_COST_STATUS = UNKNOWN`. T24 does not create a Manual profile with
invented hard limits or an invented cost. The Mock adapter is local and
deterministic, but T48 does not establish general production limits or cost,
so no Mock profile is auto-registered either.

## Requirements contract

`ProviderRequirements` is the explicit provider-consumable request shape:

```json
{
  "duration": 5,
  "image_count": 2,
  "requires_first_frame": false,
  "requires_last_frame": false,
  "execution_mode": "automated"
}
```

`duration` is a positive finite number. `image_count` is an integer greater
than or equal to zero. The two frame requirements are strict booleans.
`execution_mode` is exactly `manual` or `automated`.

T24 intentionally accepts `image_count` explicitly. T16 Package and T26
Manual upload references are provider-neutral and do not yet define one
universal provider-consumable upload-count derivation. T24 therefore does not
guess character + scene + prop + first + last counting semantics and does not
modify T16, T26, or ShotSpec.

## Compatibility result

`CompatibilityResult` contains:

```text
provider
status: COMPATIBLE | INCOMPATIBLE | UNVERIFIED | UNKNOWN | INVALID
verified
profile_last_verified_at
requirements
satisfied_constraints[]
blockers[]
warnings[]
reason
```

The evaluator applies these deterministic checks:

1. Invalid profile, requirement, or provider input returns `INVALID`.
2. A required first frame must be supported.
3. A required last frame must be supported.
4. Required duration must satisfy `required <= max_duration`.
5. Required image count must satisfy `required <= max_images`.
6. Automated execution is incompatible with `manual_only=true`; manual
   execution is allowed.
7. All definite blockers are returned in stable check order; evaluation does
   not stop at the first blocker.
8. If no blockers exist, a timestamped profile is `COMPATIBLE`; a null-
   timestamp profile is `UNVERIFIED` with a `profile_unverified` warning.

Blockers identify `field`, `required`, `available`, and a typed `reason`, for
example `duration_exceeds_provider_limit`,
`required_last_frame_not_supported`, or
`automated_execution_not_supported`.

An unknown provider returns `UNKNOWN` with `profile_not_found`. It never falls
back to Seedance, Mock, Manual, or another provider. There is no provider
ranking, cheapest-provider selection, fastest-provider selection, or health
status in T24.

## Registry and storage

`ProviderCapabilityRegistry` is an in-memory typed registry with `register`,
`get`, `list`, and `evaluate` operations. Registry ordering is stable by
provider ID. Duplicate provider registration fails closed with
`DUPLICATE_PROVIDER_PROFILE`; it is never last-write-wins.

No `config/capability_profiles` directory currently exists, so T24 does not
create a new file format solely for appearance. No production profiles are
auto-registered. Callers may register an explicitly authorized static profile
through the typed API. Normal `get`, `list`, and `evaluate` operations do not
mutate the registry or Runtime.

## Provider boundaries

### Seedance / T25 / T28

No verified Seedance capability evidence, Seedance Adapter, endpoint,
credential, HTTP request, submit, poll, fetch, cancel, or Contract Test was
added. The plan's `seedance`, `max_duration=10`, and `max_images=5` values are
documentation examples only. T24 does not register them as a verified
production profile; an example with `last_verified_at=null` is explicitly
`UNVERIFIED`.

### Manual and Mock

`manual` remains a legal Manual Bridge path and is not treated as unavailable;
`manual_only=true` only blocks automated execution. `mock` remains the local
T48 test provider. T24 does not alter either adapter, submit lifecycle,
ProviderSubmission, T09 idempotency, or T48 approval behavior.

### T15, T16, T27, T33+, Preflight, and Health

T24 does not modify T15 routes, package manifests, provider config hashes, or
ShotSpec semantics. It does not implement Gateway reconcile (T27), technical
or AI QA (T33/T34), issue taxonomy (T35), retry planning (T36), a full
Preflight system, Provider Health, or automatic Provider selection.

## Read-only and schema boundary

The capability model and evaluator use typed Python objects and static
declarations only. Evaluation creates no Task, Event, Shot, Artifact,
Generation, ProviderSubmission, or Review; it performs no filesystem or
network operation. There is no capability table, provider limits table,
migration, or new Runtime column.

## Tests

`tests/runtime/test_t24_provider_capability.py` contains 62 passing tests
covering P1–P31 plus strict unknown-field and JSON-result checks. It covers
field validation, cost and timestamp semantics, all compatibility constraints,
unknown and duplicate providers, deterministic ordering, read-only registry
behavior, T15/T14/T13/T48 regression surfaces, and the no-fake-Seedance rule.
The separate T15, T14, T13, T16, T20, T23, T26, T48, runtime, and schema
suites remain unchanged.

The canonical production DB remains the existing 11-table Runtime database;
T24 does not write it. Its before/after safety evidence is recorded in the
task completion report.
