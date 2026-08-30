# FRAMEFLOW V5.3.2 — T00–T03 HOUSEKEEPING INVENTORY

Initial snapshot: 2026-08-27 21:52 Asia/Shanghai  
Branch: `dev/v5.3.2`  
HEAD: `5269824f9e2a830d84094b3779fdb51a741b1159`

## Execution boundary

The initial inventory was read-only. After explicit user authorization, only the listed reproducible cache/test files were removed. No archive move was performed.

Existing user changes were preserved: 10 tracked modifications, 5 pre-existing tracked deletions, and 52 untracked status entries. No `reset`, `restore`, `checkout`, `stash`, or `clean` operation was used.

## Baseline measurements

| Area | Files | Size | Classification |
| --- | ---: | ---: | --- |
| Workspace snapshot | 14,633 | 1,529.52 MB | KEEP / protected or user-owned content mixed |
| `data/.cutover` | 429 | 150.51 MB | Evidence; only explicit test-temp candidate below |
| `.tmp` | 4,946 | 922.03 MB | Reproducible test temporary output |
| Non-venv `__pycache__` / `*.pyc` | 15 dirs / 97 files | 2.38 MB | Reproducible cache |
| `archives/migrations/v5.3.2` | 23 | 18.48 MB | Permanent migration evidence; protected |

The `.tmp` and `.cutover` trees were changing during inspection, so counts are a point-in-time snapshot rather than a stable process metric.

## Post-clean observations

After cleanup and the requested regression, `.tmp/tests` was empty at the cleanup snapshot with 472 residual empty directories. A separate active process subsequently recreated 2 `.tmp/tests` files and 41 non-`.venv` `.pyc` files by the final snapshot; they were left in place. `data/.cutover` contains 460 files / 160.25 MB. The root `.pytest_cache` remains present but unreadable due Access Denied. No ACL was changed.

## Protected and retained inventory

| Path / scope | Size / count | Type | Classification | Action | Reason |
| --- | ---: | --- | --- | --- | --- |
| `data/frameflow.db` | 3.49 MB | Production SQLite DB | PROTECTED | KEEP | Canonical writable runtime database |
| `data/frameflow.db-wal`, `data/frameflow.db-shm` | 0 MB / 0.03 MB | SQLite companions | PROTECTED | KEEP | Must remain with production DB |
| `data/runtime-startup.json` | absent | Runtime config | PROTECTED | KEEP state absent | Runtime currently remains legacy-default |
| `.venv/` | not rescanned | Runtime environment | PROTECTED | KEEP | Formal interpreter and dependencies |
| `core/`, `frameflow/`, `server.py`, `scripts/`, `tests/`, `web/` | user-owned | Source/test tree | PROTECTED / KEEP | KEEP | Source and user dirty/untracked content |
| `requirements.txt`, `.gitignore`, project/migration config | user-owned | Project config | PROTECTED / KEEP | KEEP | Protected configuration |
| `archives/migrations/v5.3.2/` | 30 / 23.11 MB | Permanent migration archive | PROTECTED | KEEP | Rollback, migration, and audit evidence, including the newest rollback archive |
| `data/safety-backups/` and other `data/` DBs | present | Runtime/backups | PROTECTED / UNKNOWN | KEEP | Data scope; not safe to infer disposable status |
| `docs/*.md` | user-owned | Formal reports | KEEP | KEEP | Historical rationale and audit chain |
| `data/.cutover/T03SOL-CERT-20260827T132950Z-dfd7a77b` | 22 / 12.48 MB | Latest certification evidence | PROTECTED | KEEP | Current A0/A1/B0 and production-safety evidence |
| `data/.cutover/T03SOL-ROOTCAUSE-20260827T131952Z-13fc7e6b` | 10 / 7.80 MB | Root-cause evidence | PROTECTED | KEEP | Current nondeterminism investigation lineage |
| `data/.cutover/T03SOL-NONDET-20260827T132057Z-99b1a36a` | 10 / 7.80 MB | Root-cause reproduction | PROTECTED | KEEP | Current diagnostic lineage |
| `data/.cutover/T03FINAL-20260827T130400Z-b79f6806` | 12 / 7.81 MB | Latest failed final attempt | PROTECTED | KEEP | Referenced by formal blocker report |
| `data/.cutover/T03FINAL-20260827T135157Z-a483f658` | 31 / 9.73 MB | Newest final cutover/rollback evidence | PROTECTED | KEEP | Created during this audit window; latest evidence and rollback audit |
| `data/.cutover/T03SOL-FINAL-d1b2e318` | 7 / 3.99 MB | Repair evidence | KEEP | KEEP | Referenced by repair report |
| `data/.cutover/LUNA-DIAG-20260827T203919-490f4644` | 12 / 7.81 MB | Pre-cutover diagnostic | KEEP | KEEP | Referenced by LUNA verification report |
| `data/.cutover/T03R3C-20260826T155354Z-ac9a373c` | 11 / 7.83 MB | R3C evidence | KEEP | KEEP | Referenced by R3C cutover report |
| `data/.cutover/T03R3E-20260827T073218Z-1d10d139` | 8 / 3.74 MB | Rollback attempt evidence | PROTECTED | KEEP | Referenced by R3E report and permanent archive |
| `data/.cutover/T03ENV-20260827T093832Z-540a7e12` | 6 / 3.89 MB | Environment closure evidence | KEEP | KEEP | Referenced by environment closure report |
| `data/.cutover/T03FINAL-20260827T084503Z-b71c4c75` | 8 / 3.95 MB | Rolled-back final evidence | KEEP | KEEP | Formal rollback evidence |
| `data/.cutover/r3c-tests` | 228 / 17.04 MB | Test fixture/evidence | PROTECTED | KEEP | Referenced directly by `tests/runtime/test_t03_r3c_handles.py` |
| Existing dirty tracked and untracked paths | 62 entries | User workspace state | KEEP | KEEP | User files may not be guessed disposable |

## Cleanup candidates and execution

| Path / scope | Size / count | Type | Classification | Action | Reason |
| --- | ---: | --- | --- | --- | --- |
| `.tmp/tests/` | 5,116 files removed / at least 922.56 MB | Pytest/test temporary tree | SAFE_DELETE | DELETED | 4,954 initial files plus 133 from regression plus 29 from later test output |
| Non-venv `__pycache__/` and `*.pyc` | 150 files removed | Python bytecode cache | SAFE_DELETE | DELETED | 97 initial files plus 53 regenerated files; `.venv` excluded |
| Root `.pytest_cache/` | 1 dir / 0 readable files | Pytest cache | SAFE_DELETE | BLOCKED | Access Denied; no ACL change |
| `data/.cutover/pytest-temp/` | 29 files / 13.05 MB | Historical pytest temp staging | SAFE_DELETE candidate | NOT EXECUTED | No source/report reference found; still requires batch deletion |

Execution details:

- `.tmp/tests`: 4,954 initial files, 133 regression-generated files, and 29 later test files deleted; 2 files were recreated by an external process after cleanup and were retained.
- Non-`.venv` Python cache: 150 files deleted. 41 new bytecode files were recreated by an external process after cleanup and were retained.
- 472 empty `.tmp/tests` directories and root `.pytest_cache` remain because removal returned Access Denied.
- `data/.cutover/pytest-temp`, all other cutover runs, databases, archives, docs, source, and user files were not deleted.

## Ambiguous historical runs retained

The following run directories are not referenced by the searched current reports, but their evidence role could not be proven disposable. They remain retained as `UNKNOWN`:

- `T03R3B-20260826T152927Z-15c75194`
- `T03R3C-20260826T155235Z-49dc9233`
- `T03R3E-20260827T072959Z-9c19ca5f`
- `T03R3E-20260827T073121Z-65b39ab7`
- `T03ENV-20260827T092601Z-c3e2e97d`
- `LUNA-FINAL-PRE-20260827T203225-c35c0857`
- `LUNA-FINAL-PRE-20260827T203707-d6494908`
- `LUNA-FINAL-PRE-20260827T204053-e290b6c6`

No ambiguous item was deleted or moved.

## Other untracked generated-looking paths

`web/playwright-report/`, `web/test-results/`, `web/tsconfig.app.tsbuildinfo`, and `tests/test-v3-matrix-*.db` look generated, but they are user/untracked content in protected source/test areas. They remain `KEEP` pending explicit user classification. `tests/phase8-baseline.db` is also retained as `UNKNOWN`/user content.

During the cleanup window, `core/migration/cutover.py` and `tests/migration/test_runtime_startup_cutover.py` gained tracked modifications outside the cleanup scope. They were preserved as user changes.

## Runtime and database observations

- `data/runtime-startup.json` is absent.
- Read-only runtime inspection reports `LEGACY_V3` with 41 tables.
- Production `PRAGMA integrity_check` is `ok`.
- Production `PRAGMA foreign_key_check` returned no violations.
- Final inspection found no listener on local port 8787; no process was terminated.
- Final production journal mode was `delete` with no WAL/SHM companions. This correlated with the new `T03FINAL-20260827T135157Z-a483f658` rollback evidence timestamps; cleanup never targeted `data/`.
