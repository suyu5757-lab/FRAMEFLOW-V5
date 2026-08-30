# FRAMEFLOW V5.3.2 — T26 Manual Provider Adapter

## Contract status

The T26 Architecture Closure froze the output-side provenance relation:

```text
artifacts.generation_id → generations.id
```

The V5 Runtime had no formal Provider lifecycle interface, so T26 adds one
minimal provider-neutral surface in
`core/runtime/providers/manual.py`. The legacy V3
`frameflow/provider_adapters.py` remains a MIGRATE surface and is not used as
the V5 Runtime authority.

```text
provider = manual
```

No Skill, Gateway, Seedance adapter, or Workbench UI is modified.

## Inputs and package boundary

The adapter consumes a T23 `CanonicalPrompt` and a T20
`ResolvedShotContext`. It does not resolve Shots, recompile prompts, translate
text, or rewrite prompt semantics. `prepare()` reads the existing Generation,
its `package_manifest_artifact_id`, and the package Artifact's registered
`version`/path. It requires an existing Generation and package; it never
creates a Generation or Package.

Missing or incomplete package identity returns `PACKAGE_REQUIRED` or
`PACKAGE_NOT_READY`. T16 Package Builder remains outside this implementation;
the adapter creates no package directories or package files.

## ManualHandoff

`prepare()` returns typed `ManualHandoff` data containing:

```text
provider
generation_id
shot_id
project_id
canonical_prompt_text
reference_artifacts
upload_checklist
package_manifest_artifact_id
package_version
package_manifest_path
submission_ready
required_manual_actions
cost_status = UNKNOWN
submission identity (idempotency_key/request_hash/config hash)
```

Reference paths are projected only from T20-registered Artifacts. Copy Prompt
returns the exact canonical text; Open References returns IDs and registered
paths. Neither operation changes the OS clipboard or launches Explorer,
browser, shell, or external applications. The checklist is deterministic and
contains no unverified provider limits or model parameters.

## Provider lifecycle

```text
prepare          → pure/read-only ManualHandoff
submit           → MANUAL_ACTION_REQUIRED
reconcile        → local ProviderSubmission/manual evidence only
poll             → locally known state only
fetch            → MANUAL_IMPORT_REQUIRED
cancel           → MANUAL_CANCELLATION_REQUIRED
normalize_result → validates an imported result representation
```

There are zero HTTP calls, remote polling/fetch/cancel calls, and browser
automation calls. Manual cost is `UNKNOWN`, never fabricated as zero.

## ProviderSubmission and Task Runtime

`Mark Submitted` and External Task ID binding use the existing T09
`ProviderSubmissionStore`, `ProviderIdempotencyService`, canonical
`idempotency_key`, and `request_hash`. The identity includes project, shot,
package version, ShotSpec version, provider `manual`, and provider config hash.

All mutations use the trusted Runtime path:

```text
TaskStore
→ TaskQueue
→ Worker
→ explicit HandlerRegistry entry
→ ProviderSubmissionStore / domain operation
```

Task types are narrowly registered:

```text
MANUAL_PROVIDER_MARK_SUBMITTED
MANUAL_PROVIDER_BIND_EXTERNAL_TASK_ID
MANUAL_PROVIDER_IMPORT_RESULT
```

`SUBMITTED` requires a non-empty external Task ID under the existing T09
contract. Manual confirmation and the external ID are therefore persisted as
one logical submission operation. Repeating the same ID is idempotent;
different IDs fail closed and never silently overwrite the recorded ID.

Task payloads accept typed data only. They contain no shell, eval, exec,
module, callable, or command fields.

## Result Import

`import_result()` queues `MANUAL_PROVIDER_IMPORT_RESULT`; it does not copy a
file directly from the public call path. The trusted handler:

```text
validate approved staging source
→ compute source SHA-256
→ validate shot-level Generation destination
→ copy to a collision-safe temporary file
→ flush/fsync and verify size/hash
→ atomic finalize
→ create Artifact in a short DB transaction
```

The source must be in `%TEMP%\FRAMEFLOW\` or the project-controlled
`projects/<project_id>/imports/` staging root. Symlink/path escapes, system
roots, unsafe basenames, missing sources, unsupported media types, hash
mismatches, and destination collisions fail closed.

Result Artifacts use the existing `READY` status and contain:

```text
project_id
shot_id
generation_id
asset_id = NULL
type = derived media type
role = provider_result
path
sha256
version
source_task_id = import Task ID
source_artifacts_json = actual input Artifact IDs only
```

The destination is always the canonical shot-level path:

```text
projects/<project_id>/shots/<shot_id>/generations/<generation_id>/
```

The handler is retry-idempotent by deterministic Task/Artifact identity. If
the DB Artifact transaction fails after filesystem finalization, only the new
destination and newly-created empty directories are compensated; the source
remains unchanged. No global SHA uniqueness rule is introduced.

`normalize_result()` validates the Generation/Shot/Project relationship,
canonical destination, `provider_result` role, `asset_id = NULL`, source Task,
hash, version, and source Artifact IDs without writing. Import completion
returns `review_required = true` and the result Artifact IDs, but creates no
Review row, approval, or `POST_READY` state.

## Generation and package semantics

```text
Generation.package_manifest_artifact_id = input package Artifact
input package Artifact.generation_id = NULL
result Artifact.generation_id = owning Generation.id
```

Generation status is unchanged by import. The existing
`artifacts.generation_id` relation is the canonical binding; paths and
`tasks.result_json` are not relationship authorities. Cross-shot and
cross-project result bindings are rejected.

## Non-responsibilities

```text
T16 Package Builder       = not implemented
T48 Mock Single-shot E2E  = not implemented
T24 Provider Capability   = not started
T25 Seedance Adapter      = not started
T27 Gateway               = not started
Skill mutation            = none
Workbench UI              = none
ResourceLock              = none
Technical/AI QA           = deferred
Human approval            = deferred to T48
```
