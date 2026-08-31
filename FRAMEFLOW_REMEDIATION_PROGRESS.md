# FRAMEFLOW V3 Remediation Progress

- Remediation date: 2026-08-23
- Governing plan: `C:\Users\11067\Downloads\FRAMEFLOW_V3_CODEX_REMEDIATION_EXECUTION_PLAN.md` (the requested root copy was not present at baseline)
- Audit source: `FRAMEFLOW_V3_INITIAL_AUDIT_REPORT_2026-08-23.md`
- Starting decision: `NO-GO`
- Starting blocker count: `P0 = 0`, `P1 = 9`
- Current blocker count after Phase 8: `P0 = 0`, `P1 = 0`
- Execution state: ACTIVE; all P1 items are verified. P2/P3 and final re-audit evidence remain.
- Target state: `RE-AUDIT READY` only; this work does not declare `GO` or `CONDITIONAL GO`.
- Priority: `Correctness > Data Safety > Production Authority > Recoverability > Performance > UX > Refactoring`

## Safety baseline

| Check | Result |
|---|---|
| Git branch | `main` tracking `origin/main` |
| Git worktree | Dirty before remediation; existing modified, deleted, and untracked user files are preserved |
| Formal database | `data/frameflow.db` |
| SQLite | WAL; `integrity_check=ok`; declared FK violations `0`; `user_version=0` |
| Migration authority | Baseline `1..8`; Phase 2 applied v9; Phase 3 applied v10 after independent dry-runs and pre-migration backups |
| Formal projects | DB: `PRJ_F3843DF0760F`, `e8f59c50-5db2-44e9-a4f7-fc3c41f0cc84`; media directories: `PRJ_32B543F4B566`, `e8f59c50-5db2-44e9-a4f7-fc3c41f0cc84` |
| Protected mismatches | `PRJ_F3843DF0760F` missing directory; `PRJ_32B543F4B566` missing DB row; no automatic repair performed |
| WAL checkpoint | `PRAGMA wal_checkpoint(TRUNCATE) = (0, 0, 0)` |
| Source DB SHA256 | `DC109C179879C08C20E9C6A26D17523CB99B0CDF72E274E36D46CF8F931E84D2` |
| Safety backup | `backups/frameflow-remediation-preflight-20260823-221507.db` |
| Backup SHA256 | `AE5D0621A9A858392317EE82DD1259FA612DCF8B0C85BCD631C362B7E6F921C1` |
| Backup validation | `integrity_check=ok`; 3,657,728 bytes |
| Post-v9 backup | `backups/frameflow-remediation-post-v9-20260823-230000.db`; SHA256 `24AF4DE7A9D28E1852CDFD84AC4AD82246BA3B0CE6A2131D037B2AD4A42627B2`; integrity `ok` |
| Post-v10 backup | `backups/frameflow-remediation-post-v10-20260823-231000.db`; SHA256 `5F8B754F22A7B6AEE3F491DF1AC6899398BEEB17FD89D85B41D317BBBC4A283F`; integrity `ok` |
| Media manifest | `backups/frameflow-media-manifest-20260823-221507.json` |
| Manifest SHA256 | `C8B2BFD16D687120185DE8F3C33D2AA9715295B837AD219296A8A4DAB9EFF9B5` |
| Manifest coverage | 110 files; 461,022,766 bytes under `data/projects` |
| Provider state | Runtime `degraded`; video ready; orchestrator/image/vision/TTS/music/SFX and other capabilities not ready or unbound; no paid provider call authorized |
| Phase 7 pre-migration backup | `data/safety-backups/backup_020d41a3477519de.db`; SHA256 `69d079de4cdf499406a728c85bd969dc25df5626cad6d12f4f990a408c6533e7`; integrity `ok` |
| Phase 7 media manifest | `data/safety-backups/backup_020d41a3477519de.manifest.json`; SHA256 `c1b7e87f3074735ed56740508c31cdc9320f9e6cb4df66ee89435e81dd69c65b`; 110 files / 461,022,766 bytes |
| Phase 7 formal migration | v12 applied after backup and isolated dry run; integrity `ok`, declared FK violations `0`, Reference rows `0`; formal DB SHA256 `28dc0c14eb58ddc0a5370c4ae430dc65e90abeda27bea1573199074b4e3afeef` |

## Baseline regression

| Suite | Result |
|---|---|
| Python unittest | `83/83 PASS` in 12.718s |
| Vitest | `6 files`, `32/32 PASS` |
| TypeScript + production build | PASS; main JS 699.17 KB (gzip 215.34 KB), >500 KB warning remains |
| Playwright Chromium | `8/8 PASS` |
| npm audit | `0 vulnerabilities` (run in `web`, where the lockfile exists) |
| pip check | PASS |
| Chrome / Edge smoke | Pending final regression |
| pip-audit | Pending environment check |
| Phase 7 full Python regression | `107/107 PASS` in 16.399s |
| Phase 8 full Python regression | `110/110 PASS` in 17.417s |
| Phase 8 performance acceptance | Independent 1000 assets / 300 shots HTTP p95: Asset Library `76.10 ms`, Dashboard `107.57 ms`; both below the `< 1s` acceptance threshold |

## AUDIT BASELINE DIFFERENCE

- The requested root filenames were not present. The authoritative files actually read were the attached `D:\11067\Codex\2026-08-13\video-2\FRAMEFLOW_V3_INITIAL_AUDIT_REPORT_2026-08-23.md` and `C:\Users\11067\Downloads\FRAMEFLOW_V3_CODEX_REMEDIATION_EXECUTION_PLAN.md`. Their contents match the stated audit/plan roles; this path/name difference does not redefine any audit issue.
- The audit baseline describes migrations `1..8`, 83 Python tests, and the original FF-P1-008 schema. Current code includes verified Phases 1–6 and migrations `1..11`; Phase 7 was therefore checked against the current schema before work rather than reimplementing prior phases.
- For FF-P1-008 specifically, the formal database had `0` `asset_reference_roles_v4` rows. v12 added only defaulted authority columns and indexes, so no historic reference row, project media, artifact, QA decision, or active-version pointer was rewritten.
- For FF-P2-010, the audit report supplies only a P2 summary rather than an individual Reproduce/Expected/Actual/Root Cause/Affected/Fix/Regression Risk record. Current read-only schema confirmation shows no declared FKs on `artifacts`, `asset_versions`, `prompt_versions`, `asset_qa_runs`, `asset_reference_roles_v4`, or `artifact_lineage_v3`. All project/artifact/QA/Reference/lineage joins are currently valid; however, all 29 formal `asset_versions.prompt_version` values are legacy labels such as `v01`, not `prompt_versions.id`. They cannot be silently converted into FK values and must be preserved/reported during the P2 migration design.

## Remediation Ledger

| ID | Severity | Problem | Root Cause | Code paths | Fix plan | Status | Tests | Regression result | Remaining risk |
|---|---|---|---|---|---|---|---|---|---|
| FF-P1-001 | P1 | Pending, unregistered, superseded, cross-project, or non-active media can reach Timeline → Render → Delivery | Timeline readiness trusted artifact/shot booleans; render `delivery_set=single` bypassed preflight; Worker did not recheck authority | `frameflow/production_gate.py`; `frameflow/v3.py`; `server.py`; `tests/test_v3_delivery.py`; `tests/test_v3_function_matrix.py` | One server-side production artifact gate validates ownership, path, SHA256, completed Approved QA, registered single active version, logical asset authority and non-revoked state at assemble/preflight/preview/estimate/create/approve/worker/final packaging | VERIFIED | 10 new delivery gate regressions plus upgraded authoritative fixtures | Targeted delivery `17/17 PASS`; full Python `93/93 PASS`; formal active artifacts `8/8` accepted and Pending artifacts `2/2` rejected | Older permissive timelines can now be blocked; no automatic data migration or readiness promotion is performed |
| FF-P1-002 | P1 | More than one approved Prompt can remain current for a logical asset | Prompt QA updated only the selected row | `frameflow/prompt_authority.py`; `frameflow/database.py`; `server.py`; migration/test coverage | Approval uses one immediate transaction to supersede prior authority; schema v9 partial unique index enforces one approved Prompt per project/logical asset | VERIFIED | Approve v1 then v2; v1=`superseded`, v2=current approved; direct duplicate update raises `IntegrityError`; duplicate-data migration test | Targeted 8/8 + migration 4/4; full Python 96/96 | Re-approving an older version intentionally makes it current and supersedes the newer approval; this is explicit authority reassignment, not history deletion |
| FF-P1-003 | P1 | Client can pair an approved prompt version ID with tampered text | Generation trusted `body.prompt` instead of canonical approved row | `frameflow/prompt_authority.py`; `frameflow/database.py`; `frameflow/schemas.py`; `server.py`; `tests/test_asset_v3_improvements.py` | Resolve the unique canonical approved row, compare optional client body hash, send only canonical text, and persist frozen prompt/reference/provider/model/parameter snapshot | VERIFIED | Tampered body returns `409` with zero Provider calls; omitted body sends exact canonical text and persists successful snapshot/hash/artifact binding | Full Python 96/96; mocked Provider argument and DB snapshot assertions PASS | Real paid Provider acceptance remains unauthorized; regression proves the exact mocked Provider argument, not real Provider health |
| FF-P1-004 | P1 | Concurrent Generate requests create duplicate runs and approval gates | No canonical fingerprint, in-flight uniqueness, or one-shot approval consumption | `frameflow/idempotency.py`; `frameflow/database.py`; `server.py`; `tests/test_v3.py`; `tests/test_v3_delivery.py` | Canonical run/render fingerprints, transactionally serialized create, partial unique indexes for in-flight work, and compare-and-set approval consumption | VERIFIED | Generate ×10 concurrent -> one run/gate; Render create ×10 -> one job; repeated approvals -> 409 | Targeted PASS; full Python `98/98 PASS` | Single-process scheduler still provides the runtime task lock; a future multi-process deployment would need renewable worker leases |
| FF-P1-005 | P1 | Empty project cannot complete a manual production chain without Providers | Scene/Shot and logical asset creation operations were missing from the UI; manual video QA still resolved a Provider before honoring manual review | `web/src/App.tsx`; `web/src/styles.css`; `frameflow/schemas.py`; `server.py`; `tests/test_manual_workflow_v3.py`; Playwright | Stable-ID Scene/Shot UI operations, logical asset creation for core classes, video logical asset support, and manual QA path that never resolves a Provider | VERIFIED | Provider-disabled API production chain + UI scene/shot CRUD/split/reorder + five logical asset classes, with forbidden Provider POST assertion | Python 106/106; Vitest 32/32; Build PASS; Playwright 9/9 | Final real FFmpeg render is not claimed here; Phase 1 already validated render worker behavior with mocked renderer and the original audit validated installed FFmpeg |
| FF-P1-006 | P1 | System data audit can report green while DB and media directories disagree | `ok` omitted missing/unregistered directories; project create did not atomically create media dir | `frameflow/data_integrity.py`; `frameflow/maintenance.py`; `server.py`; `tests/test_maintenance_v3.py` | One read-only integrity service drives both endpoints; project creation transactionally binds DB row and directory with compensation | VERIFIED | Missing/unregistered directory -> both audits `ok=false`; create directory success and synthetic mkdir rollback | Targeted 6/6; full Python 101/101; formal audit `ok=false` with exactly the two known protected directory mismatches | Full hashing makes audit intentionally correctness-first; performance can be optimized later without changing semantics |
| FF-P1-007 | P1 | Formal orphan/missing project state has no V3 backup/export/recovery path | Legacy endpoints retired without V3 replacement; startup lacked verified safety snapshot | `frameflow/recovery.py`; `frameflow/database.py`; `frameflow/schemas.py`; `server.py`; `tests/test_recovery_v3.py` | V3 backup/export/recovery scan-preview-confirm-apply-verify; daily startup backup; recovery candidates remain Pending/mapping-required | VERIFIED | Verified backup/hash; self-verifying export; preview/no-write; confirmation/token/source-change conflicts; temp apply/verify | Recovery 4/4; maintenance+recovery 10/10; full Python 105/105 | Formal `PRJ_32B543F4B566` Apply is `BLOCKED_USER_APPROVAL`; preview exists and no production row/media change occurred |
| FF-P1-008 | P1 | Reference role model could not express ordering, scope, authority, conflicts or historical effective version | Audit location remained valid: v4 stored only role/source/notes and generation snapshots sorted by creation time | `frameflow/reference_authority.py`; `frameflow/database.py` v12; `frameflow/schemas.py`; `server.py`; `tests/test_asset_v3_improvements.py`; `tests/test_v3.py` | v12 adds priority/scope/authority/conflict_group/effective_version; server validates same-group conflicts, resolves artifact-version authority, and freezes deterministic ordered reference snapshots | VERIFIED | Ordered persistence, conflict-winner snapshot, artifact hash/version freeze, two-absolute conflict rejection, v1→v12 migration regression | Targeted 5/5; Reference+V3 35/35; full Python `107/107 PASS`; formal v12 integrity `ok` | Existing historical generation snapshots retain their v9 frozen payload; new authority fields affect new/edited references only. Formal data had zero existing reference rows. |
| FF-P1-009 | P1 | 1000 assets + 300 shots exceeded API/UI targets | Audit location remained valid: library used per-asset relation/Prompt queries and implicit full media integrity scan; Dashboard detail reused that full projection | `server.py` library projection/query API; `frameflow/database.py` v13/v14; `web/src/components/VirtualAssetList.tsx`; `tests/test_v3_performance.py` | Batch relation projection, explicit-only integrity audit, server pagination/filter/sort, project indexes proven by EXPLAIN, and bounded virtual list window | VERIFIED | 1000/300 HTTP p95 gate, server paging contract, EXPLAIN migration test, virtual-window unit test | Full Python `110/110 PASS`; Vitest `33/33 PASS`; production build PASS; HTTP p95 Asset Library `76.10 ms`, Dashboard `107.57 ms`; virtual window `<30` rows at 1000 items | Asset Board still intentionally retains its separate canvas model; its larger-scale viewport/culling requirement remains a P2/follow-up concern, not a claim made by this library verification. |
| FF-P2-010 | P2 | Core V2/V3 authority tables lacked DB FKs, so `foreign_key_check=0` could not prove their integrity | Current confirmation: no FK declarations on artifacts, asset versions, Prompt versions, QA, Reference or lineage. 29 historical asset-version Prompt values are labels (`v01`), not Prompt IDs. | `frameflow/database.py` v15; `frameflow/asset_audit.py`; `server.py`; `tests/test_v3.py`; `tests/test_v3_delivery.py` | Rebuild authority tables with project/artifact/QA/Reference/lineage FKs and checks; preserve legacy prompt label, add nullable canonical `prompt_version_id` FK for new writes | VERIFIED | v15 migration/rollback chain, direct invalid FK insertion, legacy label preservation, canonical new-version binding, Gate fixtures with valid parent rows | Full Python `111/111 PASS`; dry-run and formal v15: integrity `ok`, FK check `[]`; counts preserved 31 artifacts/29 versions/16 Prompts/29 QA; 29 legacy labels retained | The logical asset is still authority in the project JSON document, so it cannot be a relational FK until a dedicated logical-assets table is introduced. |

## Phase history

### Preparation — Safety, mapping and Ledger

- Status: VERIFIED
- Code changes: none before safety checks.
- Database changes: WAL checkpoint only; no schema or project row changes.
- Formal data changes: none.
- Evidence: baseline test table and safety snapshot table above.
- Backward compatibility: source database remains schema v8 and integrity `ok`.
- Remaining risk: repository began dirty; all unrelated user changes must remain untouched. The execution plan exists only at the attachment path, not the requested project-root path.

### PHASE 1 — FF-P1-001 Production Artifact Gate

- Status: VERIFIED
- Fixed:
  - Added a single `production_artifact_gate()` that reads current DB and disk state rather than timeline, shot, frontend or cached readiness booleans.
  - Requires exact project ownership, a physical file inside the project root, valid matching SHA-256, artifact and logical asset `Approved` authority, a completed Approved QA record, exactly one registered active version, and matching logical-asset pointers.
  - `generated_pending_qa`, Pending, unmapped, unregistered, revoked/superseded/non-ready, wrong-project, missing-file and hash-mismatch inputs fail closed.
  - Timeline assembly stores the verified asset-version ID and production hash in clip metadata.
  - Preflight calculates readiness through the same gate.
  - Preview, render estimate, render create, render approve and Worker start all revalidate.
  - Removed the `delivery_set=single` preflight bypass from estimate/create.
  - Worker revalidates before starting, immediately before final artifact registration, and immediately before delivery package creation.
  - Render manifests now freeze logical asset ID, active asset-version ID/version, Approved QA run ID and verified file hash.
- Files changed:
  - `frameflow/production_gate.py`
  - `frameflow/v3.py`
  - `server.py`
  - `tests/test_v3_delivery.py`
  - `tests/test_v3_function_matrix.py`
- Database changes: none; schema remains v8 and migrations remain `1..8`.
- Tests added:
  - director-approved shot with Pending artifact -> assemble `409`
  - unregistered artifact -> assemble `409`
  - superseded/non-active artifact -> assemble `409`
  - wrong-project artifact -> assemble `409`
  - missing physical file -> assemble `409`
  - hash mismatch -> assemble `409`
  - Pending input -> preflight blocked and preview/estimate/create `409`, including `delivery_set=single`
  - authority revoked after create -> approve `409`
  - authority revoked before Worker -> failed job and zero render calls
  - authority changed during render -> failed job, no final artifact registration and no delivery package
- Tests passed:
  - targeted `tests.test_v3_delivery`: `17/17 PASS`
  - full Python regression: `93/93 PASS` in 12.513s
  - `py_compile`: PASS
  - `git diff --check`: PASS
  - formal DB active-authority dry run: `8/8` active artifacts pass; both Pending artifacts are rejected with `qa_not_approved`
- Migration/backward compatibility:
  - formal DB remains WAL, `integrity_check=ok`, declared FK violations `0`, migrations `1..8`, SHA256 unchanged from the safety snapshot
  - no formal project row, artifact, asset version, QA decision or media file was modified
  - schema-v8 API remains compatible; intentionally, old timelines that relied on permissive state now fail closed and require explicit QA/registration rather than automatic promotion
- Remaining risks:
  - `server.py` and `frameflow` were already large/untracked relative to the repository baseline, so Git cannot isolate all historical user changes; unrelated work remains preserved.
  - A render whose authority changes after final artifact registration but before package creation is stopped before the package is written, but the just-created output artifact row may already exist as a Pending final-render candidate. It is not Approved, registered, or delivered; transactional staging can be strengthened in the Recovery/P2 work.

### PHASE 2 — FF-P1-002 / FF-P1-003 Prompt Authority

- Status: VERIFIED
- Fixed:
  - Added atomic Prompt approval authority: approving a version supersedes all other approved versions for that project/logical asset in the same `BEGIN IMMEDIATE` transaction.
  - Added schema-v9 partial unique index `idx_prompt_versions_single_approved_v9`; application logic alone can no longer create two Current Approved Prompts.
  - Added deterministic duplicate migration: only the highest version/id remains approved; older duplicate approvals become `superseded`.
  - Image generation resolves the requested/current Prompt ID against the unique Approved DB row and sends only that canonical body.
  - Optional client Prompt text is hash-checked; a changed body returns `409 prompt_body_tampered` before any Provider call.
  - Added `generation_snapshots_v9` with canonical Prompt ID/body/SHA256, reference snapshot, provider/profile/model, parameters, status, artifact binding and timestamps.
- Files changed:
  - `frameflow/database.py`
  - `frameflow/prompt_authority.py`
  - `frameflow/schemas.py`
  - `server.py`
  - `tests/test_asset_v3_improvements.py`
  - `tests/test_v3.py`
- Database changes:
  - `SCHEMA_VERSION: 8 -> 9`
  - formal preflight-copy migration dry run: integrity `ok`, 2 projects/31 artifacts/16 prompts preserved, 8 approved, zero duplicate groups
  - formal migration applied after the dry run; checkpoint `(0,0,0)`, integrity `ok`, declared FK violations `0`
  - formal counts preserved: projects 2, artifacts 31, asset versions 29, QA runs 29, Prompt versions 16; approved 8, superseded 0, duplicate groups 0
  - formal post-v9 DB SHA256: `95A0FC277326F9AE3D17E46945A2B228CED01735F69D320F8CB04587EE90CF20`
  - post-v9 safety backup: `backups/frameflow-remediation-post-v9-20260823-230000.db`, integrity `ok`
- Tests added:
  - approve v1 then v2 -> v1 superseded, v2 approved, approved count exactly one
  - DB-level attempt to approve a second row -> `sqlite3.IntegrityError`
  - v9 migration with pre-existing duplicate approvals -> deterministic supersede + unique index
  - Approved version ID + tampered body -> `409`, Provider call count zero
  - canonical generation without client body -> exact approved text is sent and frozen snapshot fields/hash/artifact link are verified
- Tests passed:
  - `tests.test_asset_v3_improvements`: `8/8 PASS`
  - `FrameflowMigrationTests`: `4/4 PASS`
  - full Python regression: `96/96 PASS` in 14.685s
  - source compile check: PASS (bytecode write was unavailable because the running server held `__pycache__`; in-memory compile passed)
  - `git diff --check`: PASS
- Backward compatibility:
  - client `prompt` is now optional; existing clients may still send it unchanged, but cannot override canonical authority
  - old Prompt rows and bodies are retained; supersede changes authority status only
  - current formal data required no Prompt status rewrite because no duplicate approved groups existed
- Remaining risks:
  - the existing running server process loaded pre-remediation code and will require a controlled restart before runtime/browser release checks
  - frozen references use the current v4 reference fields; Phase 7 will add priority/scope/authority/conflict/effective-version and strengthen the snapshot without invalidating v9 rows
  - no real paid Provider was called; that acceptance remains `BLOCKED_USER_APPROVAL` until explicitly authorized

### PHASE 3 — FF-P1-004 Generation / Render Idempotency

- Status: VERIFIED
- Fixed:
  - Added canonical SHA-256 fingerprints for workflow runs using project, graph revision, selected nodes, full selected node/edge configuration, concurrency parameters, actor and operation type.
  - Added canonical render fingerprints using project, timeline revision/document, verified manifest inputs, render parameters, actor and operation type.
  - `confirmed` is deliberately excluded from the fingerprint, so a duplicate confirmed request cannot bypass an existing awaiting-confirmation gate.
  - Run and Render creation use `BEGIN IMMEDIATE`, look up an in-flight fingerprint, and return the existing ID instead of inserting duplicates.
  - Schema-v10 partial unique indexes enforce one in-flight row per fingerprint even if application-level lookup races.
  - Run approval consumes the pending approval-gate row and transitions the run with compare-and-set in one transaction.
  - Render approval records `approval_consumed_at` and transitions only from unconsumed awaiting-confirmation state.
  - Duplicate confirmations return `409`; completed/failed/canceled work releases the partial unique key so an intentional later retry can create a new run.
- Files changed:
  - `frameflow/idempotency.py`
  - `frameflow/database.py`
  - `server.py`
  - `tests/test_v3.py`
  - `tests/test_v3_delivery.py`
- Database changes:
  - `SCHEMA_VERSION: 9 -> 10`
  - added `workflow_runs_v3.idempotency_fingerprint`
  - added `approval_gates_v3.approval_consumed_at`
  - added `render_jobs_v6.idempotency_fingerprint` and `approval_consumed_at`
  - added partial unique in-flight indexes for workflow runs and render jobs
  - v10 dry run on the post-v9 backup: integrity `ok`, migrations `1..10`, zero existing runs/renders
  - formal migration: checkpoint `(0,0,0)`, integrity `ok`, declared FK violations `0`, 2 projects/31 artifacts/16 prompts preserved
  - formal post-v10 DB SHA256: `0F3FE111885A53B00B3713A0CFE4396AD71E480A6E8AA2D65FD5308CC7DEB1FB`
- Tests added/strengthened:
  - concurrent Generate ×10 -> ten HTTP 200 responses, one unique run ID, one non-replay response, one approval gate, seven selected node-run rows
  - Run approval twice -> first succeeds, second `409`, gate has `approval_consumed_at`
  - Render Create ×10 -> one unique in-flight render job and one non-replay response
  - Render approval twice -> first succeeds, second `409`, job has `approval_consumed_at`
- Tests passed:
  - targeted workflow concurrency/approval: `2/2 PASS`
  - targeted render idempotency/approval: `2/2 PASS`
  - migration suite: `4/4 PASS`
  - full Python regression: `98/98 PASS` in 16.845s
  - source compile and `git diff --check`: PASS
- Backward compatibility:
  - request bodies are unchanged; responses only add fingerprint/replay/approval-consumption metadata
  - existing completed historical rows may have null fingerprints and remain readable
  - formal DB had zero workflow/render jobs, so v10 required no row rewrite
- Remaining risks:
  - paid Provider billing was not invoked; the test proves one run/gate and scheduler enqueue authority, not a real billable execution
  - in-process `V3_RUNTIME_TASKS` / `V3_RENDER_TASKS` prevent duplicate workers in the supported single-user deployment; a multi-process server is outside the current deployment contract and would require DB worker leases

### PHASE 4 — FF-P1-006 Data Audit Authority / Atomic Project Creation

- Status: VERIFIED
- Fixed:
  - Added one read-only `scan_data_integrity()` authority used by project storage integrity and system data-audit.
  - `ok` now includes both DB-project -> directory and directory -> DB-project checks; missing/unregistered directories can no longer be omitted from the final result.
  - Added current checks for artifact ownership/path/file/hash, unregistered media under project artifact roots, orphan project-scoped rows, asset-version/artifact consistency, active-version ambiguity, QA/artifact consistency, reference authority, lineage, story asset references and board duplicate IDs.
  - Critical issues are returned in a single `critical_issues` list while legacy field names remain available for compatibility.
  - New project creation creates the DB row and exact project directory as one compensated operation under `BEGIN IMMEDIATE`.
  - If directory creation fails, the DB transaction rolls back; if DB commit fails after creating the empty directory, the single known empty directory is removed as compensation.
  - V3 `PUT` project creation uses the same atomic helper; updates to an existing project do not auto-create a missing directory and therefore cannot silently repair protected unknown state.
- Files changed:
  - `frameflow/data_integrity.py`
  - `frameflow/maintenance.py`
  - `server.py`
  - `tests/test_maintenance_v3.py`
  - `tests/test_v3_function_matrix.py` (fixture now creates the project before media)
- Database changes: none; formal schema remains v10.
- Tests added:
  - missing DB-project directory -> project integrity and system data-audit both `ok=false`
  - unregistered project directory -> both audits `ok=false`
  - API project create -> directory exists and project detail integrity is true
  - synthetic target-directory mkdir failure -> exception, no DB row, no residual target directory
- Tests passed:
  - maintenance target suite: `6/6 PASS`
  - function matrix after authoritative fixture ordering: `5/5 PASS`
  - full Python regression: `101/101 PASS` in 21.788s
  - source compile and `git diff --check`: PASS
  - formal SQLite: integrity `ok`, declared FK violations `0`, migrations `1..10`
- Formal read-only audit result:
  - `ok=false`
  - `missing_project_directories=[PRJ_F3843DF0760F]`
  - `unregistered_project_directories=[PRJ_32B543F4B566]`
  - exactly 2 critical issues; no artifact mismatch, unregistered artifact-root media, orphan row, version, QA, reference, lineage, story-ref or board-ID issue detected
  - no automatic directory creation, DB registration, media move or recovery apply was performed for either protected project
- Backward compatibility:
  - existing response fields remain; additional issue categories are additive
  - empty project directories are valid and distinguishable from missing directories
  - creating a project over an existing unregistered directory returns conflict rather than adopting unknown media
- Remaining risks:
  - scanning hashes is correctness-first and may be expensive for very large media sets; any Phase 8 caching must preserve current-state verification and invalidation guarantees
  - the two protected formal mismatches remain intentionally unresolved pending Phase 5 Recovery Preview and explicit user approval for any apply action

### PHASE 5 — FF-P1-007 Backup / Export / Import / Recovery

- Status: VERIFIED (formal Recovery Apply remains `BLOCKED_USER_APPROVAL` by policy)
- Fixed:
  - Added V3 verified backup API with WAL checkpoint, SQLite online backup, DB integrity check, DB SHA256, media manifest, media hashes/sizes/MIME and durable backup record.
  - Added project export API producing a ZIP with `manifest.json`, project-scoped DB authority rows and media files; the archive is reopened and every packaged media hash is verified before returning `verified`.
  - Added Recovery Scan reporting DB-missing directories and unregistered directories without mutation.
  - Added Recovery Preview that freezes file path/MIME/size/SHA256 into a durable plan, reports conflicts, defaults to dry-run, and never creates project/artifact rows.
  - Added Recovery Apply requiring explicit `confirmed=true`, exact preview ID + manifest SHA token, zero conflicts and unchanged source manifest.
  - Explicit recovery creates only a project in `recovery_review_required` plus `Pending/mapping_required` media candidates; it never grants QA, registration or active-version authority.
  - Existing project IDs produce a blocked preview; no overwrite/merge is attempted.
  - Added one verified formal startup backup per UTC day before task/run/render recovery proceeds.
- Files changed:
  - `frameflow/recovery.py`
  - `frameflow/database.py`
  - `frameflow/schemas.py`
  - `server.py`
  - `tests/test_recovery_v3.py`
  - `tests/test_v3.py`
- Database changes:
  - `SCHEMA_VERSION: 10 -> 11`
  - added `backup_records_v11` and `recovery_plans_v11`
  - v11 migration dry run on post-v10 backup: integrity `ok`, migrations `1..11`
  - formal migration: integrity `ok`, declared FK violations `0`; projects 2, artifacts 31, prompts 16 preserved
- Formal backup evidence:
  - backup ID `BACKUP_b97ab68659e9ce8b`, status `verified`
  - SQLite path `data/safety-backups/backup_b97ab68659e9ce8b.db`
  - DB SHA256 `8100aa77928babfc7583748d84012aff9497b1d3ae8c18e7977313cb6fcaa73b`
  - media manifest `data/safety-backups/backup_b97ab68659e9ce8b.manifest.json`
  - manifest SHA256 `987655257de60f2dbcd501aae8769fdf0c9e071e50a9b87ff4da53ca78dbda05`
  - checkpoint `(0,0,0)`, DB integrity `ok`, 110 media/project files, 461,022,766 bytes
- Formal Recovery Preview evidence:
  - Scan still reports missing `PRJ_F3843DF0760F` and unregistered `PRJ_32B543F4B566`
  - preview ID `RECOVERY_c2b669f6b615741f`
  - source `PRJ_32B543F4B566`: 79 files, 384,129,492 bytes
  - manifest SHA256 `665a0064adb5370bc57976153e0954be3b62ac553424deb8607ee43c270c345b`
  - conflicts `[]`, `apply_allowed=true`, `apply_performed=false`
  - formal counts after preview remain projects 2, artifacts 31, prompts 16; only one backup audit record and one recovery-plan metadata row were added
- Tests added:
  - backup files/hashes/SQLite integrity/manifest/record verification
  - export archive hash and packaged media/database authority verification
  - scan + preview leaves zero project/artifact rows
  - unconfirmed Apply -> `409`
  - source changed after Preview -> `409 source_changed`
  - refreshed explicit Apply in isolated temp project -> verified project plus one Pending/mapping-required candidate
  - existing project preview -> blocked/no overwrite
- Tests passed:
  - recovery suite: `4/4 PASS`
  - recovery + maintenance: `10/10 PASS`
  - migration suite: `4/4 PASS`
  - full Python regression: `105/105 PASS` in 22.435s
  - source compile and `git diff --check`: PASS
- Backward compatibility:
  - legacy V1/V2 endpoints stay retired; all capabilities use `/api/v2`
  - export/backup/recovery are additive and do not alter project schema until an explicitly confirmed recovery apply
  - startup backup is skipped for temporary/test databases and deduplicated to once per UTC day for the formal DB
- Remaining risks:
  - applying formal recovery for `PRJ_32B543F4B566` is not authorized and remains `BLOCKED_USER_APPROVAL`
  - `PRJ_F3843DF0760F` has no source directory, so recovery preview cannot reconstruct media; it remains BLOCKED pending external source or user decision
  - no UI for these administrative APIs has been added in this phase; the V3 service/API path and verification are complete, and Phase 6 remains focused on the manual production workflow rather than recovery administration UI

### PHASE 6 — FF-P1-005 Provider-Free Manual Production Workflow

- Status: VERIFIED
- Fixed:
  - Story UI now supports manual Scene creation/edit/delete without invoking an Agent or Provider.
  - Shot UI now supports Add, Duplicate, Delete, Reorder Up/Down and Split Shot.
  - New manual Shot IDs use non-renumbering UUID-based stable IDs; deleting one shot never changes surviving IDs.
  - Split preserves the original Shot ID for the first half and creates one new stable ID for the second half; durations are divided without dropping below 0.1s.
  - Unified Asset Library now exposes the existing logical-asset creation modal directly.
  - Manual logical asset options cover Character, Scene, Prop, Fusion, Product, Style, Video, Audio, Music and SFX; Phase-6 UI regression creates Character/Scene/Prop/Fusion/Audio.
  - Added `video` to the V3 logical-asset creation schema so manually uploaded approved-shot video can have a formal logical authority chain.
  - Fixed manual image/video/reference QA initialization so `manual_review=true` and mandatory manual Video/Reference QA do not resolve any Provider first.
  - The manual API path reaches Render awaiting-confirmation while `resolve_profile` is patched to fail on any use, proving no hidden Provider dependency.
- Files changed:
  - `web/src/App.tsx`
  - `web/src/styles.css`
  - `web/tests/e2e/workbench.spec.ts`
  - `frameflow/schemas.py`
  - `server.py`
  - `tests/test_manual_workflow_v3.py`
- Database changes: none; schema remains v11.
- Tests added:
  - Provider-disabled API: Project -> Story -> Scene -> Shot -> Video Logical Asset -> Upload -> manual Video QA -> Register active version -> approved Shot -> Timeline Assemble -> Preflight -> Render awaiting-confirmation
  - Provider-disabled UI: create/edit Scene; add three stable Shots; delete middle Shot without renumbering survivor; Duplicate; Split; save; verify four unique IDs
  - UI creates Character, Scene, Prop, Fusion and Audio logical assets and asserts no paid/generation/Agent POST occurred
- Tests passed:
  - manual API integration: `1/1 PASS`
  - full Python regression: `106/106 PASS` in 19.481s
  - Vitest: `6 files`, `32/32 PASS`
  - TypeScript + Production Build: PASS; current main JS 702.27 KB (gzip 216.24 KB), existing >500 KB warning remains for Phase 8
  - targeted Provider-free Playwright: `1/1 PASS`
  - full Playwright Chromium: `9/9 PASS`
  - Python source compile and `git diff --check`: PASS
  - formal SQLite: integrity `ok`, declared FK violations `0`, migrations `1..11`; core counts remain projects 2, artifacts 31, asset versions 29, QA 29, prompts 16
- Backward compatibility:
  - existing numeric Shot IDs and order are preserved; new manual IDs do not renumber legacy shots
  - Story API schema remains scenes/shots based; new controls only edit supported fields
  - existing logical asset classes and creation endpoint remain compatible; `video` is additive
  - manual QA still enforces the complete video checklist and correct QA owner; no QA threshold was lowered
- Remaining risks:
  - this phase does not claim a real paid Provider pass and does not call one
  - the manual integration stops at a gated Render awaiting confirmation; it does not mislabel a mocked render as real FFmpeg acceptance
  - full administrative Recovery UI remains absent but the verified V3 API exists from Phase 5

### PHASE 7 — FF-P1-008 Reference Authority

- Status: VERIFIED
- Audit defect → current-code confirmation: the dated audit's `Reproduce/Expected/Actual/Root Cause/Affected/Fix/Regression Risk` was reread before implementation. Current v11 still had only `role/source/notes` in `asset_reference_roles_v4`; `_generation_reference_snapshot()` ordered only by creation time. The audit location therefore remained valid.
- Fixed: Reference records now contain `priority`, `scope`, `authority`, `conflict_group`, and `effective_version`. A central authority service validates project-local artifact references, resolves the effective asset-version ID, rejects multiple absolute authorities and tie-ranked conflict winners, and defines deterministic packaging order. Each image-generation snapshot freezes priority/scope/authority/conflict group, winner, artifact SHA256, effective version and order.
- Files changed: `frameflow/reference_authority.py`, `frameflow/database.py`, `frameflow/schemas.py`, `server.py`, `tests/test_asset_v3_improvements.py`, `tests/test_v3.py`.
- Database changes: migration `11 -> 12`; new defaulted v4 Reference columns plus `idx_asset_refs_v12_authority`. Isolated migration dry run passed. Formal migration followed a verified SQLite/media backup; integrity `ok`, FK violations `0`, formal Reference rows `0`.
- Tests added: reference field persistence/order; conflict-winner snapshot; artifact SHA256/effective-version freeze; duplicate absolute authority rejection; v1-to-current migration compatibility.
- Tests passed: targeted `5/5`; Reference/V3 `35/35`; full Python `107/107 PASS` in 16.399s; source compile and `git diff --check` PASS.
- Backward compatibility: old API payloads remain valid through defaults (`priority=100`, `scope=general`, `authority=supporting`); legacy snapshots are immutable. No formal reference row required conversion.
- Remaining risk: no real paid Provider was invoked (not authorized); the regression verifies the exact server snapshot written immediately before the existing Provider boundary.

### PHASE 8 — FF-P1-009 Performance at 1000 assets + 300 shots

- Status: VERIFIED
- Audit defect → current-code confirmation: the audit's `Reproduce/Expected/Actual/Root Cause/Affected/Fix/Regression Risk` was reread. Current code still performed four relation/prompt queries per logical asset and called full media hashing from every library projection, so the original diagnosis remained valid.
- Fixed: Asset, version, Prompt, dependency, Reference and comparison rows are projected in six bounded batch queries rather than per-asset queries. Media hash integrity was not weakened: it is now explicit on `/integrity`, rather than silently recomputed on every asset-library read. The library route supports server pagination, filter, search and sort; v13/v14 indexes remove project-read scans and temporary sorts. The Asset Library list is windowed, with a bounded visible-row slice.
- Files changed: `server.py`, `frameflow/database.py`, `web/src/App.tsx`, `web/src/components/VirtualAssetList.tsx`, `web/src/components/VirtualAssetList.test.ts`, `tests/test_asset_v3_improvements.py`, `tests/test_v3.py`, `tests/test_v3_performance.py`.
- Database changes: migrations `12 -> 14`, only additive indexes. Each formal migration was preceded by a verified SQLite/media backup; final integrity `ok`, declared FK violations `0`. `EXPLAIN QUERY PLAN` now reports project-read index use with no temporary B-tree for artifacts, asset versions or Prompt versions.
- Tests added: real HTTP p95 test with 1000 assets/300 shots; query-page/filter/sort contract; migration index-plan test; virtual-window bound test.
- Tests passed: full Python `110/110 PASS` in 17.417s; Vitest `7 files / 33/33 PASS`; TypeScript + production build PASS; `git diff --check` PASS. Independent HTTP p95: Asset Library `76.10 ms`, Dashboard `107.57 ms`; library response contains 100 of 1000 items; virtual window is `<30` items.
- Backward compatibility: callers without `page` keep the legacy complete-library response; callers using the new query contract receive additive `pagination` metadata. The integrity endpoint remains the single authoritative full hash audit.
- Remaining risk: the separate React Flow Asset Board is not represented as a virtual list. This Phase verifies the audited Asset Library/Dashboard targets and does not overclaim canvas culling.

## Current checkpoint after Phase 8

### PHASE 9.1 — FF-P2-010 Database Integrity Constraints

- Status: VERIFIED
- Audit defect → current-code confirmation: the audit P2 summary was reread. No individual reproduce fields were supplied; current read-only schema inspection confirmed the cited six authority tables had no declared FK.
- Fixed: v15 rebuilds `artifacts`, `asset_versions`, `prompt_versions`, `asset_qa_runs`, `asset_reference_roles_v4`, `artifact_lineage_v3` and their dependent generation snapshot table with true project/artifact/QA/reference/lineage FKs. It adds `asset_versions.prompt_version_id` for canonical FK binding while preserving legacy `prompt_version` labels.
- Formal compatibility evidence: 29 legacy labels (`v01`) remain in the legacy field and are null in `prompt_version_id`; no invented backfill was applied. New asset-version creation resolves a project/logical-asset-scoped canonical Prompt ID before it writes the FK.
- Database changes: v14 → v15 after safety backup `BACKUP_ab705367a7013657`; dry-run and formal counts preserved: projects 2, artifacts 31, asset versions 29, Prompt versions 16, QA runs 29, Reference/lineage/snapshots 0. Formal integrity `ok`, FK violations `0`.
- Tests passed: migration suite includes direct invalid FK insertion and legacy/canonical Prompt cases; full Python `111/111 PASS`; `git diff --check` PASS.
- Remaining risk: logical assets remain document-authoritative, so their relational FK requires a future dedicated table rather than unsafe implicit duplication.

## Current checkpoint after Phase 9.1

- Current release state: `NOT READY`.
- Current blocker count: `P0 = 0`, `P1 = 0`.
- Next required phase: FF-P2-011 security response and local-boundary hardening.
- Do not mark `RE-AUDIT READY`; remaining P2/P3 items and final acceptance remain incomplete.

### PHASE 9.2 — FF-P2-011 Security Boundary Verification (2026-08-24)

- Status: `IMPLEMENTED / NOT VERIFIED` (fail-closed).
- Before this execution:
  - `P0 = 0`
  - `P1 = 0`
  - `FF-P1-009 = VERIFIED`
  - `FF-P2-010 = VERIFIED`
  - `FF-P2-011 = IMPLEMENTED / NOT VERIFIED`
  - `GLOBAL STATUS = NOT READY`; `RE-AUDIT READY = NO`; `GO = NO`
- Repository baseline: branch `main`, HEAD `7e3e0a9115980fbe599cea74765534417a7d1ea5`; the worktree was already dirty with user modifications, deletions and untracked V3 files. No reset, clean, broad deletion or formal-data reset was performed.
- Authoritative finding contract:
  - Source: `FRAMEFLOW_V3_INITIAL_AUDIT_REPORT_2026-08-23.md`, P2 summary.
  - ID/severity: `FF-P2-011 / P2`.
  - Defect: the local service lacked Authentication, Origin/CSRF/TrustedHost protection and CSP, X-Content-Type-Options and X-Frame-Options response headers, relying only on the loopback bind.
  - Affected component: HTTP boundary in `server.py`.
  - The authoritative report contains a summary finding but no separate reproduction or acceptance-criteria record. The existing remediation contract therefore covers only the observable local-boundary behaviors below; absence of application authentication remains unresolved rather than being inferred away.
- Existing remediation reviewed: `server.py` `TrustedHostMiddleware` and `local_security_boundary`; `tests/test_security_boundary.py` header, hostile-Origin and hostile-Host regression. The pre-existing Origin check was hard-coded to port `8787`.
- Change made in this execution: the Origin check now compares a supplied Origin with the current request scheme/netloc, so the same security boundary remains valid on an isolated test/runtime port such as `8791` without allowing a foreign origin. Added one dynamic-port regression to `tests/test_security_boundary.py`.
- Targeted test: `python -m unittest tests.test_security_boundary` → `1/1 PASS`.
- Live workbench baseline: `http://127.0.0.1:8787/` reachable; root `200`; `/api/health` `200` with runtime `degraded` because some Provider capabilities are unavailable; `/api/v2/projects` `200`; CSP, `X-Content-Type-Options: nosniff`, and `X-Frame-Options: DENY` present. A headless browser opened the actual workbench, rendered the main shell and navigation, and reported no page/console errors.
- Live negative path: POST with `Origin: https://evil.example` → `403`; attack marker absent from the subsequent project list. GET with `Host: evil.example` → `400`. No persistence, partial write or success state was observed.
- Live positive path: POST with `Origin: http://127.0.0.1:8787` created a temporary `AUDIT_TEST_P2_011_*` project with `201`; DELETE with the same valid Origin returned `200`; the temporary name was absent afterward. The Playwright isolated runtime also passed the formerly blocked dynamic-port creation step before reaching an unrelated selector failure.
- Related regression:
  - `npm run test:e2e -- --grep "project manager and all primary workspaces remain navigable" --workers=1` → security-path failure removed; later fails on an existing strict-mode selector ambiguity.
  - Full Playwright: `7/9 PASS`; failures are the stale schema-version assertion expecting `11` while current schema is `15`, and the same unrelated navigation selector ambiguity. Neither contradicts the FF-P2-011 boundary result.
- Full backend: `python -m unittest discover -s tests -p 'test*.py'` → `112/112 PASS` in `18.647s`.
- Full frontend: `npm test` → `7 files / 33 tests PASS`; `npx tsc -b --pretty false` → PASS; `npm run build` → PASS with the existing >500KB bundle warning.
- DB integrity: read-only formal DB check → `integrity_check=ok`, `foreign_key_violations=0`, schema `15`.
- Performance regression: `NOT REQUIRED`; this execution changed only the HTTP security middleware and its test, not the Asset Library, Dashboard, pagination, query, projection, integrity or virtual-list paths.
- No new P0/P1 finding or new FF-P2-011 security regression was found. The two broader E2E failures are recorded as existing/unrelated evidence and were not “fixed” by weakening tests.
- Finding decision: `FF-P2-011 = IMPLEMENTED / NOT VERIFIED`. The local Origin/TrustedHost/header boundary is verified, but the authoritative finding explicitly includes Authentication, and no formal acceptance criteria or application-auth implementation was found. The broader E2E suite also remains non-green. Do not upgrade this finding without resolving or explicitly accepting those gaps.

#### P2 inventory after Phase 9.2

| Finding | Current state | Evidence / next action |
|---|---|---|
| FF-P2-010 | VERIFIED | Preserve v15 FK/integrity evidence; do not redo unless regression appears. |
| FF-P2-011 | IMPLEMENTED_NOT_VERIFIED | Clarify/approve the authentication acceptance contract, resolve the recorded gate evidence, then re-audit. |
| FF-P2-012 | OPEN | Address bounded/streaming upload memory use next; no closure evidence found in the authoritative ledger. |
| FF-P2-013 | OPEN | Complete actor/reason/before-after audit trail coverage. |
| FF-P2-014 | OPEN | Complete accessibility remediation and browser verification. |
| FF-P2-015 | OPEN | Address maintainability/CI/bundle findings; current build warning remains. |
| FF-P2-016 | OPEN | Define and verify camera/scene authority models. |

- Audit inventory: `P0 = 0`; `P1 = 0`; `P2 = 7` (`1 VERIFIED`, `1 IMPLEMENTED_NOT_VERIFIED`, `5 OPEN`); `P3 = 3` (`FF-P3-017` through `FF-P3-019`, unresolved in the authoritative summary).
- Not completed: remaining P2, P3, Final RC Regression, Independent Re-Audit, `RE-AUDIT READY`, and `GO`.
- Do not redo: `FF-P1-009` performance remediation and `FF-P2-010` FK/integrity remediation unless a directly affected path regresses.
- Evidence report: this Phase 9.2 section, targeted unittest output, live 8787 HTTP/browser observations, full Python/Vitest/typecheck/build output, Playwright output, and read-only SQLite integrity output.
- Global decision: `GLOBAL STATUS = NOT READY`.
- Next recommended action: resolve the missing/ambiguous Authentication acceptance contract and the two unrelated frontend E2E failures, then continue with `FF-P2-012` using the same read → targeted test → live verification → minimal gap-fix workflow.

### PHASE 9.2B — FF-P2-011 Security Acceptance Closure (2026-08-24)

- Status: `VERIFIED` for the confirmed supported deployment contract.
- Final decision: `FF-P2-011 = VERIFIED`.
- Global state remains: `GLOBAL STATUS = NOT READY`; `RE-AUDIT READY = NO`; `GO = NO`.

#### Before

- `P0 = 0`
- `P1 = 0`
- `FF-P1-009 = VERIFIED`
- `FF-P2-010 = VERIFIED`
- `FF-P2-011 = IMPLEMENTED / NOT VERIFIED`

#### Authoritative finding and acceptance contract

- The authoritative finding is `FF-P2-011 / P2` in `FRAMEFLOW_V3_INITIAL_AUDIT_REPORT_2026-08-23.md`: the local service lacked application Authentication, Origin/CSRF/TrustedHost protection and CSP, X-Content-Type-Options and X-Frame-Options headers, relying on the loopback bind.
- Deployment inspection confirmed that FRAMEFLOW is a single-user local workbench: `启动工作台.bat` and `server.py:main()` bind to `127.0.0.1:8787`; README documents only the local URL; there is no FRAMEFLOW LAN/public/remote mode, reverse-proxy mode, application token, session or login mechanism. The only Basic Auth reference is for the separate optional OpenCode server, not FRAMEFLOW.
- Accepted security contract for the currently supported deployment: loopback-only (`127.0.0.1`, `localhost`, `::1`); no multi-user identity login is required inside that boundary; TrustedHost, same-origin state-change validation and browser security headers are mandatory; any non-loopback bind without a real application-auth implementation is unsupported and must fail closed. If LAN, remote, public, shared-user or reverse-proxy deployment is introduced, application Authentication becomes mandatory and this acceptance must be re-evaluated.
- This contract resolves the original Authentication ambiguity without pretending that Origin protection is Authentication: the application does not expose an unauthenticated non-loopback service, and it refuses such configuration at startup.

#### Changes

- `server.py`: added explicit `ipaddress`-based bind-host classification, loopback-only enforcement in the FastAPI lifespan and `main()`, and detection of `FRAMEFLOW_BIND_HOST`/Uvicorn `--host` configuration. `0.0.0.0` and `192.168.1.20` now fail before application startup; `127.0.0.1`, `localhost` and `::1` are accepted.
- `tests/test_security_boundary.py`: added positive loopback host and negative non-loopback configuration tests; retained Origin/Host/header/persistence coverage.
- `web/tests/e2e/workbench.spec.ts`: replaced stale exact schema `11` assertion with the current supported minimum `15`; scoped workspace navigation selectors to the navigation landmark to remove strict-mode ambiguity without `.first()`, `.nth()`, sleeps or disabled strict mode.
- `FRAMEFLOW_REMEDIATION_PROGRESS.md`: recorded this acceptance contract, evidence and closure decision.
- No database migration, performance-path change, dependency upgrade or change to `FF-P1-009`/`FF-P2-010` was made.

#### Targeted security tests

- `python -m unittest tests.test_security_boundary` → `2/2 PASS`.
- `python -m uvicorn server:app --host 0.0.0.0 --port 8793 --log-level warning` → application startup rejected with the explicit loopback-only/no-authentication error.

#### Live verification

- `http://127.0.0.1:8787/`: reachable, root `200`, main shell rendered, project manager opened, all five primary workspaces navigated, no browser console/page errors.
- Malicious Origin `https://evil.example` on a state-changing POST → `403`; attack marker was absent from the subsequent project list.
- Malicious Host `evil.example` → `400` from TrustedHost.
- Valid `http://127.0.0.1:8787` project create → `201`; temporary `AUDIT_TEST_P2_011B_*` delete → `200`; cleanup confirmed and project count returned to baseline.
- Dynamic-port same-origin behavior remained valid on isolated Playwright port `8791`; foreign Origin remained rejected.
- Runtime headers verified on the live root/API middleware: CSP present, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`.
- `/api/health` remained `degraded` only because external Provider capabilities are unavailable/unbound; this is an environment capability limitation, not an FF-P2-011 application failure.

#### Regression

- Full Python: `python -m unittest discover -s tests -p 'test*.py'` → `113/113 PASS` in `27.373s`.
- Vitest: root `npm test` → `7 files / 33 tests PASS`.
- TypeScript: `npx tsc -b --pretty false` → PASS.
- Production build: `npm run build` → PASS; existing >500KB bundle warning remains in FF-P2-015 scope.
- Full Playwright: `npm run test:e2e -- --workers=1` → `9/9 PASS` in `17.6s`.
- DB integrity: read-only `PRAGMA integrity_check` → `ok`; `PRAGMA foreign_key_check` → `[]`; schema version `15`; no migration performed.
- Performance regression: `NOT REQUIRED`; only deployment boundary, security tests and E2E selectors changed.
- `git diff --check` → PASS.

#### Remaining risk and inventory

- The Authentication contract is valid only for the documented loopback-only single-user workbench. Any future non-loopback/shared-user/remote exposure requires a real application-auth design and a new FF-P2-011 acceptance review.
- Audit inventory remains `P0 = 0`, `P1 = 0`, `P2 = 7`, `P3 = 3`:
  - `FF-P2-010 = VERIFIED`
  - `FF-P2-011 = VERIFIED`
  - `FF-P2-012` through `FF-P2-016 = OPEN`
- Not completed: remaining P2, P3, Final RC Regression and Independent Re-Audit. Do not declare `RE-AUDIT READY` or `GO`.
- Do not redo: `FF-P1-009` performance remediation or `FF-P2-010` FK/integrity remediation unless a directly affected regression appears.
- Next recommended action: Phase 9.3 — `FF-P2-012` bounded/streaming upload memory remediation. Stop before beginning it in this task.

### PHASE 9.3 — FF-P2-012 Bounded / Streaming Upload Memory (2026-08-24)

#### 1. Final decision

- Status: `VERIFIED`.
- `FF-P2-012 = VERIFIED`.
- `GLOBAL STATUS = NOT READY`; `RE-AUDIT READY = NO`; `GO = NO`.

#### 2. Authoritative finding

- Source: `FRAMEFLOW_V3_INITIAL_AUDIT_REPORT_2026-08-23.md`, P2 summary.
- Finding: `FF-P2-012 / P2`.
- Exact available wording: maximum upload is 1GB and `await file.read(MAX_UPLOAD+1)` loads the whole file into memory, creating local memory-exhaustion risk.
- The original audit provides a summary finding, not a separate complete acceptance-criteria block. This phase therefore records the minimum architecture-backed contract: application-level reads are bounded; SHA-256 and byte count are incremental; disk writes are staged/incremental; validation happens without rebuilding the full payload; failed uploads remove temporary/final files and do not leave authoritative rows; successful uploads preserve artifact ownership, hash, media type and Pending/QA lifecycle.

#### 3. Upload surface inventory

| Upload path | Runtime status | Media | Before | After |
|---|---|---|---|---|
| `/api/v2/projects/{project_id}/asset-intake` | Active V3 path; delegates to `asset_intake` | image/video/audio/reference | `await file.read(MAX_UPLOAD+1)` and `write_bytes(raw)` | Shared staged upload, 1MiB reads, incremental hash/size, bounded inspection prefix, atomic finalize, DB compensation |
| `/api/assets/upload` | Legacy helper retired by V3 gateway | image/video/audio | Same full-memory read | Same shared staged upload implementation |
| `/api/audio/import` | Legacy helper retired by V3 gateway | audio | `await file.read(MAX_AUDIO_UPLOAD+1)` and `write_bytes(raw)` | Same shared staged upload implementation, preserved 25MiB limit and response semantics |
| Frontend `FormData` upload | Active client path | image/video/audio | `FormData.append('file', file)` | Unchanged; no `FileReader`, `arrayBuffer`, data-URL or base64 upload path found |
| Provider download / generated base64 responses | Not user-upload paths | provider/generated media | Existing separate I/O behavior | Not changed in this phase |

No other active multipart file-body endpoint was found. Artifact map/register endpoints receive metadata, not file bodies.

#### 4. Root cause and implementation

- Reproduction before the fix: the deterministic guarded stream observed `read(1073741825)` on `/api/assets/upload`; the test failed before any bounded write could occur.
- Added `frameflow/upload_storage.py` with one central `UPLOAD_CHUNK_SIZE = 1 MiB`.
- `stage_upload()` reads only `await upload.read(UPLOAD_CHUNK_SIZE)`, counts actual bytes, updates SHA-256 incrementally, retains at most a 1MiB inspection prefix, and writes to a same-directory `.uploading` file.
- `UploadTooLarge` stops the stream as soon as the actual byte count exceeds the endpoint limit; it does not trust Content-Length as the authoritative size.
- `finalize_staged_upload()` uses `os.replace` after validation. `cleanup_staged_upload()` removes interrupted/invalid temporary files.
- `asset_audit.technical_validation()` now accepts an inspection prefix plus authoritative streamed `total_size` and `sha256`; it preserves signature, extension, MIME and media semantics without re-reading the complete payload into memory.
- V3 intake finalizes only before artifact insertion, deletes the final file and new artifact/event rows on registration/event failure, and retains `mapping_required`/Pending authority semantics. No upload becomes Approved, active or delivery-ready merely because bytes were written.

#### 5. Targeted tests and failure paths

- `python -m unittest tests.test_upload_streaming -v` → `10/10 PASS` after the valid-small-image coverage was added.
- Final related command `python -m unittest tests.test_upload_streaming tests.test_manual_workflow_v3 tests.test_asset_v3_improvements tests.test_v3_delivery` → `39/39 PASS`.
- Bounded-read regression: multi-chunk guarded stream; largest application read `1,048,576` bytes.
- Incremental hash/write regression: `2,097,192`-byte payload; 4 reads including EOF; exact final bytes and SHA-256.
- Mid-stream failure: synthetic read exception; temp and final files absent.
- Oversize: limit-plus-one stream; `UploadTooLarge`/HTTP `413`; temp, final and authority absent.
- Invalid signature: HTTP `422`; no artifact and no file.
- DB/event failure: HTTP `500`; final file and artifact row removed.
- Valid small image: accepted with exact bytes/hash and `mapping_required` status.
- Valid multi-chunk video: accepted with exact bytes/hash and zero asset-version promotion.
- Legacy audio helper: bounded multi-chunk read, exact bytes/hash and preserved response fields.

#### 6. Memory / streaming evidence

- Central chunk size: `1,048,576` bytes.
- Deterministic payload: `2,097,192` bytes; `4` reads; largest application read `1,048,576` bytes.
- Full payload bytes object: not constructed by FRAMEFLOW application code; only a bounded inspection prefix is retained.
- No RSS threshold was invented; deterministic guarded-read evidence is the primary proof.
- Aggregate concurrent-upload admission control remains outside this finding; the bound is per in-flight upload, while framework multipart spooling remains an independent runtime layer.

#### 7. Live positive path

- Workbench: `http://127.0.0.1:8787`.
- Temporary project: `AUDIT_TEST_P2_012_8086b41a` / `PRJ_2A69F1F87750`.
- Source fixture: existing `10,439,695`-byte MP4, read-only client input.
- Upload: HTTP `200`; artifact status `mapping_required`; no QA/active-version promotion.
- Physical final size: `10,439,695` bytes.
- Reported and independently computed SHA-256: `e436bea9365d000748c5e672baf74e739e9dc8f830347f0124cf6edc1981312a`; match `true`.
- Cleanup: project delete `200`, artifact file and empty temporary directories removed, project absent from active list.

#### 8. Live negative and security path

- Malicious upload Origin `https://evil.example` → `403`; asset-audit total remained `0`; temporary project delete `200`.
- Existing TrustedHost/Origin middleware remained active on the upload path.
- No new artifact mismatch or unregistered media was created by this phase.

#### 9. Full regression

- Python: `python -m unittest discover -s tests -p 'test*.py'` → `123/123 PASS` in `28.233s`.
- Vitest: root `npm test` → `7 files / 33 tests PASS`.
- TypeScript: `npx tsc -b --pretty false` → PASS.
- Production build: `npm run build` → PASS; existing >500KB warning remains in FF-P2-015 scope.
- Playwright: `npm run test:e2e -- --workers=1` → `9/9 PASS`.
- DB: read-only `PRAGMA integrity_check = ok`; `PRAGMA foreign_key_check = []`; schema `15`; `user_version = 0`; no migration.
- `git diff --check` remains clean apart from normal line-ending warnings on pre-existing dirty files.
- Phase-8 performance regression: `NOT REQUIRED`; Asset Library/Dashboard/query/virtual-list paths were not modified.

#### 10. Workbench smoke and data-integrity note

- Root, main shell, project manager and upload-related workspace rendered in the actual 8787 browser smoke; no page or console errors.
- The upload drop zone is asset-selection dependent; the smoke verified the workspace and upload copy/file-input contract without mutating the formal project.
- Read-only system data audit remains `ok=false` because of pre-existing protected/miscellaneous orphan state (`PRJ_F3843DF0760F`, `PRJ_32B543F4B566` and earlier audit temp directories). Current phase added no new orphan, artifact mismatch, broken artifact, unregistered media, orphan row, asset-version, QA, reference or lineage issue. No automatic recovery or deletion was performed.

#### 11. Files changed and database

- `server.py`: replaced all three upload helper full-memory reads with the shared staged upload path and compensation.
- `frameflow/upload_storage.py`: new bounded streaming, hash, staging, finalize and cleanup utility.
- `frameflow/asset_audit.py`: technical validation now accepts streamed size/hash plus bounded inspection bytes.
- `tests/test_upload_streaming.py`: deterministic bounded-read, hash, multi-chunk, oversize, interrupted-read, invalid, DB-failure, small-image, video and audio regressions.
- `FRAMEFLOW_REMEDIATION_PROGRESS.md`: this Phase 9.3 report.
- Database changes: `NONE`; no formal migration, reset, truncate, recovery apply or historical media rewrite.

#### 12. Regression protection and inventory

- Preserved: `FF-P1-001`, `FF-P1-006`, `FF-P1-009`, `FF-P2-010`, `FF-P2-011`.
- `P0 = 0`; `P1 = 0`; `P2 = 7`; `P3 = 3`.
- `FF-P2-010 = VERIFIED`
- `FF-P2-011 = VERIFIED`
- `FF-P2-012 = VERIFIED`
- `FF-P2-013 = OPEN`
- `FF-P2-014 = OPEN`
- `FF-P2-015 = OPEN`
- `FF-P2-016 = OPEN`
- Remaining risk: the 1MiB bound is per in-flight upload; aggregate concurrency and framework-level multipart spool behavior are deployment considerations, not a demonstrated FF-P2-012 failure.
- Next recommended action: Phase 9.4 — `FF-P2-013` actor/reason/before-after audit trail coverage. Do not execute it in this task.

---

# FRAMEFLOW V3 — Phase 9.4 Result

## 1. Final decision

`FF-P2-013 = VERIFIED`.

The verified scope is the authoritative finding from the initial report: ordinary project/story editing lacked a unified durable actor/reason/before/after contract, and the manual approval path used the fixed `studio-user` string. This phase does not replace specialized runtime telemetry or complete P2-014/P2-015/P2-016.

## 2. Authoritative finding and evidence boundary

The initial audit supplied only a summary row for P2-013; it did not supply an independent reproduction, expected/actual field matrix, root-cause section, or acceptance test. Phase 9.4 established the missing evidence before implementation:

- `PATCH /api/v2/projects/{project_id}` persisted a name change, but the required audit query surface did not exist (`404`).
- `asset_events`, `task_events`, workflow events, and approval records were specialized tables and did not share one actor/action/target/reason/before/after/result contract.
- `studio-user` was a fixed value in `manualProductionApproval.approvedBy`, not an authenticated identity.

## 3. Architecture distinction

1. Data-integrity audit remains the read-only `system/data-audit` scanner.
2. Runtime/task/workflow/asset event tables remain operational telemetry.
3. `audit_events_v16` is the durable, queryable business audit trail.

The unified record contains `actor`, `action`, `target_type`, `target_id`, `reason`, `before`, `after`, `result`, `metadata`, and `created_at`. JSON snapshots are redacted for secret-like keys and never contain raw media or credentials.

## 4. Mutation surface coverage matrix

| Mutation surface | Unified event(s) | Consistency | Result |
|---|---|---|---|
| Project create/update/delete | `project_created`, `project_updated`, `project_deleted` | Same DB transaction; delete history retained | VERIFIED |
| Story edit/rollback | `story_updated`, `story_rolled_back` | Same project-document transaction | VERIFIED |
| Logical asset create/duplicate/update/delete | `asset_created`, `asset_duplicated`, `asset_updated`, `asset_deleted` | Document, relation replacement, prompt row and audit share one transaction | VERIFIED |
| Prompt create / Prompt QA | `prompt_version_created`, `prompt_qa_decision` | Prompt creation and projection share one transaction | VERIFIED |
| Artifact intake / QA decision | `artifact_intake`, `qa_decision_submitted` | Recorded after successful mutation | VERIFIED |
| Manual approval/revoke | `manual_production_approved`, `manual_production_approval_revoked` | Same project-document transaction | VERIFIED |
| GET/navigation/projections/health | None | Read-only or operational telemetry | Intentionally excluded |

Specialized workflow/task/render/agent events remain separate; no historical events were fabricated.

## 5. Root cause

The application had subsystem-specific append-only tables while ordinary project/story writes went directly through document persistence. There was no central contract, writer, reader, redaction policy, stable local actor convention, or transaction hook for ordinary edits.

## 6. Audit contract

- Actor: `local-operator` for the single-user loopback workbench; this is not an authentication claim.
- Action/target: stable action code plus typed target and stable ID.
- Reason: stable reason code; free-text rationale remains in redacted metadata where needed.
- Before/after: bounded canonical snapshots of the changed authority, not binary rows.
- Result: `success` is written only within the committed mutation transaction.
- Timestamp/ID: UTC ISO-8601 plus unique `AUD_...` ID.
- Query: newest-first, project-scoped, bounded to 1–200 events at `/api/v2/projects/{project_id}/audit-events`.

## 7. Implementation

- Added `frameflow/audit_trail.py` with central writing/query/redaction/field validation.
- Added the project-scoped audit endpoint.
- Added transaction-aware project persistence and relation replacement hooks.
- Replaced `studio-user` with `local-operator`.
- Kept specialized events as telemetry and did not backfill invented history.
- Excluded intentionally retained deleted-project audit history from orphan-live-row data-integrity reporting.

## 8. Database changes

Formal `v15 → v16` was applied only after verified backup `BACKUP_ff04e0ef4eff25f9`:

- Backup integrity: `ok`; media manifest: 110 files / 461,022,766 bytes.
- Added `audit_events_v16` and project/time plus target/time indexes.
- No FK to `projects`, so deletion history survives project deletion.
- Post-migration max: `16`; `PRAGMA integrity_check = ok`; `PRAGMA foreign_key_check = []`; project count remained `2`.
- No reset, truncate, recovery apply, or historical media rewrite.

## 9. Targeted tests

`python -m unittest tests.test_audit_trail -v` → `5/5 PASS`.

Coverage includes complete fields, story/asset before-after snapshots, Prompt reason, secret redaction, isolated migration/count/integrity/FK checks, and audit-write rollback.

## 10. Consistency/failure tests

- Injected audit writer failure during project PATCH → HTTP 500; project name/revision unchanged; no `project_updated` event.
- Prompt creation, asset document update, relation replacement, and audit insert share one SQLite connection.
- Failed validations and rolled-back writes do not create fabricated success history.
- Delete writes `project_deleted` before deleting the project row in the same transaction.

## 11. Live verification

Workbench: `http://127.0.0.1:8787`.

Live temporary probe `PRJ_2194C74598E8` produced and queried:

```text
actor=local-operator
action=project_updated
target_type=project
target_id=PRJ_2194C74598E8
reason=project_metadata_updated
before.name=FF-P2-013 live audit probe
after.name=FF-P2-013 live audit probe updated
result=success
created_at=2026-08-24T10:03:42.069853+08:00
```

After deletion, the endpoint returned `project_exists=false` and retained `project_deleted`, `project_updated`, and `project_created`. The empty temporary directory from the probe was verified empty and removed explicitly; no existing project or media directory was touched.

## 12. Full regression

- Python: `python -m unittest discover -s tests -p 'test_*.py'` → `128/128 PASS`.
- Vitest: `npm test` → `7 files / 33 tests PASS`.
- TypeScript/build: `npm run build` → PASS; the existing >500KB bundle warning remains in FF-P2-015 scope.
- Playwright: `npm run test:e2e -- --workers=1` → `9/9 PASS` after retrying the initial sandbox `spawn EPERM` outside the browser-worker sandbox.
- Live DB: schema `16`, integrity `ok`, foreign-key violations `0`.
- Live data-integrity remains `ok=false` only for pre-existing protected state: missing `PRJ_F3843DF0760F` directory and unregistered directories `PRJ_32B543F4B566`, `PRJ_3420262B9478`, `PRJ_4496167982D3`, `PRJ_A70916F644F1`. Phase 9.4 added no new artifact, media, QA, lineage, or orphan-row issue.

## 13. Workbench

Live health after restart: `schema_version=16`, status `degraded` because provider readiness is environment-dependent. Browser/API regression remained green; no UI change was required because acceptance is API/durable-audit coverage.

## 14. Files changed

- `server.py`
- `frameflow/database.py`
- `frameflow/audit_trail.py`
- `frameflow/asset_audit.py`
- `frameflow/maintenance.py`
- `frameflow/data_integrity.py`
- `tests/test_audit_trail.py`
- `FRAMEFLOW_REMEDIATION_PROGRESS.md`

## 15. Regression protection

Preserved and rechecked: `FF-P1-001`, `FF-P1-004`, `FF-P1-006`, `FF-P1-009`, `FF-P2-010`, `FF-P2-011`, and `FF-P2-012`. No regression was observed in upload streaming, loopback security, FK boundaries, or existing workbench flows.

## 16. Inventory

- `P0 = 0`, `P1 = 0`, `P2 = 7`, `P3 = 3`.
- `FF-P2-010 = VERIFIED`
- `FF-P2-011 = VERIFIED`
- `FF-P2-012 = VERIFIED`
- `FF-P2-013 = VERIFIED`
- `FF-P2-014 = OPEN`
- `FF-P2-015 = OPEN`
- `FF-P2-016 = OPEN`

## 17. Global status

`GLOBAL = NOT READY`. No full re-audit and no GO decision is authorized by this phase. Existing protected data-integrity findings remain open and were not auto-repaired.

## 18. Remaining risk

The current actor is a truthful local operator label because the workbench remains loopback-only and has no authentication. If multi-user or remote operation is introduced, this contract must receive a real authenticated principal before that boundary changes. Specialized runtime event tables also remain separate by design.

## 19. Next

Recommended next action: Phase 9.5 — `FF-P2-014` accessibility remediation. Do not enter Phase 9.5 automatically.
