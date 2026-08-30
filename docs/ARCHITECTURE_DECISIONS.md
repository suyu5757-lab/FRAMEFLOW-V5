# FRAMEFLOW V5.3.2 FINAL — Architecture Decisions

Status: **FROZEN FOR CONTROLLED IMPLEMENTATION**

These ADRs are the T00 architecture freeze. They record decisions from the V5.3.2 expanded master plan; they do not represent implementation of T01 or later tasks.

## ADR-001 — Workspace Root

**Decision:** `D:\11067\CodexWorkspaces\frameflow-v3` is the only writable project root. It is the physical path behind the `D:\cc\workspace` dual mount. Skills live at `D:\11067\CodexHome\skills`; `D:\AIGC\SUYU` is READ_ONLY; `D:\ComfyUI` is the external engine boundary.

**Consequence:** All project artifacts, runtime state, docs, and future code use the physical project root. No alias ambiguity may change where writes land.

## ADR-002 — Local Video Boundary

**Decision:** Local execution is limited to image/control/reference preparation. No local Seedance-class video model, long-video diffusion, video LoRA, or video training is introduced. Formal video generation goes through Seedance, another cloud provider adapter, or Manual Bridge.

**Consequence:** `D:\ComfyUI` remains an engine/weights boundary, not a location for a local video-generation stack inside FRAMEFLOW.

## ADR-003 — SQLite Runtime Source of Truth

**Decision:** Runtime truth is SQLite WAL at `D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db`, with `journal_mode=WAL`, `foreign_keys=ON`, and `busy_timeout=5000`. The Runtime MVP has 11 tables: `projects`, `sequences`, `shots`, `assets`, `artifacts`, `tasks`, `events`, `resource_locks`, `generations`, `provider_submissions`, and `reviews`.

**Consequence:** JSON, Markdown, and manifests are exports, archives, inspection records, or migration inputs. T00 does not create or migrate the existing database.

## ADR-004 — Shot-centric Model

**Decision:** The minimum production unit is a Shot in `Project → Sequence → Shot`. ShotSpec is the contract for story purpose, participants, scene, props, action, camera, states, dialogue, references, constraints, and status.

**Consequence:** Provider submission, package manifests, generation, review, retry, and continuity are anchored at shot level rather than at a project-wide video blob.

## ADR-005 — Artifact Provenance

**Decision:** Every durable file is an Artifact with project/shot/asset relationship where applicable, type, role, path, hash, version, source task, source artifacts, status, and creation metadata. `assets.master_artifact_id` points to the current asset master; `source_artifacts_json` records derivation.

**Consequence:** The system can answer how a file was produced and can trace it through Task, Input, Provider, Recipe, and Generation without relying on filename conventions alone.

## ADR-006 — Provider Abstraction

**Decision:** The provider-neutral pipeline is `ShotSpec → Canonical Prompt → Provider Adapter`. Seedance is first priority, Manual Bridge is mandatory, and Mock is required for offline E2E. Provider capabilities include first/last-frame support, limits, manual-only state, estimated cost, and last verification time.

**Consequence:** Provider-specific parameters stay in adapters/contracts, not in Skill prompts. Manual unknown cost is `null`/`UNKNOWN`, never a fabricated zero.

## ADR-007 — Task Runtime

**Decision:** Every side effect becomes a Task and is coordinated by the Runtime. MVP states are `CREATED`, `QUEUED`, `WAITING_FOR_RESOURCE`, `RUNNING`, `SUCCEEDED`, `FAILED`, `INTERRUPTED`, and `CANCELLED`. Task records carry trace, attempt, timeout, worker, payload/result/error JSON, timestamps, and event history.

**Consequence:** Queueing, retry, cancellation, observation, and restart recovery have one auditable control path instead of ad hoc endpoint or Skill side effects.

## ADR-008 — Resource Locks

**Decision:** `resource_locks` is a persistent MVP table. The lock resources are `PHOTOSHOP`, `AFTER_EFFECTS`, `RESOLVE`, and `COMFY_GPU`; leases expire after 300 seconds and heartbeat every 30 seconds. The V5.3.2 Resource Compatibility Matrix is:

| Resource pair | Rule |
|---|---|
| `PHOTOSHOP` + `AFTER_EFFECTS` | Mutually exclusive |
| `PHOTOSHOP` + `RESOLVE` | Mutually exclusive |
| `AFTER_EFFECTS` + `RESOLVE` | Mutually exclusive |
| `COMFY_GPU` + `PHOTOSHOP` | Concurrent execution allowed |
| `COMFY_GPU` + `AFTER_EFFECTS` | Mutually exclusive |
| `COMFY_GPU` + `RESOLVE` | Mutually exclusive |

The `COMFY_GPU` policy is conservative production safety for the target
machine (RTX 4060 Laptop, 8GB VRAM). Photoshop concurrency remains allowed
for the image/control GPU workflow, while After Effects and DaVinci Resolve
may use GPU acceleration and VRAM during production workloads. Reliability
and deterministic resource behavior therefore take priority over maximum
local concurrency. A future hardware or benchmark review may introduce a
new capability/resource-profile ADR; it does not change the V5.3.2 matrix.

**Consequence:** Creative Apps and GPU work cannot silently contend for stateful software or hardware. Lock ownership and recovery are visible through Runtime state.

## ADR-009 — Provider Idempotency

**Decision:** Provider Submit is idempotent using persisted `idempotency_key` and `request_hash`. The key includes `PRJ + SH + package_version + shot_spec_version + provider + provider_config_hash`.

**Consequence:** Double clicks yield one external job; submit timeouts reconcile before resubmission; a restart marks orphaned running work `INTERRUPTED` and permits explicit retry. `shot_spec_version` prevents a new shot contract from colliding with an older package.

## ADR-010 — Typed Actions

**Decision:** LLMs may produce only schema-validated Typed Actions. Execution is `LLM → Typed Action → Schema Validation → Allowlist → Trusted Handler`; arbitrary Shell is prohibited.

**Consequence:** Action permissions, path policy, audit logging, and preflight/verification stay enforceable independently of model output.

## ADR-011 — AI QA in Pilot

**Decision:** AI Visual QA enters the Pilot with exactly three dimensions: Identity, Character Count, and Artifacts. It emits score, blocking issues, warnings, and suggested route. The remaining visual dimensions are deferred.

**Consequence:** Pilot QA remains small enough to validate in the Runtime loop while still supporting a structured decision route and human approval.

## ADR-012 — Production Decision Engine

**Decision:** The first Decision Engine supports only four routes: `REGENERATE_VIDEO`, `PHOTOSHOP_REPAIR`, `AE_REPAIR`, and `HUMAN_REVIEW`. Identity drift/character-count errors regenerate; minor artifacts/color mismatches use Photoshop; timing/caption issues use AE; score below 40 or repeated failure at least twice goes to human review.

**Consequence:** Routing is deterministic and auditable in the MVP. Cost/time probability scoring is deferred.

## ADR-013 — Git / Skill Migration Safety

**Decision:** Any Skill refactor is gated by a stable snapshot, dedicated development branch, actual auto-sync script audit, dirty-tree abort safety, and explicit `INTERNAL`/`NON_BREAKING`/`BREAKING` classification. BREAKING changes require compatibility adapter, migration test, rollback test, and deprecation note. T01.5 must pass before T02 or any Skill contract refactor.

**Consequence:** V5.3.2 cannot trade existing production capability for a faster schema or Skill rewrite. T00 records the current hash and audit gap; it does not create the stable tag or development branch.

## ADR-014 — Shot-level Real Storage Paths

**Decision:** The real package and generation root is `D:\11067\CodexWorkspaces\frameflow-v3\projects\PRJ001\shots\SH001\`, with `references`, `packages`, `generations`, `reviews`, `retries`, and `post` subdirectories. Archives live at `D:\11067\CodexWorkspaces\frameflow-v3\archives\` and are tracked through Artifact paths.

**Consequence:** No project-level `packages` or `generations` directory is reintroduced. Retention is non-destructive with locked masters and approved generations protected.

## ADR-015 — Creative App Responsibility Boundaries

**Decision:** Photoshop owns still/reference/image repair; After Effects owns shot-level VFX/composite/motion; DaVinci Resolve owns sequence-level edit/color/audio/delivery. They are AI-operated production nodes with L1 atomic actions and later L2 composite tasks.

**Consequence:** Each app has a clear scope, uses ResourceLock, and follows non-destructive rollback: new Photoshop versions, AEP snapshot/duplicate, or Resolve duplicate timeline. Resolve auto-assembly is not part of T48 Milestone 1 closure.

## ADR-016 — T04 Archive Retention Threshold

**Decision:** FRAMEFLOW V5.3.2 freezes `max_archive_size_gb` at `100` GB in
`config/runtime-retention.json`. This is a warning-only projected-usage
threshold: `current_archive_size_bytes + candidate_size_bytes >= 100 GB`
emits `ARCHIVE_SIZE_THRESHOLD_EXCEEDED`.

**Consequence:** The threshold is not a filesystem quota and never triggers
automatic deletion, purge, rotation, approved-generation deletion, locked
master deletion, migration-archive deletion, or Legacy evidence deletion.
Missing, malformed, non-finite, zero, and negative values are configuration
errors. Crossing the threshold requires explicit operator awareness and a later
maintenance decision.

## ADR-017 — Generation Result Artifact Binding

**Problem:** The Runtime already records the input package manifest on a
Generation, but it had no canonical relation for result Artifacts produced or
imported by that Generation.

**Decision:** Add nullable `artifacts.generation_id` as a foreign key to
`generations.id`, with an index for Generation-result queries and restrictive
delete behavior. A Generation may own zero or many result Artifacts.

**Semantics:** `generations.package_manifest_artifact_id` remains the input
package-manifest relation. Package, asset-master, frame, scene, prop, and
other reference Artifacts keep `generation_id = NULL`. Provider or Manual
result Artifacts use `generation_id = <owning generation>` and the existing
`role = provider_result` convention.

**Safety:** Existing rows are backfilled only with NULL; no path, role,
timestamp, task, or Legacy V3 inference is allowed. The relation remains on
the existing `artifacts` table; no result join table or single-result column
is introduced. Cross-project and cross-shot consistency is a service-level
invariant for the later Manual/Provider binder.

**Consequence:** The Runtime remains an 11-domain-table model (12 SQLite
tables including `alembic_version`) and can trace a result Artifact to its
Generation, ProviderSubmission, source Task, and input provenance without
using filesystem paths as authority.

## Freeze rules

- Implementation, bug fixes, performance work, provider adapters, workflow/recipe additions, and UI refinement may follow the frozen decisions.
- Changing the Project/Sequence/Shot/Asset/Artifact/Task/Runtime/Provider/Review/Decision/Creative App/Delivery relationships requires an explicit architecture review.
- T00 did not modify Skills, Runtime, database, Workbench UI, old files, sync scripts, or model installations.
