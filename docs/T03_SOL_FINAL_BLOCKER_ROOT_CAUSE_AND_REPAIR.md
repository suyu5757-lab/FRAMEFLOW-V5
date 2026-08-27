# FRAMEFLOW V5.3.2 — T03 Final Blocker Root Cause and Repair

Date: 2026-08-27

Branch: `dev/v5.3.2`

HEAD before repair: `fa9ef69e59a67cb860039f3c83a690ee0bc33a1e`

Production cutover performed: **NO**

Runtime source of truth: **LEGACY_V3**

## Executive Summary

The final pre-swap logical mismatch was caused by real migration
nondeterminism, not by comparing Candidate A after smoke with Candidate B
before smoke. The V3-to-V5 transform omitted `created_at` and `updated_at` on
four populated domain tables. SQLite therefore filled those columns from
`CURRENT_TIMESTAMP` when each candidate was created. Candidate A and Candidate
B were migrated 38 seconds apart and received different domain values despite
having the same frozen source, revision, schema, primary keys, and row counts.

The migration now preserves Legacy timestamps, derives child timestamps from
stable source project timestamps, uses a fixed fallback only when Legacy has no
timestamp, reads source rows in deterministic primary-key order, and derives
missing event identifiers from canonical source rows instead of UUIDs. The
equivalence gate now explicitly compares A0 with B0, stores all 11 table
fingerprints and canonical rows for field-level delta reporting, and audits A0
to A1 separately.

Fresh certification run:

`D:\11067\CodexWorkspaces\frameflow-v3\data\.cutover\T03SOL-CERT-20260827T132950Z-dfd7a77b`

Result: A0/B0 equivalence PASS, Candidate A launcher and restart PASS,
Candidate B closed-file and rename gates PASS, production untouched.

## Latest Abort Evidence

The preserved failed production run remains:

`T03FINAL-20260827T130400Z-b79f6806`

Its permanent archive intentionally contains only the frozen Legacy database
(1/5 files) because the run aborted before swap. It was not deleted or promoted
to a successful archive. Its staging evidence shows:

- Candidate A migration: `2026-08-27T13:04:12.512117+00:00`.
- Candidate B migration: `2026-08-27T13:04:50.231934+00:00`.
- Both source SHAs: `0fc5d85d3da9848ace81dd4bd3ce79625752d347e9dd6aa0915b6b4f1710b2b3`.
- Both row counts: identical.
- Candidate A first start/restart: 19/19 and 17/17.
- Candidate A fixture cleanup: PASS.
- Candidate B backend-opened: NO.
- Candidate B validation and rename: PASS.
- Final logical equivalence: FAIL; production replacement: NOT_PERFORMED.

The old Candidate B was not reopened during this repair. Its saved manifest and
the independent reproductions below were used instead.

## Historical Resolved Blockers

The repair does not reopen prior root causes. Cross-volume replacement, Windows
SQLite handle closure, restart-safe Legacy archive configuration, formal
project `.venv` dependencies, and the Candidate A/Candidate B contract had all
already been repaired and remain covered by regression tests.

## Current Root Cause

Classification: **MIGRATION_NONDETERMINISM**.

Before repair, inserts into `sequences`, `shots`, `assets`, and `artifacts`
omitted their domain timestamp columns. The V5 schema uses
`server_default=CURRENT_TIMESTAMP`, so migration wall-clock time became business
data. `tasks.created_at` had the same latent defect for any non-empty source.
Projects and derived events also had wall-clock/UUID fallback paths for missing
Legacy values.

A controlled cross-second reproduction from the exact failed frozen source
produced:

```text
A0 started = 2026-08-27T13:20:58.375704+00:00
B0 started = 2026-08-27T13:20:59.726949+00:00
A0 logical = 2c3d89d09ad5b4baf66a0fbf995a2ce6ee98e6f12467368a40ef8f2766350912
B0 logical = bef20b8915bb729104a17b9bf00b15e27b2aa388d4078725c89a0a16d3ec4f9c
different tables = sequences, shots, assets, artifacts
```

A same-second reproduction happened to pass, explaining how earlier A/B runs
could report deterministic equivalence while the defect remained.

## Actual Candidate Lifecycle Before Repair

```text
Candidate A created and migrated
  -> formal launcher first open
  -> Workbench 19/19
  -> SH004-SH020 17/17
  -> restart
  -> Workbench 19/19
  -> SH004-SH020 17/17
  -> fixture cleanup
  -> Candidate A logical fingerprint captured (AFTER_SMOKE)

Candidate B independently created later
  -> migration
  -> validation
  -> logical fingerprint
  -> rename probe
  -> never opened again

Gate compared A post-smoke evidence with B pre-swap evidence.
```

Although that timing was ambiguous and has been repaired, the saved row counts,
fixture cleanup, fresh A0/A1 audit, and cross-second reproduction prove the
observed mismatch was generated during migration. Smoke did not change the
remaining domain state.

## A0 / A1 / B0 Definitions

- **A0**: Candidate A after migration and validation, before its first backend
  open. It carries source SHA, migration revision/implementation, schema
  contract/fingerprint, all 11 table fingerprints and rows, business PKs, and
  row accounting.
- **A1**: the same Candidate A after first start, 19/19, 17/17, restart,
  19/19, 17/17, backend shutdown, explicit fixture cleanup, and handle release.
  It is used only for smoke delta audit.
- **B0**: independently migrated Candidate B after short-lived SQLite
  validation and before its rename probe. It is never backend-opened and is not
  reopened after rename.

The final migration-equivalence comparison is A0 versus B0. A1 is never used as
a substitute migration baseline.

## Mismatch Table Analysis

The prior mismatch and the independent cross-second reproduction both resolve
to these tables:

| Table | Differing field | Classification |
|---|---|---|
| `sequences` | `created_at` | MIGRATION_NONDETERMINISM |
| `shots` | `created_at`, `updated_at` | MIGRATION_NONDETERMINISM |
| `assets` | `created_at` | MIGRATION_NONDETERMINISM |
| `artifacts` | `created_at` | MIGRATION_NONDETERMINISM |

No table was excluded from the logical fingerprint. `events`, `tasks`,
`generations`, `provider_submissions`, and every other V5 domain table remain
inside the 11-table gate.

## Mismatch Row / PK Analysis

- `sequences`: `SQ001`.
- `shots`: `SH001`, `SH002`, `SH003`.
- `assets`: `BLEND_SH004`, `BLEND_SH006`, `BLEND_SH007`, `BLEND_SH008`,
  `BLEND_SH009`, `BLEND_SH018`, `C001`-`C008`, `P001`-`P004`, and
  `S001`-`S008`.
- `artifacts`: all 31 preserved artifact PKs, from
  `ART_00be69a94d7a1cac` through `ART_fedaa7828f52714f`, as enumerated in the
  fresh A0/B0 evidence.

There were no only-in-A or only-in-B primary keys and no row-count differences.
The exact changed fields were solely the migration-generated timestamps above.

## Code Changes

- `core/migration/v3_to_v5.py`
  - explicitly persists deterministic timestamps on every migrated populated
    domain table;
  - preserves source artifact, asset-version, task, project, and event times;
  - derives embedded sequence/shot/asset times from stable project source
    timestamps;
  - uses `1970-01-01T00:00:00+00:00` only when no source-derived timestamp
    exists;
  - orders every source read by primary key (or stable rowid fallback);
  - replaces derived-event UUID fallbacks with canonical row hashes.
- `core/migration/equivalence.py`
  - versions the deterministic migration implementation;
  - records explicit A0/A1/B0 stages;
  - compares A0 against B0;
  - stores canonical rows with each table fingerprint;
  - reports table, PK, row, and field deltas;
  - audits smoke deltas and fixture residues separately.
- `tests/migration/test_t02_runtime_migration.py`
  - proves two migrations more than one second apart have the same logical SHA.
- `tests/migration/test_candidate_equivalence.py`
  - covers F1-F12, including stage separation, cleanup failure, Candidate B
    safety, pre-swap immutability, and exact table/PK reporting.

Migration implementation version is now:

`v3_to_v5:20260826_01-deterministic-v2`

## Migration Determinism Analysis

Fresh Candidate A and Candidate B were created well apart in time from the same
frozen snapshot after the repair. Their schema SHA and logical SHA are exactly
equal:

```text
source SHA = 0fc5d85d3da9848ace81dd4bd3ce79625752d347e9dd6aa0915b6b4f1710b2b3
schema SHA = afaf402223dc29d9b33e9e3ad7fadc52aed94f7d907e8fb6e1f779e1f4b637db
A0 logical SHA = f469daa1b2746c3fe259e964d009e37070e277972fc6bd7d21a23229441acf59
B0 logical SHA = f469daa1b2746c3fe259e964d009e37070e277972fc6bd7d21a23229441acf59
```

All 11 table SHA values match. Physical SQLite file SHA is not used as logical
equivalence evidence.

## Smoke Mutation Analysis

The formal probe created two isolated `T03R2_*` projects, updated them, proved
the first survived restart, and then removed their project, sequence, and event
rows transactionally. A0 and A1 have identical logical SHA and identical table
fingerprints:

```text
A0 -> A1 different tables = none
rows inserted after cleanup = 0
rows modified after cleanup = 0
rows deleted from baseline = 0
Smoke fixture cleanup = PASS
classification = no net domain delta
```

No ignore list was introduced. A residual fixture would be classified
`TEST_CLEANUP_DEFECT` and fail the final gate. Other unexplained changes are
classified `UNEXPECTED_RUNTIME_SIDE_EFFECT` and also fail.

## Candidate A Formal Launcher Evidence

```text
Formal interpreter = D:\11067\CodexWorkspaces\frameflow-v3\.venv\Scripts\python.exe
First health = HTTP 200, runtime_mode=v5
Workbench first = 19/19
SH004-SH020 first = 17/17
Restart = PASS
Workbench restart = 19/19
SH004-SH020 restart = 17/17
Fixture cleanup = PASS
Rename probe = PASS
```

The isolated backend used port 8893 and was stopped.

## Candidate B Closed-File Evidence

```text
backend-opened = NO
domain tables = 11
schema drift = 0
integrity = ok
foreign_key_check = 0
journal_mode = WAL
foreign_keys = ON
busy_timeout = 5000
validation = PASS
rename = PASS
```

Candidate B was built independently from the frozen Legacy snapshot, not copied
from Candidate A. After its successful D: rename probe it was not opened again.

## A0/B0 Equivalence

```text
same frozen source = PASS
migration revision = PASS (20260826_01)
migration implementation = PASS
schema contract = PASS (runtime-mvp:5.3.2)
schema equivalence = PASS
logical data equivalence = PASS
business PK equivalence = PASS
row accounting equivalence = PASS
UNKNOWN = 0
UNACCOUNTED = 0
SH004-SH020 = 17/17
```

The 17 migration-unmapped rows are explicitly accounted Legacy read-only
compatibility records, not final unaccounted rows.

## Regression Tests

All tests used the formal project interpreter and workspace test temp root:

```text
tests/schema tests/migration tests/runtime = 104 passed
V3 regression subset = 37 passed
unique relevant total = 141 passed
failed = 0
blocked = 0
```

The only warning was the existing Starlette/httpx deprecation warning.

## Production Safety Audit

The current production database was audited read-only after all tests:

```text
path = D:\11067\CodexWorkspaces\frameflow-v3\data\frameflow.db
schema = LEGACY_V3
tables = 41
schema version = 16
integrity = ok
foreign key violations = 0
logical SHA = d75ca4d9611cba4c1e913ecfae0a0981870285983cb5d714045bc30a6a16646e
matches frozen source logical SHA = YES
data/runtime-startup.json = absent
production replacement = NO
intentional production modification = NO
atomic replacement = NOT_PERFORMED
dual write = NO
dual source of truth = NO
```

No production archive was created. All diagnostic databases and evidence are
under `data/.cutover` and are not staged.

## Independent Review

1. The root cause is reproduced across seconds and tied to exact SQL/schema
   defaults; it is not inferred from the prompt.
2. Final equivalence compares A0 with B0.
3. All 11 domain tables are covered with no expanded ignore list.
4. Migration nondeterminism is removed and cross-second regression-tested.
5. A0/A1 is separately audited and has no net domain delta.
6. Both smoke fixtures were removed.
7. Candidate A passed formal first start and restart, 19/19 and 17/17 twice.
8. Candidate B was never backend-opened and was not reopened after rename.
9. Production remains the same logical 41-table Legacy source of truth.
10. Tests failed=0 and blocked=0.

Independent review result: **PASS**.

## Remaining Risks

- The actual production cutover remains a separately authorized operation and
  must create a fresh permanent archive and fresh Candidate A/B evidence.
- Physical SQLite file hashes can differ after consistent backup or WAL
  checkpoint; logical table evidence remains the authoritative equivalence
  gate.
- The existing provider readiness deferral and dependency-locking risk remain
  outside this root-cause repair.

## Final Verdict

```text
STATUS = PASS
PRODUCTION CUTOVER = NOT_PERFORMED
RUNTIME SOURCE OF TRUTH = LEGACY_V3
ACTUAL ROOT CAUSE = MIGRATION_NONDETERMINISM
READY FOR FINAL PRODUCTION CUTOVER = YES
```

The required stop rule is active. No production cutover, runtime switch,
production archive creation, or canonical database replacement was performed.
