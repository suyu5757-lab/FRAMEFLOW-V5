# FRAMEFLOW V5.3.2

## T00–T03 Implementation Audit

Audit date: 2026-08-26 (Asia/Shanghai)  
Audit mode: inspection, safe verification, and temporary-database testing only. No Runtime, Schema, Skill, Workbench, sync script, legacy asset, or production database was modified.

### 1. Executive Verdict

| Task | Status | Verdict basis |
| --- | --- | --- |
| T00 | PASS | The required freeze documents are substantive, aligned to the supplied V5.3.2 contract, and committed independently as `7e405b4`. |
| T01 | PARTIAL | Reality checks exist in the T00 baseline, but no repository audit classifies the existing surface as KEEP / MIGRATE / REFACTOR / LEGACY / DELETE_LATER. |
| T01.5 | FAIL | No actual daily Git auto-sync script exists in the audited scope; required G1–G5 coverage is incomplete. |
| T02 | FAIL | Declarative schema, ShotSpec, and offline Alembic SQL exist and have unit evidence, but the target Runtime DB is still an incompatible V3 41-table schema; no safe online/backup migration path or real Alembic upgrade/downgrade test exists. |
| T03 | FAIL | The isolated StateStore works, but it is not integrated with the target DB/application. `data/frameflow.db` remains the legacy Runtime database and is not the V5.3.2 11-table StateStore. |

Gate 0 — MIGRATION SAFE = **FAIL**  
Milestone 1A overall = **FAIL**  
READY FOR T05 = **NO**

The audit used the complete contract supplied in the task text. A physical file named `FRAMEFLOW_最终留存版_V5.3.2_FINAL_正确版_展开版_归档主计划.md` was not found under the four mandated audit roots; that evidence-location gap is recorded as P2-003.

### 2. Current Git Reality

| Item | Observed value |
| --- | --- |
| Repo | `D:/11067/CodexWorkspaces/frameflow-v3` |
| Current branch | `dev/v5.3.2` |
| HEAD | `9b674b008ef417c548b27ccb2dea49d76ad5eb2b` — `feat(runtime): SQLite WAL StateStore (11-table persistence)` |
| Remotes | `origin` = `https://github.com/suyu5757-lab/video-workbench.git`; `local-source` = missing desktop path `C:\Users\11067\Desktop\video 工作台制作` |
| Dirty state | Dirty before the audit: 9 tracked M/D paths and many untracked V3-era paths. Git additionally warned it could not open two `pytest-cache-files-*` directories. |
| Merge / rebase | No `MERGE_HEAD`, `rebase-merge`, or `rebase-apply` marker found. |
| Stable tag | Annotated `v5.3.2-gate0-baseline` (`d5d555f` tag object) resolves to `7e405b4cfa8f8e91ed58863e1114c6bfcf7b6641`, dated 2026-08-26. |
| Development branch | `dev/v5.3.2`; it is three commits ahead of `main`. `main` remains at `7e405b4`. |
| Auto-sync script | Not found. No executable Git-command match was found in the scanned project, Skill repository, or historical tree scripts. |

Recent relevant commits:

1. `9b674b0` — StateStore source/tests.
2. `b11a074` — schema, ShotSpec, migration skeleton/tests.
3. `488f0f1` — Gate 0 documentation.
4. `7e405b4` — T00 architecture freeze.

### 3. T00 Audit

| Requirement | Status | Evidence | Gap |
| --- | --- | --- | --- |
| `BASELINE_V5_3_1.md` is a substantive pre-refactor baseline | PASS | `docs/BASELINE_V5_3_1.md:3-71` records paths, V3 surface, Skills, historical tree, ComfyUI, DB, and Git baseline. | None material. |
| `FRAMEFLOW_V5_3_2_SCOPE.md` freezes the supplied contract | PASS | `docs/FRAMEFLOW_V5_3_2_SCOPE.md:5,13-17,23-150` explicitly covers system identity, Shot, roots, read-only history, ComfyUI boundary, Seedance/Manual Bridge, SQLite WAL, 11 tables, task/lock/idempotency, four routes, three QA dimensions, typed/non-destructive actions, and migration safety. | Physical master-plan file was not discoverable; the supplied task text was used as authority. |
| `ARCHITECTURE_DECISIONS.md` has ADR-001 through ADR-015 with substance | PASS | Headings at `docs/ARCHITECTURE_DECISIONS.md:7,13,...,91`; each ADR includes a decision and consequence. | None material. |
| `GIT_SYNC_AUDIT.md` exists and differentiates T00 from T01.5 | PASS | `docs/GIT_SYNC_AUDIT.md:1-28,114-202`; T00 snapshot plus appended T01.5 evidence. | The later Gate conclusion is independently re-audited below. |
| Independent T00 Git evidence | PASS | Commit `7e405b4cfa8f8e91ed58863e1114c6bfcf7b6641`, 2026-08-26, subject `docs: freeze FRAMEFLOW V5.3.2 final architecture`; added exactly the four requested T00 docs. | None. |

### 4. T01 Audit

| Requirement | Status | Evidence | Gap |
| --- | --- | --- | --- |
| Real repository/root/branch/remote facts identified | PASS | Current Git evidence in section 2; T00 baseline `docs/BASELINE_V5_3_1.md:13-71`. | The result is embedded in T00 rather than a separate T01 repository audit. |
| KEEP / MIGRATE / REFACTOR / LEGACY / DELETE_LATER classification | NOT_IMPLEMENTED | Search of `docs`, `README.md`, and `T01.5_GATE0_CODEX指令.md` found no such classification record. | Required T01 decision inventory is absent. |
| Skill reality check | PASS | `D:\11067\CodexHome\skills` contains `image-blending`, `image-copy`, `image-explore`, `seedance-shot-packager`, and the nine listed video packages; `D:\AIGC\SUYU` contains `image skill`, `video skill`, and `seedance skill`. No `photo repair skill` directory exists in the historical root. | Existing provider/QA/post packages are noted by baseline but not classified for migration. |
| Workbench reality check | PARTIAL | Real frontend is `web\` (Vite/React); backend/API surface is `server.py`; existing V3 runtime/database are `frameflow\runtime.py` and `frameflow\database.py`. | Planned `workbench\` root is absent; no formal T01 comparison/audit of APIs and state ownership was found. |
| Comfy reality check | PARTIAL | `D:\ComfyUI` exists with `models`, `custom_nodes`, `input`, and `output`; project has provider-adapter references. | No FRAMEFLOW `comfy bridge`, `registry`, or `adapter` root in the planned location was found. |

### 5. T01.5 Audit

#### Git commands inventory

No actual daily auto-sync script was found, so there is no executable command inventory to classify. The scanned project, Skill, and historical executable candidates had zero Git command matches. `docs/GIT_SYNC_AUDIT.md:20-28` and `docs/MIGRATION_SAFETY.md:53-83` are policy/documentation, not a runnable sync mechanism.

| Class | Observed result |
| --- | --- |
| SAFE | Inspection commands were used by this audit. A future script policy permits status/add/commit/push-current-branch only under controls. |
| REVIEW | Documentation designates `pull --rebase` and `merge` as review-only. No executable implementation found. |
| FORBIDDEN | No forbidden executable command was found; policy prohibits reset/checkout/restore/clean/force-push/automatic main merge/automatic branch switch. Absence of a script cannot prove runtime enforcement. |

| Requirement | Status | Evidence | Gap |
| --- | --- | --- | --- |
| Stable snapshot/tag | PASS | Annotated `v5.3.2-gate0-baseline` resolves to `7e405b4`; tagger date 2026-08-26. | Local-only; no remote publication was claimed. |
| Separate development branch | PASS | Local `dev/v5.3.2` exists and contains T01.5/T02/T03 commits; `main` remains `7e405b4`. | None. |
| Actual daily Git auto-sync script | FAIL | Script discovery and executable scan returned no sync mechanism in mandated scopes. | T01.5 explicitly requires locating/reading the real script. |
| Detect current branch and push current branch | NOT_VERIFIED | No script implementation exists to inspect or exercise. | Cannot verify dynamic branch targeting or absence of hard-coded `main`/`master`. |
| Dirty/merge/rebase abort-safe behavior | PARTIAL | `docs/MIGRATION_SAFETY.md:53-77` defines ABORT SAFE policy. Current repo has no merge/rebase markers. | No executable automation or isolated repo test proves enforcement. |
| Change classification policy | PASS | `docs/MIGRATION_SAFETY.md:9-43` defines INTERNAL/NON_BREAKING/BREAKING and requires adapter, migration script/test, rollback test, deprecation note. | Policy is present; no Skill change was in scope to exercise it. |
| Rollback test | PARTIAL | Git objects exist: probe `91fb0c3` and revert `56c518b`; document record at `docs/GIT_SYNC_AUDIT.md:196-202`. | It proves a disposable Git revert, not restoration and execution of an old Skill function from the stable tag. |

| Gate test | Status | Evidence |
| --- | --- | --- |
| G1 — Skill change on dev pushes dev and leaves main unchanged | NOT_VERIFIED | No Skill-change/push test and no sync script. Branch separation exists only. |
| G2 — unmerged file stops sync | NOT_VERIFIED | Policy says abort; no implementation/test. |
| G3 — dev branch does not switch to main | NOT_VERIFIED | Policy says no automatic switching; no implementation/test. |
| G4 — dirty tree never reset/restored/cleaned | NOT_VERIFIED | Current dirty tree is preserved and policy prohibits the commands, but no automation test exists. |
| G5 — stable tag restores old Skill function | NOT_VERIFIED | Probe/revert did not run a legacy Skill function from the tag. |

### 6. T02 Audit

| Requirement | Status | Evidence | Gap |
| --- | --- | --- | --- |
| 11-table schema declaration | PASS | `core/schemas/runtime_mvp.py:34-250` declares exactly the required 11 tables; schema tests passed. | Declaration is not the target DB. |
| Required key fields and removal of `generations.package_id` | PASS | `runtime_mvp.py:110-239`; `tests/schema/test_runtime_mvp_schema.py` checks required columns and absence of `package_id`. | Only declaration/test evidence. |
| Actual target schema matches 11-table Runtime MVP | FAIL | Read-only `data/frameflow.db` introspection: 41 tables; only `projects`, `tasks`, `artifacts` intersect, and all three have incompatible V3 columns. Missing: `assets`, `events`, `generations`, `provider_submissions`, `resource_locks`, `reviews`, `sequences`, `shots`. | Blocking migration/schema drift. |
| ShotSpec v2.2 — 17 core and 14 optional fields | PASS | `core/schemas/shot_spec_v2.2.schema.json`; `tests/schema/test_shot_spec_v2_2.py` passed and checks 31 fields/default null extensions. | None in source contract. |
| Legacy SH001–SH003 migration | PASS | `scripts/migrate_shot_spec_v1_to_v2_2.py:153-251`; `tests/migration/test_migration_v1_to_v2_2.py` passed five tests for SH001/SH002/SH003, schema validation, immutability, and round-trip intent. | Migration is in-memory ShotSpec only; it does not migrate the Runtime database. |
| Alembic upgrade | PARTIAL | `core/migration/versions/20260826_01_runtime_mvp.py:25-31`; `python -m alembic ... upgrade head --sql` exited 0 and emitted all 11 tables. | `core/migration/env.py:37-43` intentionally rejects online execution; no isolated real Alembic-upgrade test or target DB migration evidence. |
| Alembic downgrade | PARTIAL | `downgrade head:base --sql` exited 0 and emitted reverse drops. | SQL emission is not a real applied downgrade/rollback test. |
| Backup before migration | NOT_IMPLEMENTED | No V5.3.2 Alembic backup mechanism/test found. Legacy V3 backups do not satisfy this new migration requirement. | Required safe-migration evidence absent. |
| Migration tests | PARTIAL | ShotSpec migration tests exist and pass; schema declaration tests pass. | No test applies and reverses the Alembic revision against a fresh/legacy database. |

### 7. T03 Audit

| Requirement | Status | Evidence | Gap |
| --- | --- | --- | --- |
| Target DB path | FAIL | `data/frameflow.db` exists, but read-only introspection found legacy 41-table V3 schema rather than V5.3.2 Runtime MVP. | Target path is not migrated to the declared StateStore schema. |
| WAL | PARTIAL | Target DB reports `journal_mode=wal`; isolated StateStore reports `wal`. | The target DB's WAL is managed by legacy `frameflow/database.py:1019-1034`, not verified through StateStore. |
| `foreign_keys=ON` reality | FAIL | Read-only target connection reported `foreign_keys=0`. Legacy `Database.connect()` enables it per connection (`frameflow/database.py:1002-1010`), but StateStore is not the application path. | Contract needs V5.3.2 runtime connection behavior, not only legacy per-connection setup. |
| `busy_timeout=5000` | PARTIAL | Target raw connection reported 5000; isolated StateStore reported 5000. | No StateStore production connection is used by the app. |
| StateStore abstraction | PARTIAL | `core/runtime/state_store/store.py:56-263` provides engine setup, initialization, transaction/connection context managers, commit/rollback via `engine.begin()`, and `close()`. | Only projects/sequences/shots/assets/artifacts/generations have specific facade methods; no application integration, TaskStore, lock, submission, or review facade exists. |
| Commit / rollback / reopen | PASS (isolated) | Custom isolated DB test passed: persisted write/reopen; forced exception left `PRJ_ROLLBACK` absent. | Does not establish production DB state. |
| FK enforcement | PASS (isolated) | Custom isolated DB test received `IntegrityError` for sequence with missing project. | Target DB runtime path remains legacy. |
| WAL file behavior | PASS (isolated) | Custom isolated DB observed `wal_file_exists=True` during write. | Does not establish target integration. |
| Schema definition vs actual DB | FAIL | Declarative 11-table schema conflicts with target 41-table V3 database; details in section 6. | P0 schema drift. |
| Legacy Runtime conflict / SQLite source of truth | FAIL | `frameflow/database.py:994-1061` owns `data/frameflow.db`, runs legacy migrations 1–16, and is used by V3 application surface. Search found `StateStore(` only in `tests/runtime/test_state_store_wal.py`. | Two incompatible runtime designs coexist; V5.3.2 SQLite StateStore is not the active source of truth. |

### 8. Test Evidence

| Command | Result | Passed / failed / skipped | Duration / note |
| --- | --- | --- | --- |
| `python -m unittest discover -s tests/schema -p 'test_*.py' -v` | PASS | 10 / 0 / 0 | 0.087 s reported. |
| `python -m unittest discover -s tests/migration -p 'test_*.py' -v` | PASS | 5 / 0 / 0 | 0.001 s reported. |
| `python -m unittest discover -s tests/runtime -p 'test_*.py' -v` | BLOCKED | 0 / 9 errors / 0 | 1.08 s total command; test setup could not open default `C:\Users\11067\AppData\Local\Temp` in sandbox. This is not treated as a code PASS. |
| Isolated StateStore test on explicit temporary DB | PASS | 1 scenario / 0 / 0 | Verified 11 tables, all three pragmas, FK rejection, forced rollback, WAL observation, and reopen persistence. Temporary DB was removed as one explicit file. |
| `python -m alembic -c core/migration/alembic.ini upgrade head --sql` | PASS | n/a | Exit 0; SQL emitted 11 tables. No DB write. |
| `python -m alembic -c core/migration/alembic.ini downgrade head:base --sql` | PASS | n/a | Exit 0; reverse drop SQL emitted. No DB write. |
| `python -m unittest discover -s tests -p 'test_v3.py' -v` | PASS | 28 / 0 / 0 | 5.371 s test time, 6.8 s command. Confirms the legacy V3 Runtime/migrations remain working, not that V5.3.2 is integrated. |

Target DB was queried read-only before/after testing. Final fingerprint: 3,657,728 bytes; SHA-256 `c22a480cbbeb6998eb3b71d9ff47890df60307a27b4b1f70f7e71dad7536c27f`; 41 tables. No production database write was made.

### 9. Findings

#### P0

| ID | Related Task | Requirement | Actual State / Evidence | Impact | Recommended Correction |
| --- | --- | --- | --- | --- | --- |
| P0-001 | T01.5 | Real daily auto-sync and G1–G5 safety validation | No executable sync script was found; G1–G5 are mostly NOT_VERIFIED. | Gate 0 cannot be passed; branch/dirty-tree safety is policy-only. | Locate the real scheduled/scripted sync mechanism or formally establish and test one in an authorized task; execute G1–G5 in an isolated repo. |
| P0-002 | T02 | V5.3.2 Runtime schema applied to target DB | `data/frameflow.db` has 41 V3 tables; required V5 tables/columns are absent or incompatible. | Schema contract is not active; T02 cannot support later Runtime tasks. | Design an authorized, backed-up migration strategy, then test real Alembic upgrade/downgrade against isolated legacy copies before production migration. |
| P0-003 | T03 | SQLite StateStore is Runtime Source of Truth | V3 `frameflow.database.Database` controls target DB; StateStore is referenced only by its tests. | Active runtime has a conflicting source-of-truth design; V5.3.2 persistence is not live. | Integrate a single V5 StateStore path only after P0-002 safe migration is verified; retire/bridge legacy truth explicitly under authorization. |

#### P1

| ID | Related Task | Requirement | Actual State / Evidence | Impact | Recommended Correction |
| --- | --- | --- | --- | --- |
| P1-001 | T01 | Repository classification | No KEEP/MIGRATE/REFACTOR/LEGACY/DELETE_LATER inventory found. | Migration decisions and ownership boundaries are not auditable. | Produce a real T01 inventory from current files/roots, including Workbench and Comfy bridge disposition. |
| P1-002 | T02 | Recoverable Alembic migration | Alembic is offline-only; no backup, applied upgrade/downgrade test, or target-migration evidence. | The migration cannot safely reach the actual DB. | Add tested backup, fresh/legacy-copy upgrade, downgrade, and rollback evidence in a future authorized task. |
| P1-003 | T03 | Complete Runtime persistence interface | StateStore only has domain helpers for six entity types; no task/lock/provider submission/review lifecycle interface. | Later runtime work would bypass or fragment StateStore behavior. | Define and verify complete persistence ownership after the schema path is safe. |

#### P2

| ID | Related Task | Requirement | Actual State / Evidence | Impact | Recommended Correction |
| --- | --- | --- | --- | --- |
| P2-001 | T03 | Reproducible project test environment | `.venv\Scripts\python.exe` lacks SQLAlchemy and Alembic; targeted V5 tests required system Python. | Project-local test execution is not reproducible. | In an authorized environment task, align the venv with declared dependencies and lock/test it. |
| P2-002 | T01.5 | Runtime test portability | Existing StateStore test uses default user temp directory and is blocked by this sandbox; an explicit isolated DB works. | CI/sandbox portability is unproven. | Make test temp location configurable or provide a sandbox-safe fixture. |
| P2-003 | T00 | Recoverable authority source | Physical master-plan filename was not found under mandated roots. | Future auditors cannot independently reopen the named source file from the stated locations. | Record or provide the canonical retained-plan path/hash without changing contract content. |

#### INFO

| ID | Related Task | Actual State |
| --- | --- | --- |
| INFO-001 | T00 | Required roots `frameflow-v3`, `CodexHome\skills`, `AIGC\SUYU`, and `ComfyUI` all exist. |
| INFO-002 | T01.5 | Stable tag and `dev/v5.3.2` branch exist and main stayed at the frozen T00 commit. |
| INFO-003 | T03 | Target DB has WAL at file level; the isolated StateStore implementation correctly configures three required PRAGMAs. |

### 10. Architecture Drift

**Drift exists.** The frozen V5.3.2 architecture requires an 11-table SQLite WAL StateStore at `data/frameflow.db`. The actual DB is a populated V3 database with 41 tables and migration versions 1–16. It has only overlapping table names `projects`, `tasks`, and `artifacts`, whose columns do not match the V5.3.2 contract. The active V3 code path (`frameflow/database.py`) creates/migrates that database separately from the new SQLAlchemy/Alembic/StateStore source.

The new V5.3.2 source is therefore **implemented and partly tested in isolation**, not **validated as the active Runtime architecture**.

### 11. Out-of-Sequence Changes

V3-era Runtime, provider, QA, recovery, workflow, server, and frontend surfaces already exist under `frameflow\`, `server.py`, and `web\`. These are pre-existing/parallel implementation surfaces, not evidence that T05+ V5.3.2 contracts are complete. The audit did not assess T05+ completion.

T02 and T03 source commits are on `dev/v5.3.2` after T01.5 documentation. Because Gate 0 is independently FAIL in this audit, they are recorded as **implemented after an unverified/failed migration gate**.

### 12. Gate Decision

Gate 0 — MIGRATION SAFE: **FAIL**

Reasons: the required actual daily Git auto-sync script is absent from audited scope; command behavior cannot be tested; G1–G5 are not fully verified; the claimed rollback does not prove stable-tag old-Skill functional restoration.

T00–T03 AUDIT RESULT: **NOT READY FOR T05**

