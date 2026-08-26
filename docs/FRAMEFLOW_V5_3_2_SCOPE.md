# FRAMEFLOW V5.3.2 FINAL — Scope Freeze

## Freeze statement

**FRAMEFLOW = AI Video Production Orchestration System**（AI 视频生产编排工作台）。本文件冻结 V5.3.2 的架构边界与 MVP 目标；本轮只执行 T00 Scope Freeze。T01、T01.5、T02 及任何功能开发均不在本轮范围内。

FRAMEFLOW is not a local video generator or a loose collection of Skills. It orchestrates story, assets, shots, continuity, tasks, providers, creative applications, QA, retry, versioning, recovery, post, and delivery. The user remains Director / Producer / Final Reviewer; low-risk operations may be AI-operated, while creative and final-risk decisions remain human-approved.

## Immutable environment boundaries

| Role | Path | Rule |
|---|---|---|
| Only writable project root | `D:\11067\CodexWorkspaces\frameflow-v3` | Unique project write target; equivalent to the `D:\cc\workspace` mount in the plan |
| Skill repository | `D:\11067\CodexHome\skills` | Skill source and migration boundary |
| Historical assets | `D:\AIGC\SUYU` | READ_ONLY; canonicalize and resolve symlinks/junctions before permission checks |
| Image/control asset engine | `D:\ComfyUI` | Engine, models, workflows, custom nodes, and runtime outputs; weights must not be copied into the project |
| Runtime Source of Truth | `D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db` | SQLite WAL; JSON/Markdown/manifest files are exports, archives, inspection records, or migration inputs, not concurrent runtime truth |

The project is not allowed to introduce a local Seedance-class video model, long-video diffusion, video LoRA, or video-model training. Local execution is for image/control/reference preparation such as character, scene, prop, first/last frame, mask, depth, edge, segmentation, inpaint, outpaint, upscale, background removal, contact sheets, and preprocessing.

## Production unit and provider boundary

The minimum production unit is a **Shot**:

```text
Project
└─ Sequence
   └─ Shot
```

The provider-neutral path is:

```text
ShotSpec
→ Canonical Prompt
→ Provider Adapter
→ Seedance / other cloud provider / Manual Bridge
```

Seedance is the first provider. Manual Bridge is required even when a provider has no API. Mock is required for offline Runtime E2E. FRAMEFLOW stays provider-agnostic and must not scatter provider-specific parameters into Skills.

## Runtime MVP

SQLite WAL is the runtime source of truth. The MVP target is an 11-table runtime model:

```text
projects
sequences
shots
assets
artifacts
tasks
events
resource_locks
generations
provider_submissions
reviews
```

The database boundary must use:

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;
```

The model preserves `shots.metadata_json`, `tasks.payload_json`, `tasks.result_json`, and `tasks.error_json`. Every artifact must retain provenance to its project, shot/asset where applicable, source task, source artifacts, path, hash, version, role, and status. Package manifests are tracked as artifacts through `generations.package_manifest_artifact_id`; there is no standalone `packages` runtime table in this MVP.

## Task Runtime, locks, and side effects

Every side effect must first become a Task and execute through the Task Runtime. Runtime state includes task identity, trace, status, attempt, timestamps, input, output, and error. MVP TaskState is:

```text
CREATED → QUEUED → WAITING_FOR_RESOURCE → RUNNING
       → SUCCEEDED / FAILED / INTERRUPTED / CANCELLED
```

ResourceLock is persistent and required for Creative Apps and GPU work. The resources are `PHOTOSHOP`, `AFTER_EFFECTS`, `RESOLVE`, and `COMFY_GPU`. Lease timeout is 300 seconds and heartbeat is 30 seconds. The concurrency matrix is:

| Resource pair | Rule |
|---|---|
| `COMFY_GPU` + `PHOTOSHOP` | Concurrent execution allowed |
| `PHOTOSHOP` + `AFTER_EFFECTS` | Mutually exclusive |
| `PHOTOSHOP` + `RESOLVE` | Mutually exclusive |
| `AFTER_EFFECTS` + `RESOLVE` | Mutually exclusive |

Provider Submit is idempotent. The key includes `shot_spec_version`:

```text
PRJ + SH + package_version + shot_spec_version + provider + provider_config_hash
```

The request hash and idempotency key are persisted. The required three cases are:

1. Double click: two submits with the same key create one external job.
2. Timeout: reconcile before any second submit; do not immediately duplicate the external job.
3. Restart: `RUNNING` becomes `INTERRUPTED` when the worker/process is absent, then can be explicitly retried.

## Decision and QA scope

The first Production Decision Engine has exactly four routes:

```text
REGENERATE_VIDEO
PHOTOSHOP_REPAIR
AE_REPAIR
HUMAN_REVIEW
```

Initial routing rules are:

- `identity_drift` or `character_count_error` → `REGENERATE_VIDEO`.
- `minor_artifact` or `color_mismatch` → `PHOTOSHOP_REPAIR`.
- `timing_issue` or `caption_issue` → `AE_REPAIR`.
- score below 40 or the same issue failing at least twice → `HUMAN_REVIEW`.

AI Visual QA enters the Pilot with three dimensions only: `Identity`, `Character Count`, and `Artifacts`. It returns a score, blocking issues, warnings, and a suggested route. Wardrobe, Prop, Composition, Action, Camera, Continuity, and Text are later dimensions.

## Creative Apps and operator levels

Photoshop, After Effects, and DaVinci Resolve are AI-operated production nodes, not manual user-entry points:

- **L1 Atomic Action:** Photoshop `open`, `resize`, `export`, `background_remove`, `color_match`; AE `create_comp`, `import_media`, `render_preview`, `add_caption`; Resolve `create_project`, `import_media`, `create_timeline`, `place_shots`. Each action follows `Preflight → Execute → Verify`.
- **L2 Composite Expert Task:** composite/reference repair, shot transition/finishing/timing, and rough-cut/pacing/audio assembly. L2 follows `INSPECT → UNDERSTAND → PLAN → PREFLIGHT → EXECUTE → VERIFY → REFINE → DELIVER`.

The responsibility boundary is `Photoshop = still/reference/image repair`, `After Effects = shot-level VFX/composite/motion`, and `Resolve = sequence-level edit/color/audio/delivery`. Locked masters are never overwritten; new versions, AEP snapshots, or duplicate timelines provide rollback.

## Security and execution rules

LLM output is limited to Typed Actions. All operations are **Non-destructive**, versioned, logged, validated, and rollbackable:

```text
LLM → Typed Action → Schema Validation → Allowlist → Trusted Handler
```

No LLM may execute arbitrary Shell. User paths must be canonicalized, symlink/junction-resolved, checked against the resolved path policy, and then permission-checked. Secrets use redaction and a credential manager or environment variables.

## Gates and migration safety

Skill Migration Safety must pass before any Skill refactor. The required policy distinguishes `INTERNAL`, `NON_BREAKING`, and `BREAKING` changes. A BREAKING change requires a compatibility adapter, migration script/test, rollback test, and deprecation note. Existing Git daily auto-sync behavior must be audited at T01.5; T00 does not modify or validate that future gate.

The implementation gates are:

| Gate | Required outcome |
|---|---|
| Gate 0 — MIGRATION SAFE | Stable snapshot/tag, development branch, auto-sync audit, compatibility policy, and `GIT_SYNC_AUDIT.md` |
| Gate A — RUNTIME MVP READY | SQLite WAL, 11 tables, Task/Queue/Worker, four locks with matrix, idempotency cases, Event Log, restart recovery, Git Safety, Mock E2E |
| Gate B — PROVIDER + INTELLIGENCE READY | Seedance, Manual, Mock, reconcile, Technical QA, three-dimensional AI QA, four-route Decision, Retry |
| Gate C — EXPERT OPERATOR MVP READY | Capability, Typed Actions, path security, Photoshop, AE, Resolve, rollback, benchmark |
| Gate D — PRODUCTION PILOT READY | 30–60 seconds, 3+ shots, AI QA, retry, PS, AE, Resolve, human approval, delivery |

## T00 deliverables and explicit exclusions

T00 creates only these documents:

1. `docs\BASELINE_V5_3_1.md`
2. `docs\FRAMEFLOW_V5_3_2_SCOPE.md`
3. `docs\ARCHITECTURE_DECISIONS.md` with ADR-001 through ADR-015
4. `docs\GIT_SYNC_AUDIT.md`

T00 does not modify Skills, Runtime code, database/schema, Workbench UI, legacy files, daily sync scripts, or model installations. It does not start T01, T01.5, T02, or any later task. The architecture is frozen for controlled implementation only after this document set and its consistency check are committed.
