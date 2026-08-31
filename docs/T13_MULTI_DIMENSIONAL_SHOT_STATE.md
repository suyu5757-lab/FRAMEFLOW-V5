# FRAMEFLOW V5.3.2 — T13 Multi-dimensional Shot State

## Purpose

T13 adds a read-only Shot State Projection / Aggregation Layer. It projects
the existing Runtime rows into seven dimensions and one operator summary. It
does not add a status column, state table, cache table, Alembic revision, or a
second database.

The Runtime SQLite rows remain the only authority. `ShotStateProjector` reads
the current Shot, ShotSpec, Assets, Artifacts, Tasks, Events, Generations,
ProviderSubmissions, and Reviews. T20/T23/T16/T48 contracts are reused for
resolution, prompt identity, package identity, and explicit approval.

## Seven-dimensional state contract

The values below are deliberately small derived representations. They are
not replacements for the underlying domain status vocabularies.

| Dimension | Possible values | Authority and derivation |
| --- | --- | --- |
| `spec_state` | `DRAFT`, `SPEC_READY`, `UNKNOWN` | ShotSpec v2.2 validation, ShotSpec identity, and its existing `status`; later lifecycle values mean the spec is ready but are not redefined. |
| `asset_state` | `NOT_READY`, `ASSET_READY`, `UNKNOWN` | T20 `ResolvedShotContext`: required Asset masters and direct frame references must resolve without a blocking issue. T14 continuity conflicts are not evaluated. |
| `package_state` | `NOT_READY`, `PACKAGE_READY`, `UNKNOWN` | A registered T16 `package_manifest` Artifact must be intact and match the current deterministic T16 logical package identity. Folder existence alone is never enough. |
| `generation_state` | `NOT_STARTED`, `CREATED`, `SUBMITTED`, `GENERATING`, `RESULT_READY`, `QA_APPROVED`, `RETRY_REQUIRED`, `UNKNOWN` | Current Generation, its ProviderSubmission, result Artifacts, and explicit Review evidence. Mock, Manual, and future providers are treated generically. |
| `review_state` | `NOT_STARTED`, `AWAITING_REVIEW`, `APPROVED`, `RETRY_REQUIRED`, `UNKNOWN` | The latest Review for the current Generation. An imported result without a Review remains awaiting review. |
| `post_state` | `NOT_READY`, `POST_READY`, `UNKNOWN` | T48 rule only: current Generation is `QA_APPROVED`, the current Review is explicit `APPROVED`, and its `qa_json.smoke.passed` is `true`. |
| `delivery_state` | `NOT_DELIVERED`, `DELIVERED`, `UNKNOWN` | No Delivery authority exists in the current Runtime MVP, so T13 always reports `NOT_DELIVERED` and reserves `DELIVERED` for a future authoritative subsystem. |

The returned `ShotState7D` also carries a minimal reason and entity evidence
list for each dimension, the current package Artifact ID, current Generation
ID, and typed projection issues.

## Summary state

`derive_summary_state()` returns only the frozen Workbench vocabulary:

```text
DRAFT
SPEC_READY
ASSET_READY
PACKAGE_READY
SUBMITTED
GENERATING
RESULT_READY
QA_APPROVED
RETRY_REQUIRED
DELIVERED
```

The precedence is explicit:

1. authoritative `DELIVERED` (reserved; not produced by T13);
2. any `UNKNOWN` dimension or invalid evidence fails closed to `DRAFT`;
3. a current Generation/Review `RETRY_REQUIRED` signal;
4. `QA_APPROVED` only when current Generation, Review, and T48 `POST_READY` evidence agree;
5. `RESULT_READY`;
6. `GENERATING`;
7. `SUBMITTED`;
8. current `PACKAGE_READY`;
9. `ASSET_READY`;
10. `SPEC_READY`;
11. otherwise `DRAFT`.

The summary is computed in memory and is never persisted to `shots`.

## Current Generation selection

Only Generations bound to the selected current package Artifact are eligible.
Among eligible rows, the selector uses persisted `created_at` and then the
Generation ID in descending order. It never uses filesystem order, an
unordered first row, or a historical approved row selected by accident.

The latest ProviderSubmission for that Generation is selected by persisted
`submitted_at`, then `attempt`, then ID. Result Artifacts and Reviews use the
same persisted timestamp/ID tie-break rule.

## Package and Generation freshness

T13 recomputes the current T16 package identity from the current T20 context
and T23 canonical prompt. It validates the registered package Artifact,
canonical package path, file hash, manifest bytes, logical SHA, version, and
current manifest identity. A ShotSpec or reference change therefore leaves
the old package and its Generations as history; it cannot produce a current
`PACKAGE_READY` or `QA_APPROVED` result.

Old Package, Generation, Review, and result Artifact rows are never deleted,
updated, or reclassified. They are only excluded from the current projection.

## Approval and post boundary

T48's boundary is preserved:

```text
result Artifact + smoke PASS
  != human approval

Generation.status = QA_APPROVED
+ latest current Review.decision = APPROVED
+ Review.qa_json.smoke.passed = true
  => post_state = POST_READY
```

T13 does not implement T14 continuity conflict detection, T15 Decision Engine,
T36 Retry Planner, Delivery, Provider adapters, ComfyUI, Creative App agents,
or Workbench redesign. `RETRY_REQUIRED` is projected only from existing
explicit Generation/Review/ProviderSubmission evidence; no retry plan,
parameters, cost, or automatic retry is created.

## Read-only semantics and malformed data

`get_shot_state()` and `derive_summary_state()` perform no Task, Event,
Artifact, Shot, Generation, Review, filesystem mutation, or network call.
`shots.metadata_json` is read only for integrity reporting; it is not used as
state authority and no snapshot is written into it.

Missing Shot, invalid ShotSpec, dangling Generation package references,
incomplete approval evidence, and ambiguous ProviderSubmission outcomes are
reported as typed issues and never guessed as ready. An orphan Review is
ignored and reported. No continuity comparison is performed.

## Tests

`tests/runtime/test_t13_multidimensional_shot_state.py` covers:

- S1–S3 Draft, Spec Ready, and Asset Ready;
- S4 T16 package identity and Package Ready;
- S5–S8 Submitted, Generating, Result Ready, explicit approval, and T48 Post Ready;
- S9 smoke/result without human approval;
- S10–S12 historical/current Generation selection and stale Package/Generation;
- S13 explicit retry evidence and S14 honest non-delivery;
- S15 zero-side-effect projection and ignored malformed metadata;
- S16 missing and inconsistent rows, including Generation without submission;
- deterministic summary precedence and mapping input support.

The fixture uses the already validated repository-local isolation mechanism;
it does not repair the known host pytest temporary-directory ACL issue.

## Production DB safety

T13 uses isolated databases for all writes in tests. The canonical database
is not opened with `initialize=True`, migrated, or populated by the projector.
Before and after the implementation, the Runtime safety checks are recorded:

```text
Alembic: 20260830_01
Runtime journal_mode: wal
Runtime foreign_keys: 1
Runtime busy_timeout: 5000
integrity_check: ok
foreign_key_check: clean

11 table counts before/after:
projects 45 / 45
sequences 45 / 45
shots 3 / 3
assets 26 / 26
artifacts 31 / 31
tasks 0 / 0
events 212 / 212
resource_locks 0 / 0
generations 0 / 0
provider_submissions 0 / 0
reviews 0 / 0
```

No schema migration, new domain table, production snapshot, or production
pollution is part of T13.
