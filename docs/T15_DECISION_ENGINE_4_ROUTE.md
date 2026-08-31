# T15 — Production Decision Engine MVP (4 Route)

## Result

T15 implements a pure, typed, read-only decision engine for the frozen V5
production contract. It returns one of exactly four routes:

- `REGENERATE_VIDEO`
- `PHOTOSHOP_REPAIR`
- `AE_REPAIR`
- `HUMAN_REVIEW`

`route=None` is reserved for `INVALID` input and `NOT_APPLICABLE` evidence.
There is no fifth route and the engine never executes a route.

## Existing decision contract

The repository audit found no existing V5 Decision Engine in
`core/decision_engine` or `core/orchestrator`. The V3 asset QA decision names
and asset-specific failure queries in `frameflow/asset_audit.py` remain outside
this contract and were not reused. T15 accepts only explicit current issue
identifiers, an optional score, explicit same-issue failure counts, and
separate optional continuity evidence.

## Frozen route mapping

| Current issue | Route |
| --- | --- |
| `identity_drift` | `REGENERATE_VIDEO` |
| `character_count_error` | `REGENERATE_VIDEO` |
| `minor_artifact` | `PHOTOSHOP_REPAIR` |
| `color_mismatch` | `PHOTOSHOP_REPAIR` |
| `timing_issue` | `AE_REPAIR` |
| `caption_issue` | `AE_REPAIR` |

Same-route issues resolve to that one route. Issues from multiple route
families resolve to `HUMAN_REVIEW` with reason
`ambiguous_multiple_route_families`.

## Precedence and fail-closed behavior

1. Invalid input returns `status=INVALID`, `route=None`, and validation errors.
2. A finite score below 40 returns `HUMAN_REVIEW`; `None` means unavailable,
   while exactly 40 does not trigger the guard.
3. Any explicit known issue failure count of at least 2 returns
   `HUMAN_REVIEW`.
4. Unknown failure evidence or an unknown current issue returns
   `HUMAN_REVIEW` and preserves the unknown evidence.
5. Multiple known route families return `HUMAN_REVIEW`.
6. A single known route family returns its mapped route.
7. No applicable issue or guard returns `NOT_APPLICABLE` with `route=None`.

The cross-family behavior is implementation closure for an ambiguity; it is
not a new cost, time, probability, severity, or utility scoring system.

Current issue duplicates are de-duplicated and therefore cannot manufacture
historical failures. Failure counts are never inferred from duplicate current
issues. Scores must be finite numbers in the existing 0–100 score contract;
failure counts must be integers greater than or equal to zero.

## T14 boundary

T14 continuity `CONFLICT` is not included in the six T15 route rules. Callers
may carry it under `DecisionInput.continuity_evidence`; it remains separate
evidence and produces no route by itself. Passing an unrecognized value as a
current issue is preserved as unknown evidence and fails closed to human
review; it is not mapped to an automatic repair route.

## Read-only boundary

`core/runtime/decision_engine.py` imports only Python standard-library typing,
dataclass, enum, numeric, and math utilities. It has no `StateStore`, Task,
provider, filesystem, network, retry, submission, repair, or QA-generation
dependency. The test suite invokes the engine repeatedly and verifies stable
results without a Runtime write surface.

## Test matrix

`tests/runtime/test_t15_decision_engine.py` covers the T15 decision matrix:
all six mappings, score boundaries, failure-count boundaries, same-route and
cross-route issue sets, duplicate issues, unknown evidence, no issue,
unavailable and invalid scores, invalid counts, deterministic ordering, the
T14 boundary, typed JSON output, and read-only behavior. The required T13,
T14, T16, T20, T23, T26, and T48 checks remain separate regression suites and
are not changed by T15; T13/T14/T48 are run as the explicit D22–D24
regressions.

## Explicit non-goals

T15 does not create Tasks, retry plans, provider submissions, provider
capability logic, Seedance/Gateway adapters, Photoshop/After Effects actions,
QA generation, taxonomy changes, cost/time/probability scoring, schema changes,
or new database tables.
