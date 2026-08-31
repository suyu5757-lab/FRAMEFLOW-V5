# FRAMEFLOW V5.3.2 — T48 Mock Single-shot E2E

## Purpose and flow

T48 proves one isolated, deterministic Shot can complete the Runtime closure:

```text
ShotSpec → T20 Resolver → T23 CanonicalPrompt → T16 Package Artifact
→ Generation(mock) → T09 ProviderSubmission → T26 Result Import
→ minimal smoke → explicit approval → Review → POST_READY
```

The fixture uses one Project, Sequence, Shot, registered character/scene/prop
masters, and registered first/last-frame references.  It invokes the real
T20/T23/T16 code; no resolved context, prompt, or package ID is fabricated.

## Local Mock Provider

`core/runtime/providers/mock.py` implements the provider-compatible surface:

```text
prepare / submit / reconcile / poll / fetch / cancel / normalize_result
```

It subclasses the existing Manual adapter specifically to reuse the existing
trusted T09 submission and T26 import paths.  `submit()` uses a deterministic
`mock-…` external task ID; it has zero HTTP, credential, cloud, or paid-model
calls. `fetch()` exposes only a pre-created isolated project import-staging
file after the local ProviderSubmission becomes `SUBMITTED`.

The media fixture is a deterministic, valid one-frame, one-second, raw AVI
from `core/runtime/mock_media.py`. It is neither an empty file nor renamed
text. T26 copies it atomically from staging into the canonical Generation path
and registers the result Artifact.

## Minimal technical smoke

`core/runtime/minimal_smoke.py` performs only:

```text
exists → raw AVI container/frame decode → duration > 0
```

The raw AVI fixture is decoded by extracting its BGR frame, so a file merely
named `.avi` fails closed. This is intentionally not T33: no codec/fps/aspect,
audio, bitrate, colour-space, or full QA report is added.

## Approval and POST_READY

The frozen schema has no `POST_READY` value or table. T48 therefore derives it
without a migration:

```text
Generation.status = QA_APPROVED
+ latest Review.decision = APPROVED
+ Review.qa_json.smoke.passed = true
⇒ post_ready = true
```

`ExplicitReviewService.approve()` is a separate explicit caller action. It
queues `T48_EXPLICIT_APPROVE`; the trusted Worker re-runs smoke, persists one
`reviews` row with approval/smoke evidence, updates the existing Generation
status to `QA_APPROVED`, and appends `T48_EXPLICIT_APPROVAL`. Result import and
smoke alone create no Review and never make an output post-ready.

## Traceability

The final Review points to Generation; Generation points to T16's package
Artifact; ProviderSubmission is bound by T09; the imported result Artifact
points to its Generation and import Task; its source Artifact list contains
the actual Package/reference IDs. Runtime Tasks and Events retain submission,
import, package, and explicit-approval evidence.

## Isolation and non-goals

All T48 artifacts, SQLite data, staging media, and final media live below a
fresh ignored `.tmp/t48-isolated/<uuid>` root. The canonical production DB is
not opened for write. T48 does not implement Seedance, ComfyUI, networking,
Gateway reconciliation, T13+, full Technical/AI QA, retries, Resolve, UI work,
or schema changes.

## Test evidence

`tests/e2e/test_t48_mock_single_shot_e2e.py` covers the full happy path,
pre-approval prevention, invalid-media rejection, T09 duplicate submission,
duplicate import, missing/wrong Generation failure, result provenance, and
the local mock-provider interface.

With the prior T20/T23/T26/T16, Task/Queue/Worker, T09, EventLog, WAL/schema,
ResourceLock, Recovery, and Git Safety evidence, this Mock E2E closes Gate A:
`RUNTIME MVP READY`.
